"""
entry_filters.py — Pure gate logic, importable without Freqtrade.

Functions here are called by GridTrendV2.confirm_trade_entry() but live
in custom_app so they can be unit-tested without the full Freqtrade stack.

All functions follow fail-open convention: return True (allow) on any error
so a missing or broken data source never blocks a trade on its own.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Orderbook imbalance thresholds (0=all asks, 1=all bids, 0.5=neutral)
OB_LONG_MIN = 0.35   # block long if imbalance < 0.35 (asks dominating)
OB_SHORT_MAX = 0.65  # block short if imbalance > 0.65 (bids dominating)


def mtf_ema_aligned(
    df_15m: Optional[pd.DataFrame],
    ema_fast_period: int,
    ema_slow_period: int,
    side: str,
) -> bool:
    """
    Multi-timeframe EMA alignment check.

    Returns True  if the 15m EMA trend aligns with the entry direction,
                  OR if 15m data is unavailable (fail-open).
    Returns False if 15m EMA opposes the entry (e.g., bearish 15m → block long).

    Args:
        df_15m: 15-minute OHLCV DataFrame (needs 'close' column).
        ema_fast_period: Fast EMA period (e.g. 9).
        ema_slow_period: Slow EMA period (e.g. 21).
        side: 'long' or 'short'.
    """
    try:
        if df_15m is None or len(df_15m) < 25:
            logger.debug("[MTFFilter] Insufficient 15m data (%s rows) — fail-open",
                         len(df_15m) if df_15m is not None else 0)
            return True

        import talib
        close_np = df_15m["close"].to_numpy(dtype=float)
        ema_fast = talib.EMA(close_np, timeperiod=ema_fast_period)
        ema_slow = talib.EMA(close_np, timeperiod=ema_slow_period)
        fast_val = float(ema_fast[-1])
        slow_val = float(ema_slow[-1])

        if side == "long" and fast_val < slow_val:
            logger.info(
                "[MTFFilter] 15m EMA bearish — blocking long (fast=%.4f < slow=%.4f)",
                fast_val, slow_val,
            )
            return False
        if side == "short" and fast_val > slow_val:
            logger.info(
                "[MTFFilter] 15m EMA bullish — blocking short (fast=%.4f > slow=%.4f)",
                fast_val, slow_val,
            )
            return False

    except Exception as exc:
        logger.debug("[MTFFilter] Error computing 15m EMAs: %s — fail-open", exc)

    return True


def orderbook_allows_entry(
    imbalance: float,
    side: str,
    long_min: float = OB_LONG_MIN,
    short_max: float = OB_SHORT_MAX,
) -> bool:
    """
    Orderbook pressure gate.

    Returns False (block) when the orderbook is heavily skewed against entry direction.
    Returns True  (allow) otherwise.

    Args:
        imbalance: bid_volume / total_volume. 0=all asks, 1=all bids, 0.5=neutral.
        side: 'long' or 'short'.
        long_min: minimum imbalance to allow a long entry.
        short_max: maximum imbalance to allow a short entry.
    """
    if side == "long" and imbalance < long_min:
        logger.info(
            "[OBFilter] Asks dominating (imbalance=%.2f < %.2f) — blocking long",
            imbalance, long_min,
        )
        return False
    if side == "short" and imbalance > short_max:
        logger.info(
            "[OBFilter] Bids dominating (imbalance=%.2f > %.2f) — blocking short",
            imbalance, short_max,
        )
        return False
    return True
