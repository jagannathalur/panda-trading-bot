"""Tests for the no-alpha gate."""

import dataclasses

import pytest
from custom_app.no_alpha import NoAlphaGate, NoAlphaBlockedError, EdgeMetrics, NoAlphaThresholds


def _thresholds(**kwargs) -> NoAlphaThresholds:
    defaults = dict(
        min_signal_strength=0.5,
        min_edge_confidence=0.6,
        min_expected_gross_edge_bps=8.0,
        min_expected_net_edge_bps=5.0,
        min_market_quality_score=0.6,
        min_model_quality_score=0.7,
    )
    defaults.update(kwargs)
    return NoAlphaThresholds(**defaults)


def _good_metrics(**overrides) -> EdgeMetrics:
    """Return a fresh EdgeMetrics that passes all default thresholds."""
    base = EdgeMetrics(
        pair="BTC/USDT",
        signal_strength=0.8,
        edge_confidence=0.75,
        expected_gross_edge_bps=12.0,
        expected_net_edge_bps=8.0,
        market_quality_score=0.8,
        model_quality_score=0.85,
    )
    return dataclasses.replace(base, **overrides)


class TestNoAlphaGate:

    def test_good_metrics_pass(self):
        gate = NoAlphaGate(_thresholds())
        gate.evaluate(_good_metrics())  # Should not raise

    def test_weak_signal_blocked(self):
        gate = NoAlphaGate(_thresholds(min_signal_strength=0.5))
        with pytest.raises(NoAlphaBlockedError, match="signal_strength"):
            gate.evaluate(_good_metrics(signal_strength=0.3))

    def test_low_net_edge_blocked(self):
        gate = NoAlphaGate(_thresholds(min_expected_net_edge_bps=5.0))
        with pytest.raises(NoAlphaBlockedError, match="expected_net_edge_bps"):
            gate.evaluate(_good_metrics(expected_net_edge_bps=2.0))

    def test_poor_market_quality_blocked(self):
        gate = NoAlphaGate(_thresholds(min_market_quality_score=0.6))
        with pytest.raises(NoAlphaBlockedError, match="market_quality_score"):
            gate.evaluate(_good_metrics(market_quality_score=0.4))

    def test_poor_model_quality_blocked(self):
        gate = NoAlphaGate(_thresholds(min_model_quality_score=0.7))
        with pytest.raises(NoAlphaBlockedError, match="model_quality_score"):
            gate.evaluate(_good_metrics(model_quality_score=0.5))

    def test_zero_edge_blocked(self):
        gate = NoAlphaGate(_thresholds())
        metrics = EdgeMetrics(pair="ETH/USDT")  # All zeros
        with pytest.raises(NoAlphaBlockedError):
            gate.evaluate(metrics)

    def test_blocked_error_contains_metrics(self):
        gate = NoAlphaGate(_thresholds())
        metrics = _good_metrics(signal_strength=0.1)
        with pytest.raises(NoAlphaBlockedError) as exc_info:
            gate.evaluate(metrics)
        assert exc_info.value.metrics is metrics

    def test_multiple_failures_reported(self):
        gate = NoAlphaGate(_thresholds())
        metrics = EdgeMetrics(pair="SOL/USDT")  # All zeros — all fail
        with pytest.raises(NoAlphaBlockedError) as exc_info:
            gate.evaluate(metrics)
        # Multiple failures should be in the reason
        assert ";" in exc_info.value.reason
