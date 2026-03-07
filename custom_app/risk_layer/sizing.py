"""Volatility-adjusted position sizing utilities."""

from __future__ import annotations


def volatility_adjusted_size(
    base_size_pct: float,
    current_atr: float,
    reference_atr: float,
    min_size_pct: float = 0.5,
    max_size_pct: float = 10.0,
) -> float:
    """
    Scale position size inversely with volatility.

    Higher volatility → smaller position.

    Parameters:
        base_size_pct: Base position size as % of equity.
        current_atr: Current ATR.
        reference_atr: Reference (calm-market) ATR.
        min_size_pct: Floor on position size.
        max_size_pct: Ceiling on position size.
    """
    if reference_atr <= 0 or current_atr <= 0:
        return base_size_pct
    vol_ratio = reference_atr / current_atr
    adjusted = base_size_pct * vol_ratio
    return max(min_size_pct, min(max_size_pct, adjusted))


def kelly_fraction(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    kelly_fraction_multiplier: float = 0.25,
) -> float:
    """
    Fractional Kelly criterion for position sizing.

    Uses 25% of full Kelly by default (conservative).

    Returns fraction of portfolio to risk (0.0-1.0).
    """
    if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1:
        return 0.0
    odds = avg_win / avg_loss
    kelly = (odds * win_rate - (1 - win_rate)) / odds
    return max(0.0, kelly * kelly_fraction_multiplier)
