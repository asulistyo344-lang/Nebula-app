"""
NEBULA - signal_engine.py - FIXED v2
Fixes BUG-001 (Crypto.com API 400 errors)
- instrument_name: BTC_USDT (underscore + USDT)
- timeframe: 15m, 1h, 4h, 1D
- candle fields come as strings, parsed to float
- detailed logging for any future failures
- one bad pair does not kill the batch
"""
import httpx
import asyncio
import logging
from typing import Optional
from dataclasses import dataclass
from config import settings

logger = logging.getLogger(__name__)

WATCHLIST = [
    "BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT",
    "ADA_USDT", "LINK_USDT", "AVAX_USDT", "SUI_USDT", "NEAR_USDT",
]
FREE_PAIRS = {"BTC_USDT"}

TF_MAP = {
    "15M": {"entry": "15m", "higher": "1h", "label": "15M"},
    "1H":  {"entry": "1h",  "higher": "4h", "label": "1H"},
    "4H":  {"entry": "4h",  "higher": "1D", "label": "4H"},
}

CRYPTO_PAIR_MAP = {
    "BTC/USD":  "BTC_USDT",
    "ETH/USD":  "ETH_USDT",
    "SOL/USD":  "SOL_USDT",
    "XRP/USD":  "XRP_USDT",
    "ADA/USD":  "ADA_USDT",
    "LINK/USD": "LINK_USDT",
    "AVAX/USD": "AVAX_USDT",
    "SUI/USD":  "SUI_USDT",
    "NEAR/USD": "NEAR_USDT",
}

@dataclass
class Candle:
    o: float; h: float; l: float; c: float; v: float; t: int

@dataclass
class SignalResult:
    pair: str
    direction: str
    entry: Optional[float]
    tp1: Optional[float]
    tp2: Optional[float]
    sl: Optional[float]
    rr: Optional[str]
    strength: int
    timeframe: str
    regime: str
    trend_bull: bool
    entry_bull: bool
    atr_value: Optional[float]
    has_signal: bool


def ema(values, period):
    k = 2 / (period + 1)
    result, prev = [], None
    for v in values:
        prev = v if prev is None else v * k + prev * (1 - k)
        result.append(prev)
    return result


def calc_atr(candles, period=14):
    trs = []
    for i, c in enumerate(candles):
        if i == 0:
            trs.append(c.h - c.l)
        else:
            pc = candles[i-1].c
            trs.append(max(c.h - c.l, abs(c.h - pc), abs(c.l - pc)))
    w = trs[-period:]
    return sum(w) / len(w) if w else 0.0


async def fetch_candles(instrument: str, timeframe: str, count: int = 100) -> list[Candle]:
    """
    Fetch candles from Crypto.com v1 public API.

    Args:
        instrument: BTC_USDT (with underscore + USDT suffix)
        timeframe: 15m | 1h | 4h | 1D
        count: max 300
    """
    url = f"{settings.CRYPTO_API_BASE}/get-candlestick"
    params = {
        "instrument_name": instrument,
        "timeframe": timeframe,
        "count": min(count, 300),
    }
    logger.debug(f"[Crypto.com] GET {url} params={params}")

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(url, params=params)
        except httpx.RequestError as e:
            logger.error(f"[Crypto.com] Network error {instrument} {timeframe}: {e}")
            raise

        if resp.status_code != 200:
            body = resp.text[:500]
            logger.error(f"[Crypto.com] HTTP {resp.status_code} {instrument} {timeframe}: {body}")
            resp.raise_for_status()

        data = resp.json()

    if data.get("code", 0) != 0:
        msg = data.get("message", "unknown")
        logger.error(f"[Crypto.com] API error {instrument}: code={data.get('code')} msg={msg}")
        raise ValueError(f"Crypto.com API error: {msg}")

    raw = data.get("result", {}).get("data", [])
    if not raw:
        logger.warning(f"[Crypto.com] Empty data for {instrument} {timeframe}")
        return []

    candles = []
    for item in raw:
        try:
            candles.append(Candle(
                o=float(item["o"]),
                h=float(item["h"]),
                l=float(item["l"]),
                c=float(item["c"]),
                v=float(item.get("v", 0)),
                t=int(item["t"]),
            ))
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"[Crypto.com] Skipping malformed candle: {e}")
            continue

    return sorted(candles, key=lambda x: x.t)


def compute_signal(pair, higher_candles, entry_candles, tf_label="15M"):
    def no_sig(regime="UNKNOWN", tb=False, eb=False):
        return SignalResult(pair, "NO_SIGNAL", None, None, None, None,
                            None, 0, tf_label, regime, tb, eb, None, False)

    if len(higher_candles) < 55 or len(entry_candles) < 25:
        return no_sig()

    h_closes = [c.c for c in higher_candles]
    h20 = ema(h_closes, 20); h50 = ema(h_closes, 50)
    regime = "BULL" if h_closes[-1] > h50[-1] else "BEAR"
    trend_bull = h20[-1] > h50[-1]

    e_closes = [c.c for c in entry_candles]
    e9 = ema(e_closes, 9); e21 = ema(e_closes, 21)
    entry_bull = e9[-1] > e21[-1]

    atr = calc_atr(entry_candles)
    price = e_closes[-1]
    if price > 0 and (atr / price) < 0.003:
        return no_sig(regime, trend_bull, entry_bull)

    long_ok = regime == "BULL" and trend_bull and entry_bull
    short_ok = regime == "BEAR" and not trend_bull and not entry_bull
    if not (long_ok or short_ok):
        return no_sig(regime, trend_bull, entry_bull)

    direction = "LONG" if long_ok else "SHORT"
    m = 1 if long_ok else -1
    entry = price
    sl = price - m * atr * 1.5
    tp1 = price + m * atr * 2.0
    tp2 = price + m * atr * 3.5
    risk = abs(entry - sl)
    rr = round(abs(tp1 - entry) / risk, 1) if risk > 0 else 0
    if rr < 1.2:
        return no_sig(regime, trend_bull, entry_bull)

    strength = 3
    if abs(e9[-1] - e21[-1]) / price > 0.001: strength += 1
    if (atr / price) > 0.006: strength += 1

    return SignalResult(
        pair=pair, direction=direction,
        entry=round(entry, 6), tp1=round(tp1, 6),
        tp2=round(tp2, 6), sl=round(sl, 6),
        rr=f"1:{rr}", strength=min(5, strength),
        timeframe=tf_label, regime=regime,
        trend_bull=trend_bull, entry_bull=entry_bull,
        atr_value=round(atr, 8), has_signal=True,
    )


async def analyze_pair(pair_symbol: str, tf_key: str = "15M") -> SignalResult:
    tf = TF_MAP.get(tf_key, TF_MAP["15M"])
    try:
        higher, entry = await asyncio.gather(
            fetch_candles(pair_symbol, tf["higher"], count=100),
            fetch_candles(pair_symbol, tf["entry"],  count=100),
        )
    except Exception as e:
        logger.error(f"[analyze_pair] {pair_symbol} {tf_key} failed: {e}")
        return SignalResult(
            pair=pair_symbol, direction="NO_SIGNAL",
            entry=None, tp1=None, tp2=None, sl=None,
            rr=None, strength=0, timeframe=tf["label"],
            regime="UNAVAILABLE", trend_bull=False,
            entry_bull=False, atr_value=None, has_signal=False,
        )
    return compute_signal(pair_symbol, higher, entry, tf["label"])


async def run_auto_scan() -> list[SignalResult]:
    tasks = [analyze_pair(p, "15M") for p in WATCHLIST]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    signals = []
    for r in results:
        if isinstance(r, SignalResult):
            signals.append(r)
        else:
            logger.error(f"[run_auto_scan] Exception: {r}")
    return signals
