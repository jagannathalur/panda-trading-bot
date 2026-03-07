"""
ModeGuard — enforces trading mode immutability at runtime.

Once initialized with a TradingModeConfig, the guard:
  - Holds the mode as a frozen, immutable value.
  - Raises ModeViolationError if any code attempts to mutate it.
  - Provides a safe read-only API for querying mode.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from custom_app.mode_control.config import TradingMode, TradingModeConfig

logger = logging.getLogger(__name__)


class ModeViolationError(RuntimeError):
    """Raised when code attempts to change the trading mode at runtime."""

    def __init__(self, attempted_mode: str, current_mode: TradingMode) -> None:
        super().__init__(
            f"SECURITY VIOLATION: Attempted to change trading mode to '{attempted_mode}' "
            f"but current mode is '{current_mode}' and is IMMUTABLE. "
            "Mode can only be changed by restarting the bot with operator approval."
        )
        self.attempted_mode = attempted_mode
        self.current_mode = current_mode


class ModeGuard:
    """
    Thread-safe, immutable trading mode guard. Singleton.

    Usage:
        guard = ModeGuard.initialize(config)  # once at startup
        guard.is_paper()     # safe read anywhere
        guard.current_mode   # read-only property
    """

    _instance: Optional["ModeGuard"] = None
    _class_lock: threading.Lock = threading.Lock()

    def __init__(self, config: TradingModeConfig) -> None:
        self._config = config
        self._mode = config.mode
        logger.info(
            "[ModeGuard] Initialized: mode=%s (immutable for this process lifetime)",
            self._mode,
        )

    @classmethod
    def initialize(cls, config: TradingModeConfig) -> "ModeGuard":
        """Create the singleton ModeGuard. Can only be called once per process."""
        with cls._class_lock:
            if cls._instance is not None:
                raise RuntimeError(
                    "ModeGuard.initialize() called more than once. "
                    "Mode guard is a singleton initialized at startup."
                )
            cls._instance = cls(config)
            return cls._instance

    @classmethod
    def get_instance(cls) -> "ModeGuard":
        """Get the initialized singleton. Raises if not yet initialized."""
        with cls._class_lock:
            if cls._instance is None:
                raise RuntimeError(
                    "ModeGuard not initialized. Call ModeGuard.initialize(config) at startup."
                )
            return cls._instance

    @classmethod
    def _reset_for_testing(cls) -> None:
        """Reset singleton. FOR TESTING ONLY. Never call in production."""
        with cls._class_lock:
            cls._instance = None

    @property
    def current_mode(self) -> TradingMode:
        return self._mode

    @property
    def config(self) -> TradingModeConfig:
        return self._config

    def is_paper(self) -> bool:
        return self._mode == TradingMode.PAPER

    def is_real(self) -> bool:
        return self._mode == TradingMode.REAL

    def assert_paper(self) -> None:
        if not self.is_paper():
            raise AssertionError(f"Expected paper mode but mode is '{self._mode}'")

    def assert_real(self) -> None:
        if not self.is_real():
            raise AssertionError(f"Expected real mode but mode is '{self._mode}'")

    def attempt_mode_change(self, new_mode: str, caller: str = "unknown") -> None:
        """
        Called by any component that attempts to change mode.
        ALWAYS raises ModeViolationError.
        """
        logger.critical(
            "[SECURITY] Mode change attempted by '%s': tried '%s', current='%s' is IMMUTABLE.",
            caller, new_mode, self._mode,
        )
        raise ModeViolationError(attempted_mode=new_mode, current_mode=self._mode)

    def to_display_dict(self) -> dict:
        """Read-only display dict for dashboard/API use."""
        return {
            "mode": str(self._mode),
            "is_paper": self.is_paper(),
            "is_real": self.is_real(),
            "read_only": True,
            "note": "Trading mode is read-only. Changes require operator restart.",
        }
