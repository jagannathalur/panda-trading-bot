"""
NoAlphaGate — gates trades when expected net edge is insufficient.

Fail-closed: if edge metrics cannot be computed, trade is blocked.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class NoAlphaBlockedError(Exception):
    """Raised when the no-alpha gate blocks a trade."""

    def __init__(self, reason: str, metrics: "EdgeMetrics") -> None:
        super().__init__(f"[NoAlpha] Trade blocked: {reason}")
        self.reason = reason
        self.metrics = metrics


@dataclass(frozen=True)
class NoAlphaThresholds:
    """Minimum thresholds for trade eligibility."""
    min_signal_strength: float = 0.5
    min_edge_confidence: float = 0.6
    min_expected_gross_edge_bps: float = 8.0
    min_expected_net_edge_bps: float = 5.0
    min_market_quality_score: float = 0.6
    min_model_quality_score: float = 0.7

    @classmethod
    def from_env(cls) -> "NoAlphaThresholds":
        return cls(
            min_signal_strength=float(os.environ.get("MIN_SIGNAL_STRENGTH", "0.5")),
            min_edge_confidence=float(os.environ.get("MIN_EDGE_CONFIDENCE", "0.6")),
            min_expected_gross_edge_bps=float(os.environ.get("MIN_EXPECTED_GROSS_EDGE_BPS", "8.0")),
            min_expected_net_edge_bps=float(os.environ.get("MIN_EXPECTED_NET_EDGE_BPS", "5.0")),
            min_market_quality_score=float(os.environ.get("MIN_MARKET_QUALITY_SCORE", "0.6")),
            min_model_quality_score=float(os.environ.get("MIN_MODEL_QUALITY_SCORE", "0.7")),
        )


@dataclass
class EdgeMetrics:
    """Computed edge metrics for a trade opportunity."""
    signal_strength: float = 0.0
    edge_confidence: float = 0.0
    expected_gross_edge_bps: float = 0.0
    expected_net_edge_bps: float = 0.0
    market_quality_score: float = 0.0
    model_quality_score: float = 0.0
    pair: str = ""

    def to_dict(self) -> dict:
        return {
            "pair": self.pair,
            "signal_strength": round(self.signal_strength, 4),
            "edge_confidence": round(self.edge_confidence, 4),
            "expected_gross_edge_bps": round(self.expected_gross_edge_bps, 2),
            "expected_net_edge_bps": round(self.expected_net_edge_bps, 2),
            "market_quality_score": round(self.market_quality_score, 4),
            "model_quality_score": round(self.model_quality_score, 4),
        }


class NoAlphaGate:
    """
    No-alpha gate. Checks all edge metrics before allowing a trade.
    Fail-closed. "Do nothing" is always the safe default.
    """

    def __init__(self, thresholds: NoAlphaThresholds | None = None) -> None:
        self._thresholds = thresholds or NoAlphaThresholds.from_env()

    def evaluate(self, metrics: EdgeMetrics) -> None:
        """
        Evaluate edge metrics. Raises NoAlphaBlockedError if thresholds not met.
        """
        failures = []

        if metrics.signal_strength < self._thresholds.min_signal_strength:
            failures.append(f"signal_strength={metrics.signal_strength:.3f} < {self._thresholds.min_signal_strength}")
        if metrics.edge_confidence < self._thresholds.min_edge_confidence:
            failures.append(f"edge_confidence={metrics.edge_confidence:.3f} < {self._thresholds.min_edge_confidence}")
        if metrics.expected_gross_edge_bps < self._thresholds.min_expected_gross_edge_bps:
            failures.append(f"expected_gross_edge_bps={metrics.expected_gross_edge_bps:.2f} < {self._thresholds.min_expected_gross_edge_bps}")
        if metrics.expected_net_edge_bps < self._thresholds.min_expected_net_edge_bps:
            failures.append(f"expected_net_edge_bps={metrics.expected_net_edge_bps:.2f} < {self._thresholds.min_expected_net_edge_bps}")
        if metrics.market_quality_score < self._thresholds.min_market_quality_score:
            failures.append(f"market_quality_score={metrics.market_quality_score:.3f} < {self._thresholds.min_market_quality_score}")
        if metrics.model_quality_score < self._thresholds.min_model_quality_score:
            failures.append(f"model_quality_score={metrics.model_quality_score:.3f} < {self._thresholds.min_model_quality_score}")

        if failures:
            reason = "; ".join(failures)
            logger.info("[NoAlpha] Blocking %s: %s", metrics.pair, reason)
            self._audit_block(metrics, reason)
            raise NoAlphaBlockedError(reason=reason, metrics=metrics)

        logger.debug("[NoAlpha] Approved %s — edge metrics pass", metrics.pair)
        self._audit_pass(metrics)

    def _audit_block(self, metrics: EdgeMetrics, reason: str) -> None:
        try:
            from custom_app.audit import AuditLogger, AuditEventType
            AuditLogger.get_instance().log_event(
                event_type=AuditEventType.NO_ALPHA_GATE_BLOCK,
                actor="no_alpha_gate",
                action="Trade blocked — insufficient edge",
                details={"metrics": metrics.to_dict(), "reason": reason},
                outcome="blocked",
            )
        except Exception:
            pass

    def _audit_pass(self, metrics: EdgeMetrics) -> None:
        try:
            from custom_app.audit import AuditLogger, AuditEventType
            AuditLogger.get_instance().log_event(
                event_type=AuditEventType.NO_ALPHA_GATE_PASS,
                actor="no_alpha_gate",
                action="Trade approved — edge metrics pass",
                details={"metrics": metrics.to_dict()},
                outcome="approved",
            )
        except Exception:
            pass

    def get_thresholds(self) -> dict:
        return {
            "min_signal_strength": self._thresholds.min_signal_strength,
            "min_edge_confidence": self._thresholds.min_edge_confidence,
            "min_expected_gross_edge_bps": self._thresholds.min_expected_gross_edge_bps,
            "min_expected_net_edge_bps": self._thresholds.min_expected_net_edge_bps,
            "min_market_quality_score": self._thresholds.min_market_quality_score,
            "min_model_quality_score": self._thresholds.min_model_quality_score,
        }
