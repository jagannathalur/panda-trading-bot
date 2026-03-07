"""
Mode Control — Operator-Only Trading Mode Lock.

The trading mode (paper vs real) is decided ONCE at startup from
environment variables and config. It cannot be changed at runtime
by any internal component.

Public API:
    ModeGuard
    validate_startup_mode()
    TradingModeConfig
    TradingMode
"""

from custom_app.mode_control.guard import ModeGuard
from custom_app.mode_control.startup import validate_startup_mode
from custom_app.mode_control.config import TradingModeConfig, TradingMode

__all__ = ["ModeGuard", "validate_startup_mode", "TradingModeConfig", "TradingMode"]
