"""
Signal and edge metric computation utilities.

Replace the placeholder computations with your strategy's real signal logic.
"""

from __future__ import annotations

import math

from custom_app.no_alpha.gate import EdgeMetrics


def compute_signal_metrics(
    pair: str,
    raw_signal: float,               # Strategy signal score, -1.0 to 1.0
    expected_fees_bps: float,        # Round-trip fees in bps
    expected_slippage_bps: float,    # Expected slippage in bps
    market_spread_bps: float,        # Current bid-ask spread in bps
    model_out_of_sample_score: float,  # Model OOS performance 0-1
    market_regime_score: float,      # Market regime quality 0-1
) -> EdgeMetrics:
    """
    Compute edge metrics from raw signal and market microstructure data.

    In production, expected_gross_edge_bps should come from your strategy's
    calibrated expected return model, not a simple linear scaling.
    """
    signal_strength = abs(raw_signal)
    edge_confidence = _sigmoid(signal_strength * 2.0) * model_out_of_sample_score
    expected_gross_edge_bps = signal_strength * 20.0  # 20bps max gross (calibrate per strategy)
    total_costs_bps = expected_fees_bps + expected_slippage_bps + (market_spread_bps * 0.5)
    expected_net_edge_bps = expected_gross_edge_bps - total_costs_bps
    spread_penalty = max(0.0, 1.0 - (market_spread_bps / 50.0))
    market_quality_score = market_regime_score * spread_penalty

    return EdgeMetrics(
        pair=pair,
        signal_strength=signal_strength,
        edge_confidence=edge_confidence,
        expected_gross_edge_bps=expected_gross_edge_bps,
        expected_net_edge_bps=expected_net_edge_bps,
        market_quality_score=market_quality_score,
        model_quality_score=model_out_of_sample_score,
    )


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))
