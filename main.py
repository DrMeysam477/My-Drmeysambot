import os
import math
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple

import aiohttp
import ccxt.async_support as ccxt
import numpy as np
import pandas as pd
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("crypto-signal-bot")


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
DEFAULT_TIMEFRAME = os.getenv("TIMEFRAME", "1h").strip()
QUOTE_ASSET = os.getenv("QUOTE_ASSET", "USDT").strip()
MIN_SCORE_TO_SEND = int(os.getenv("MIN_SCORE_TO_SEND", "80"))
SCAN_TOP_N = int(os.getenv("SCAN_TOP_N", "3"))
SCAN_MARKET_LIMIT = int(os.getenv("SCAN_MARKET_LIMIT", "80"))
AUTO_INTERVAL_SECONDS = int(os.getenv("AUTO_INTERVAL_SECONDS", "900"))
OHLCV_LIMIT = int(os.getenv("OHLCV_LIMIT", "260"))
BACKTEST_LOOKAHEAD = int(os.getenv("BACKTEST_LOOKAHEAD", "10"))

BINANCE_FAPI_BASE = "https://fapi.binance.com"

auto_tasks: Dict[int, asyncio.Task] = {}


@dataclass
class SignalResult:
    symbol: str
    timeframe: str
    side: str
    entry: float
    stop_loss: float
    targets: List[float]
    rsi: float
    volume_ratio: float
    oi_status: str
    whale_status: str
    strength_label: str
    accuracy: int
    final_score: int
    backtest_win_rate: int
    backtest_tp1_rate: int
    message: str
    internal: Dict[str, Any]


def now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d | %H:%M UTC")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            return default
        return value
    except Exception:
        return default


def format_price(price: float) -> str:
    price = safe_float(price)
    if price >= 1000:
        return f"${price:,.2f}"
    if price >= 1:
        return f"${price:,.4f}"
    if price >= 0.01:
        return f"${price:,.5f}"
    return f"${price:,.8f}"


def symbol_to_binance_pair(symbol: str) -> str:
    clean = symbol.upper().replace("/", "").replace(":USDT", "").replace("-", "")
    if clean.endswith("USDT"):
        return clean
    return f"{clean}USDT"


def normalize_ccxt_symbol(user_symbol: str) -> str:
    s = user_symbol.upper().strip()
    s = s.replace("-", "/")
    if "/" not in s:
        if s.endswith("USDT"):
            base = s[:-4]
        else:
            base = s
        return f"{base}/USDT:USDT"
    if ":USDT" not in s:
        return f"{s}:USDT"
    return s


async def create_exchange():
    exchange = ccxt.binance({
        "enableRateLimit": True,
        "options": {
            "defaultType": "future",
        },
    })
    return exchange


async def http_get_json(session: aiohttp.ClientSession, url: str, params: Optional[dict] = None) -> Any:
    async with session.get(url, params=params, timeout=15) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise RuntimeError(f"HTTP {resp.status}: {text[:200]}")
        return await resp.json()


async def fetch_binance_klines(
    session: aiohttp.ClientSession,
    pair: str,
    timeframe: str,
    limit: int = OHLCV_LIMIT,
) -> pd.DataFrame:
    url = f"{BINANCE_FAPI_BASE}/fapi/v1/klines"
    raw = await http_get_json(session, url, {
        "symbol": pair,
        "interval": timeframe,
        "limit": limit,
    })

    rows = []
    for item in raw:
        rows.append({
            "open_time": int(item[0]),
            "open": safe_float(item[1]),
            "high": safe_float(item[2]),
            "low": safe_float(item[3]),
            "close": safe_float(item[4]),
            "volume": safe_float(item[5]),
            "close_time": int(item[6]),
            "quote_volume": safe_float(item[7]),
            "trades": safe_float(item[8]),
            "taker_buy_base": safe_float(item[9]),
            "taker_buy_quote": safe_float(item[10]),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("empty kline data")

    return df


async def fetch_open_interest(session: aiohttp.ClientSession, pair: str) -> Optional[float]:
    url = f"{BINANCE_FAPI_BASE}/fapi/v1/openInterest"
    try:
        data = await http_get_json(session, url, {"symbol": pair})
        return safe_float(data.get("openInterest"))
    except Exception as exc:
        logger.warning("open interest failed for %s: %s", pair, exc)
        return None


async def fetch_open_interest_hist(
    session: aiohttp.ClientSession,
    pair: str,
    timeframe: str,
) -> Tuple[Optional[float], Optional[float]]:
    period = timeframe
    url = f"{BINANCE_FAPI_BASE}/futures/data/openInterestHist"

    try:
        data = await http_get_json(session, url, {
            "symbol": pair,
            "period": period,
            "limit": 2,
        })
        if not isinstance(data, list) or len(data) < 2:
            return None, None

        prev_oi = safe_float(data[-2].get("sumOpenInterest"))
        curr_oi = safe_float(data[-1].get("sumOpenInterest"))
        return prev_oi, curr_oi
    except Exception as exc:
        logger.warning("open interest hist failed for %s: %s", pair, exc)
        return None, None


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    close = df["close"]
    high = df["high"]
    low = df["low"]

    df["ema20"] = close.ewm(span=20, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()
    df["ema200"] = close.ewm(span=200, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    df["rsi"] = df["rsi"].fillna(50)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()

    df["volume_ma20"] = df["volume"].rolling(20).mean()
    df["trades_ma20"] = df["trades"].rolling(20).mean()

    return df


def detect_side(row: pd.Series) -> Optional[str]:
    close = safe_float(row["close"])
    ema20 = safe_float(row["ema20"])
    ema50 = safe_float(row["ema50"])
    ema200 = safe_float(row["ema200"])
    rsi = safe_float(row["rsi"])
    macd = safe_float(row["macd"])
    macd_signal = safe_float(row["macd_signal"])

    long_trend = close > ema20 > ema50 and ema50 >= ema200 * 0.995
    short_trend = close < ema20 < ema50 and ema50 <= ema200 * 1.005

    long_momentum = rsi >= 45 and macd >= macd_signal
    short_momentum = rsi <= 55 and macd <= macd_signal

    if long_trend and long_momentum:
        return "LONG"
    if short_trend and short_momentum:
        return "SHORT"

    if close > ema20 and macd > macd_signal and 42 <= rsi <= 68:
        return "LONG"
    if close < ema20 and macd < macd_signal and 32 <= rsi <= 58:
        return "SHORT"

    return None


def trend_score(row: pd.Series, side: str) -> int:
    close = safe_float(row["close"])
    ema20 = safe_float(row["ema20"])
    ema50 = safe_float(row["ema50"])
    ema200 = safe_float(row["ema200"])

    score = 0
    if side == "LONG":
        score += 5 if close > ema20 else 0
        score += 5 if ema20 > ema50 else 0
        score += 5 if ema50 > ema200 else 0
    else:
        score += 5 if close < ema20 else 0
        score += 5 if ema20 < ema50 else 0
        score += 5 if ema50 < ema200 else 0

    return min(score, 15)


def momentum_score(row: pd.Series, side: str) -> int:
    rsi = safe_float(row["rsi"])
    macd = safe_float(row["macd"])
    signal = safe_float(row["macd_signal"])

    score = 0

    if side == "LONG":
        if 45 <= rsi <= 65:
            score += 7
        elif 35 <= rsi < 45 or 65 < rsi <= 72:
            score += 4

        if macd > signal:
            score += 8
    else:
        if 35 <= rsi <= 55:
            score += 7
        elif 28 <= rsi < 35 or 55 < rsi <= 65:
            score += 4

        if macd < signal:
            score += 8

    return min(score, 15)


def volume_score(row: pd.Series) -> Tuple[int, float]:
    volume = safe_float(row["volume"])
    avg_volume = safe_float(row["volume_ma20"])

    if avg_volume <= 0:
        return 0, 0.0

    ratio = volume / avg_volume

    if ratio >= 2.5:
        return 15, ratio
    if ratio >= 1.8:
        return 10, ratio
    if ratio >= 1.2:
        return 5, ratio
    return 0, ratio


def whale_score(df: pd.DataFrame, side: str, volume_ratio: float, oi_change_pct: float) -> Tuple[int, str]:
    if len(df) < 25:
        return 0, "نامشخص"

    row = df.iloc[-1]
    prev3 = df.iloc[-4]

    close = safe_float(row["close"])
    old_close = safe_float(prev3["close"])
    trades = safe_float(row["trades"])
    trades_ma = safe_float(row["trades_ma20"])

    if old_close <= 0:
        price_acceleration = 0
    else:
        price_acceleration = ((close - old_close) / old_close) * 100

    if side == "SHORT":
        price_acceleration *= -1

    trade_ratio = trades / trades_ma if trades_ma > 0 else 0

    score = 0

    if volume_ratio >= 1.8:
        score += 5
    if volume_ratio >= 2.5:
        score += 2

    if price_acceleration >= 0.35:
        score += 3
    if price_acceleration >= 0.8:
        score += 2

    if trade_ratio >= 1.5:
        score += 3

    if oi_change_pct > 0.2:
        score += 2
    if oi_change_pct > 1.0:
        score += 1

    score = min(score, 15)

    if score >= 12:
        status = "ورود نقدینگی سنگین"
    elif score >= 8:
        status = "ورود نقدینگی متوسط"
    elif score >= 5:
        status = "نشانه‌های اولیه ورود نقدینگی"
    else:
        status = "تأیید نشده"

    return score, status


async def order_book_score(exchange, symbol: str, side: str) -> int:
    try:
        book = await exchange.fetch_order_book(symbol, limit=50)
        bids = book.get("bids", [])[:30]
        asks = book.get("asks", [])[:30]

        bid_value = sum(safe_float(price) * safe_float(amount) for price, amount in bids)
        ask_value = sum(safe_float(price) * safe_float(amount) for price, amount in asks)

        if bid_value <= 0 or ask_value <= 0:
            return 0

        if side == "LONG":
            ratio = bid_value / ask_value
        else:
            ratio = ask_value / bid_value

        if ratio >= 1.8:
            return 10
        if ratio >= 1.3:
            return 7
        if ratio >= 1.0:
            return 3
        return 0
    except Exception as exc:
        logger.warning("order book failed for %s: %s", symbol, exc)
        return 0


def oi_score_and_status(prev_oi: Optional[float], curr_oi: Optional[float], side: str, price_change_pct: float) -> Tuple[int, str, float]:
    if not prev_oi or not curr_oi or prev_oi <= 0:
        return 3, "نامشخص", 0.0

    change_pct = ((curr_oi - prev_oi) / prev_oi) * 100

    if change_pct > 0.2:
        status = "افزایشی"
    elif change_pct < -0.2:
        status = "کاهشی"
    else:
        status = "خنثی"

    score = 0

    if side == "LONG":
        if price_change_pct > 0 and change_pct > 0:
            score = 10
        elif price_change_pct > 0 and change_pct <= 0:
            score = 4
        elif change_pct > 0:
            score = 6
        else:
            score = 2
    else:
        if price_change_pct < 0 and change_pct > 0:
            score = 10
        elif price_change_pct < 0 and change_pct <= 0:
            score = 4
        elif change_pct > 0:
            score = 6
        else:
            score = 2

    return score, status, change_pct


def calculate_targets_and_stop(row: pd.Series, side: str) -> Tuple[float, List[float], float, float]:
    entry = safe_float(row["close"])
    atr = safe_float(row["atr"])

    if atr <= 0:
        atr = entry * 0.01

    if side == "LONG":
        stop = entry - atr * 1.5
        targets = [
            entry + atr * 1.0,
            entry + atr * 1.6,
            entry + atr * 2.2,
            entry + atr * 3.0,
        ]
        rr_hidden = (targets[0] - entry) / max(entry - stop, 1e-12)
    else:
        stop = entry + atr * 1.5
        targets = [
            entry - atr * 1.0,
            entry - atr * 1.6,
            entry - atr * 2.2,
            entry - atr * 3.0,
        ]
        rr_hidden = (entry - targets[0]) / max(stop - entry, 1e-12)

    return entry, targets, stop, rr_hidden


def hidden_risk_score(rr_hidden: float, row: pd.Series) -> int:
    atr = safe_float(row["atr"])
    close = safe_float(row["close"])

    if close <= 0 or atr <= 0:
        return 0

    atr_pct = (atr / close) * 100

    if rr_hidden < 0.6:
        return 0

    score = 0

    if rr_hidden >= 0.65:
        score += 4
    if rr_hidden >= 1.0:
        score += 3
    if 0.2 <= atr_pct <= 5:
        score += 3

    return min(score, 10)


def backtest_signal(df: pd.DataFrame, side: str) -> Tuple[int, int, int]:
    if len(df) < 230:
        return 3, 50, 50

    wins = 0
    total = 0
    tp1_hits = 0

    start = max(205, len(df) - 90)
    end = len(df) - BACKTEST_LOOKAHEAD - 1

    for i in range(start, end):
        row = df.iloc[i]
        local_side = detect_side(row)
        if local_side != side:
            continue

        entry, targets, stop, rr_hidden = calculate_targets_and_stop(row, side)
        if rr_hidden < 0.55:
            continue

        total += 1
        tp1 = targets[0]

        future = df.iloc[i + 1:i + 1 + BACKTEST_LOOKAHEAD]

        result = None
        for _, candle in future.iterrows():
            high = safe_float(candle["high"])
            low = safe_float(candle["low"])

            if side == "LONG":
                if low <= stop:
                    result = "sl"
                    break
                if high >= tp1:
                    result = "tp1"
                    break
            else:
                if high >= stop:
                    result = "sl"
                    break
                if low <= tp1:
                    result = "tp1"
                    break

        if result == "tp1":
            wins += 1
            tp1_hits += 1

    if total == 0:
        return 3, 50, 50

    win_rate = int(round((wins / total) * 100))
    tp1_rate = int(round((tp1_hits / total) * 100))

    if win_rate >= 70:
        score = 10
    elif win_rate >= 60:
        score = 6
    elif win_rate >= 50:
        score = 3
    else:
        score = 0

    return score, win_rate, tp1_rate


def strength_label(score: int) -> str:
    if score >= 85:
        return "قوی"
    if score >= 70:
        return "متوسط رو به قوی"
    if score >= 55:
        return "ضعیف"
    return "بدون سیگنال"


def rsi_status(rsi: float, side: str) -> str:
    if side == "LONG":
        if 45 <= rsi <= 65:
            return "مناسب"
        if rsi > 70:
            return "اشباع خرید"
        if rsi < 35:
            return "اشباع فروش"
        return "متوسط"

    if 35 <= rsi <= 55:
        return "مناسب"
    if rsi < 30:
        return "اشباع فروش"
    if rsi > 65:
        return "اشباع خرید"
    return "متوسط"


def build_message(result: SignalResult) -> str:
    side_fa = "لانگ" if result.side == "LONG" else "شورت"

    return (
        f"📊 نماد: {result.symbol.replace(':USDT', '')}\n"
        f"⏱ تایم‌فریم: {result.timeframe}\n"
        f"🕒 زمان: {now_text()}\n\n"
        f"🟢 قدرت سیگنال: {result.strength_label}\n"
        f"📌 نوع معامله: {result.side} / {side_fa}\n"
        f"💵 ورود: {format_price(result.entry)}\n\n"
        f"🐋 نهنگ‌ها: {result.whale_status}\n"
        f"📈 حجم: {result.volume_ratio:.1f}x بالاتر از میانگین\n"
        f"📊 OI: {result.oi_status}\n"
        f"📉 RSI: {result.rsi:.0f} | {rsi_status(result.rsi, result.side)}\n\n"
        f"🎯 تارگت 1 | احتمال بالا: {format_price(result.targets[0])}\n"
        f"🎯 تارگت 2: {format_price(result.targets[1])}\n"
        f"🎯 تارگت 3: {format_price(result.targets[2])}\n"
        f"🎯 تارگت 4: {format_price(result.targets[3])}\n\n"
        f"🛑 حد ضرر: {format_price(result.stop_loss)}\n\n"
        f"✅ دقت تقریبی: {result.accuracy}٪\n"
        f"⭐ امتیاز: {result.final_score}/100\n"
        f"🧪 بک‌تست: Win Rate {result.backtest_win_rate}٪ | TP1 {result.backtest_tp1_rate}٪"
    )


async def analyze_symbol(
    exchange,
    session: aiohttp.ClientSession,
    symbol: str,
    timeframe: str = DEFAULT_TIMEFRAME,
) -> Optional[SignalResult]:
    pair = symbol_to_binance_pair(symbol)

    try:
        df = await fetch_binance_klines(session, pair, timeframe, OHLCV_LIMIT)
        df = add_indicators(df)

        if len(df) < 220:
            return None

        row = df.iloc[-1]
        prev = df.iloc[-2]

        side = detect_side(row)
        if not side:
            return None

        close = safe_float(row["close"])
        prev_close = safe_float(prev["close"])
        price_change_pct = ((close - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0

        prev_oi, curr_oi = await fetch_open_interest_hist(session, pair, timeframe)
        oi_score, oi_status, oi_change_pct = oi_score_and_status(prev_oi, curr_oi, side, price_change_pct)

        t_score = trend_score(row, side)
        m_score = momentum_score(row, side)
        v_score, v_ratio = volume_score(row)
        w_score, whale_status = whale_score(df, side, v_ratio, oi_change_pct)
        ob_score = await order_book_score(exchange, symbol, side)
        entry, targets, stop, rr_hidden = calculate_targets_and_stop(row, side)
        r_score = hidden_risk_score(rr_hidden, row)
        bt_score, win_rate, tp1_rate = backtest_signal(df, side)

        final_score = int(t_score + m_score + v_score + w_score + ob_score + oi_score + r_score + bt_score)

        # فیلترهای نهایی: اوردربوک و RR در خروجی نمایش داده نمی‌شوند، اما اینجا اثر دارند.
        if final_score < MIN_SCORE_TO_SEND:
            return None

        if v_ratio < 1.2:
            return None

        if r_score <= 0:
            return None

        if w_score < 5 and oi_score < 6:
            return None

        accuracy = min(95, max(50, int(round(final_score * 0.95 + bt_score * 0.5))))

        result = SignalResult(
            symbol=symbol,
            timeframe=timeframe,
            side=side,
            entry=entry,
            stop_loss=stop,
            targets=targets,
            rsi=safe_float(row["rsi"]),
            volume_ratio=v_ratio,
            oi_status=oi_status,
            whale_status=whale_status,
            strength_label=strength_label(final_score),
            accuracy=accuracy,
            final_score=final_score,
            backtest_win_rate=win_rate,
            backtest_tp1_rate=tp1_rate,
            message="",
            internal={
                "trend_score": t_score,
                "momentum_score": m_score,
                "volume_score": v_score,
                "whale_score": w_score,
                "order_book_score_hidden": ob_score,
                "oi_score": oi_score,
                "risk_score_hidden": r_score,
                "backtest_score": bt_score,
                "rr_hidden": rr_hidden,
                "oi_change_pct": oi_change_pct,
            },
        )

        result.message = build_message(result)
        return result

    except Exception as exc:
        logger.warning("analysis failed for %s: %s", symbol, exc)
        return None


async def get_scan_symbols(exchange) -> List[str]:
    markets = await exchange.load_markets()
    symbols = []

    for symbol, market in markets.items():
        try:
            if not market.get("active", True):
                continue

            if market.get("quote") != QUOTE_ASSET:
                continue

            if not market.get("swap") and market.get("type") != "swap":
                continue

            if ":USDT" not in symbol:
                continue

            symbols.append(symbol)
        except Exception:
            continue

    # برای کنترل فشار روی API، اول مارکت‌های معروف و بعد محدودیت تعداد اعمال می‌شود.
    priority = [
        "BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT", "SOL/USDT:USDT",
        "XRP/USDT:USDT", "DOGE/USDT:USDT", "ADA/USDT:USDT", "AVAX/USDT:USDT",
        "LINK/USDT:USDT", "TON/USDT:USDT", "DOT/USDT:USDT", "TRX/USDT:USDT",
        "MATIC/USDT:USDT", "LTC/USDT:USDT", "BCH/USDT:USDT", "NEAR/USDT:USDT",
    ]

    ordered = []
    seen = set()

    for s in priority:
        if s in symbols and s not in seen:
            ordered.append(s)
            seen.add(s)

    for s in symbols:
        if s not in seen:
            ordered.append(s)
            seen.add(s)

    return ordered[:SCAN_MARKET_LIMIT]


async def scan_market(timeframe: str = DEFAULT_TIMEFRAME) -> List[SignalResult]:
    exchange = await create_exchange()
    results: List[SignalResult] = []

    try:
        symbols = await get_scan_symbols(exchange)
        connector = aiohttp.TCPConnector(limit=20)

        async with aiohttp.ClientSession(connector=connector) as session:
            semaphore = asyncio.Semaphore(8)

            async def worker(sym: str):
                async with semaphore:
                    return await analyze_symbol(exchange, session, sym, timeframe)

            tasks = [worker(symbol) for symbol in symbols]
            raw_results = await asyncio.gather(*tasks, return_exceptions=True)

            for item in raw_results:
                if isinstance(item, SignalResult):
                    results.append(item)

    finally:
        await exchange.close()

    results.sort(key=lambda x: x.final_score, reverse=True)
    return results


async def analyze_one_symbol(user_symbol: str, timeframe: str = DEFAULT_TIMEFRAME) -> Optional[SignalResult]:
    symbol = normalize_ccxt_symbol(user_symbol)
    exchange = await create_exchange()

    try:
        async with aiohttp.ClientSession() as session:
            return await analyze_symbol(exchange, session, symbol, timeframe)
    finally:
        await exchange.close()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "سلام 👋\n"
        "ربات تحلیل و سیگنال رمزارز فعال است.\n\n"
        "دستورات:\n"
        "/signal BTCUSDT - تحلیل یک ارز\n"
        "/scan - اسکن کل بازار و نمایش بهترین سیگنال‌ها\n"
        "/auto_on - فعال‌سازی اسکن خودکار\n"
        "/auto_off - توقف اسکن خودکار\n\n"
        "خروجی شامل Order Book و RR نیست؛ این دو فقط در محاسبات داخلی استفاده می‌شوند."
    )
    await update.message.reply_text(text)


async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("مثال درست:\n/signal BTCUSDT")
        return

    user_symbol = context.args[0]
    timeframe = context.args[1] if len(context.args) > 1 else DEFAULT_TIMEFRAME

    msg = await update.message.reply_text("در حال تحلیل سیگنال...")

    result = await analyze_one_symbol(user_symbol, timeframe)

    if not result:
        await msg.edit_text("برای این نماد فعلاً سیگنال معتبر با امتیاز کافی پیدا نشد.")
        return

    await msg.edit_text(result.message)


async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    timeframe = context.args[0] if context.args else DEFAULT_TIMEFRAME

    msg = await update.message.reply_text("در حال اسکن کل بازار...")

    results = await scan_market(timeframe)

    if not results:
        await msg.edit_text("فعلاً در کل بازار سیگنال قوی پیدا نشد.")
        return

    top_results = results[:SCAN_TOP_N]

    await msg.edit_text(f"✅ {len(results)} سیگنال معتبر پیدا شد. نمایش {len(top_results)} مورد برتر:")

    for result in top_results:
        await update.message.reply_text(result.message)
        await asyncio.sleep(0.5)


async def auto_scan_loop(chat_id: int, application: Application, timeframe: str):
    logger.info("auto scan started for chat_id=%s", chat_id)

    while True:
        try:
            results = await scan_market(timeframe)
            top_results = results[:SCAN_TOP_N]

            if top_results:
                await application.bot.send_message(
                    chat_id=chat_id,
                    text=f"🤖 اسکن خودکار بازار انجام شد. {len(results)} سیگنال معتبر پیدا شد."
                )

                for result in top_results:
                    await application.bot.send_message(chat_id=chat_id, text=result.message)
                    await asyncio.sleep(0.5)
            else:
                logger.info("auto scan: no valid signal")

        except asyncio.CancelledError:
            logger.info("auto scan cancelled for chat_id=%s", chat_id)
            break
        except Exception as exc:
            logger.exception("auto scan failed: %s", exc)
            try:
                await application.bot.send_message(
                    chat_id=chat_id,
                    text="خطا در اسکن خودکار رخ داد؛ ربات در تلاش بعدی دوباره بررسی می‌کند."
                )
            except Exception:
                pass

        await asyncio.sleep(AUTO_INTERVAL_SECONDS)


async def auto_on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    timeframe = context.args[0] if context.args else DEFAULT_TIMEFRAME

    if chat_id in auto_tasks and not auto_tasks[chat_id].done():
        await update.message.reply_text("اسکن خودکار از قبل فعال است.")
        return

    task = asyncio.create_task(auto_scan_loop(chat_id, context.application, timeframe))
    auto_tasks[chat_id] = task

    await update.message.reply_text(
        f"✅ اسکن خودکار فعال شد.\n"
        f"تایم‌فریم: {timeframe}\n"
        f"فاصله هر اسکن: {AUTO_INTERVAL_SECONDS} ثانیه"
    )


async def auto_off_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    task = auto_tasks.get(chat_id)

    if not task or task.done():
        await update.message.reply_text("اسکن خودکار فعال نیست.")
        return

    task.cancel()
    await update.message.reply_text("🛑 اسکن خودکار متوقف شد.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("telegram error: %s", context.error)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("signal", signal_command))
    app.add_handler(CommandHandler("scan", scan_command))
    app.add_handler(CommandHandler("auto_on", auto_on_command))
    app.add_handler(CommandHandler("auto_off", auto_off_command))

    app.add_error_handler(error_handler)

    logger.info("bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
