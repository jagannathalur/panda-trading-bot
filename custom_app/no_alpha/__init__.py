"""
No-Alpha Gate — blocks trading when expected edge is too low.

"Do nothing" is a valid and preferred action when edge is weak.

Public API:
    NoAlphaGate, NoAlphaBlockedError, EdgeMetrics, NoAlphaThresholds
"""

from custom_app.no_alpha.gate import NoAlphaGate, NoAlphaBlockedError, EdgeMetrics, NoAlphaThresholds
from custom_app.no_alpha.signals import compute_signal_metrics

__all__ = ["NoAlphaGate", "NoAlphaBlockedError", "EdgeMetrics", "NoAlphaThresholds", "compute_signal_metrics"]
