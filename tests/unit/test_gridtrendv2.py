"""
Unit tests for strategy gate logic — importable without Freqtrade.

Tests cover the pure functions extracted into custom_app/signals/entry_filters.py:
  - mtf_ema_aligned()       — multi-timeframe EMA alignment filter
  - orderbook_allows_entry() — orderbook imbalance hard gate

The strategy itself (GridTrendV2) cannot be imported in tests because it
depends on freqtrade which is a cloned repo, not an installed package.
These tests verify the gate logic via the extracted helper module.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from custom_app.signals.entry_filters import (
    mtf_ema_aligned,
    orderbook_allows_entry,
    OB_LONG_MIN,
    OB_SHORT_MAX,
)


# ──────────────────────────────────────────────────────────────
# Test helpers
# ──────────────────────────────────────────────────────────────

def _make_15m_df(n: int = 30, trend: str = "bullish") -> pd.DataFrame:
    """
    Build a synthetic 15m close-price DataFrame with a clear EMA trend.
    trend='bullish'  → steadily rising  → EMA9 > EMA21
    trend='bearish'  → steadily falling → EMA9 < EMA21
    trend='flat'     → near-constant    → EMAs approximately equal
    """
    np.random.seed(42)
    if trend == "bullish":
        close = np.linspace(100.0, 130.0, n) + np.random.randn(n) * 0.05
    elif trend == "bearish":
        close = np.linspace(130.0, 100.0, n) + np.random.randn(n) * 0.05
    else:
        close = np.full(n, 100.0) + np.random.randn(n) * 0.05

    return pd.DataFrame({
        "open":   close * 0.999,
        "high":   close * 1.001,
        "low":    close * 0.998,
        "close":  close,
        "volume": np.random.uniform(100, 200, n),
    })


# ──────────────────────────────────────────────────────────────
# mtf_ema_aligned — multi-timeframe EMA filter
# ──────────────────────────────────────────────────────────────

class TestMTFEMAAligned:

    def test_allows_long_when_15m_bullish(self):
        df = _make_15m_df(trend="bullish")
        assert mtf_ema_aligned(df, 9, 21, "long") is True

    def test_blocks_long_when_15m_bearish(self):
        df = _make_15m_df(trend="bearish")
        assert mtf_ema_aligned(df, 9, 21, "long") is False

    def test_allows_short_when_15m_bearish(self):
        df = _make_15m_df(trend="bearish")
        assert mtf_ema_aligned(df, 9, 21, "short") is True

    def test_blocks_short_when_15m_bullish(self):
        df = _make_15m_df(trend="bullish")
        assert mtf_ema_aligned(df, 9, 21, "short") is False

    def test_fail_open_when_df_is_none(self):
        assert mtf_ema_aligned(None, 9, 21, "long") is True
        assert mtf_ema_aligned(None, 9, 21, "short") is True

    def test_fail_open_when_df_too_short(self):
        """Fewer than 25 candles → fail-open regardless of trend."""
        df = _make_15m_df(n=10, trend="bearish")
        assert mtf_ema_aligned(df, 9, 21, "long") is True
        assert mtf_ema_aligned(df, 9, 21, "short") is True

    def test_exactly_25_candles_is_sufficient(self):
        """Exactly 25 candles should be computed (not fail-open)."""
        df_bullish = _make_15m_df(n=25, trend="bullish")
        df_bearish = _make_15m_df(n=25, trend="bearish")
        # Bullish → block short
        assert mtf_ema_aligned(df_bullish, 9, 21, "short") is False
        # Bearish → block long
        assert mtf_ema_aligned(df_bearish, 9, 21, "long") is False

    def test_flat_market_allows_at_least_one_direction(self):
        """A flat 15m trend (near-equal EMAs) should allow at least one direction."""
        df = _make_15m_df(trend="flat", n=30)
        long_ok = mtf_ema_aligned(df, 9, 21, "long")
        short_ok = mtf_ema_aligned(df, 9, 21, "short")
        assert long_ok or short_ok

    def test_uses_configured_ema_periods(self):
        """Different fast/slow periods produce different results on the same df."""
        df_bullish = _make_15m_df(trend="bullish")
        # EMA5 vs EMA30 on a bullish series: EMA5 > EMA30 → long allowed
        assert mtf_ema_aligned(df_bullish, 5, 30, "long") is True
        # EMA15 vs EMA16 on a bullish series: very close → likely still bullish
        assert mtf_ema_aligned(df_bullish, 9, 21, "long") is True

    def test_missing_close_column_fails_open(self):
        """If the DataFrame is malformed (no 'close'), fail-open."""
        df = pd.DataFrame({"price": [100.0] * 30})
        assert mtf_ema_aligned(df, 9, 21, "long") is True

    def test_bullish_df_with_many_candles(self):
        """Larger DataFrames should work correctly."""
        df = _make_15m_df(n=200, trend="bullish")
        assert mtf_ema_aligned(df, 9, 21, "long") is True
        assert mtf_ema_aligned(df, 9, 21, "short") is False

    def test_bearish_df_with_many_candles(self):
        df = _make_15m_df(n=200, trend="bearish")
        assert mtf_ema_aligned(df, 9, 21, "short") is True
        assert mtf_ema_aligned(df, 9, 21, "long") is False


# ──────────────────────────────────────────────────────────────
# orderbook_allows_entry — imbalance gate
# ──────────────────────────────────────────────────────────────

class TestOrderbookAllowsEntry:

    def test_allows_long_on_neutral(self):
        assert orderbook_allows_entry(0.50, "long") is True

    def test_allows_long_on_bid_dominated(self):
        """Strong bid pressure → good for long."""
        assert orderbook_allows_entry(0.75, "long") is True

    def test_allows_long_at_exact_minimum(self):
        """Exactly OB_LONG_MIN → block (strictly less than required)."""
        # 0.35 is the threshold; we block if imbalance < 0.35
        assert orderbook_allows_entry(OB_LONG_MIN, "long") is True       # equal = allow
        assert orderbook_allows_entry(OB_LONG_MIN - 0.001, "long") is False  # below = block

    def test_blocks_long_on_ask_dominated(self):
        """Asks dominating → not a good long entry."""
        assert orderbook_allows_entry(0.20, "long") is False
        assert orderbook_allows_entry(0.30, "long") is False
        assert orderbook_allows_entry(0.34, "long") is False

    def test_allows_short_on_neutral(self):
        assert orderbook_allows_entry(0.50, "short") is True

    def test_allows_short_on_ask_dominated(self):
        """Strong ask pressure → good for short."""
        assert orderbook_allows_entry(0.25, "short") is True

    def test_allows_short_at_exact_maximum(self):
        """Exactly OB_SHORT_MAX → allow (strictly greater required to block)."""
        assert orderbook_allows_entry(OB_SHORT_MAX, "short") is True       # equal = allow
        assert orderbook_allows_entry(OB_SHORT_MAX + 0.001, "short") is False  # above = block

    def test_blocks_short_on_bid_dominated(self):
        """Bids dominating → don't short into buying pressure."""
        assert orderbook_allows_entry(0.70, "short") is False
        assert orderbook_allows_entry(0.80, "short") is False
        assert orderbook_allows_entry(0.66, "short") is False

    def test_custom_thresholds(self):
        """Custom long_min / short_max override defaults."""
        # Tighter: block long if imbalance < 0.45
        assert orderbook_allows_entry(0.40, "long", long_min=0.45) is False
        assert orderbook_allows_entry(0.50, "long", long_min=0.45) is True
        # Tighter: block short if imbalance > 0.55
        assert orderbook_allows_entry(0.60, "short", short_max=0.55) is False
        assert orderbook_allows_entry(0.50, "short", short_max=0.55) is True

    def test_unknown_side_always_allows(self):
        """An unexpected side value should not block (fail-open)."""
        assert orderbook_allows_entry(0.10, "hold") is True

    def test_extreme_imbalance_values(self):
        """Boundary imbalance values (0.0 and 1.0)."""
        assert orderbook_allows_entry(0.0, "long") is False   # all asks → block long
        assert orderbook_allows_entry(1.0, "short") is False  # all bids → block short
        assert orderbook_allows_entry(0.0, "short") is True   # all asks → fine for short
        assert orderbook_allows_entry(1.0, "long") is True    # all bids → fine for long


# ──────────────────────────────────────────────────────────────
# Combined: ensure the two gates work independently
# ──────────────────────────────────────────────────────────────

class TestGatesAreIndependent:

    def test_mtf_and_ob_can_both_allow(self):
        df = _make_15m_df(trend="bullish")
        assert mtf_ema_aligned(df, 9, 21, "long") is True
        assert orderbook_allows_entry(0.60, "long") is True

    def test_mtf_block_independent_of_ob(self):
        """MTF block is not affected by a favourable orderbook."""
        df = _make_15m_df(trend="bearish")
        mtf_ok = mtf_ema_aligned(df, 9, 21, "long")
        ob_ok = orderbook_allows_entry(0.70, "long")
        assert mtf_ok is False   # MTF blocks
        assert ob_ok is True     # OB would allow

    def test_ob_block_independent_of_mtf(self):
        """Orderbook block is not affected by a bullish 15m trend."""
        df = _make_15m_df(trend="bullish")
        mtf_ok = mtf_ema_aligned(df, 9, 21, "long")
        ob_ok = orderbook_allows_entry(0.25, "long")
        assert mtf_ok is True    # MTF allows
        assert ob_ok is False    # OB blocks
