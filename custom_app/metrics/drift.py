"""
Drift computation — live vs backtest and live vs paper drift.

Drift measures how much the live strategy's performance deviates
from what was expected based on backtesting and paper trading.
"""

from __future__ import annotations


def compute_pnl_drift_pct(
    live_pnl: float,
    reference_pnl: float,
    tolerance_pct: float = 5.0,
) -> dict:
    """
    Compute PnL drift between live and a reference (backtest or paper).

    Parameters:
        live_pnl: Actual live PnL.
        reference_pnl: Expected PnL from reference.
        tolerance_pct: Acceptable drift % before flagging.

    Returns dict with drift_pct, within_tolerance, severity.
    """
    if reference_pnl == 0:
        return {"drift_pct": 0.0, "within_tolerance": True, "severity": "none"}

    drift_pct = ((live_pnl - reference_pnl) / abs(reference_pnl)) * 100.0
    abs_drift = abs(drift_pct)

    if abs_drift <= tolerance_pct:
        severity = "none"
    elif abs_drift <= tolerance_pct * 2:
        severity = "warning"
    else:
        severity = "critical"

    return {
        "drift_pct": round(drift_pct, 4),
        "within_tolerance": abs_drift <= tolerance_pct,
        "severity": severity,
        "live_pnl": live_pnl,
        "reference_pnl": reference_pnl,
    }
