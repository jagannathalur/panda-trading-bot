"""Risk limit definitions loaded from config/environment."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RiskLimits:
    """Immutable risk limit configuration. Conservative defaults."""
    max_daily_loss_pct: float = 2.0
    max_drawdown_pct: float = 10.0
    kill_switch_drawdown_pct: float = 15.0
    max_leverage: float = 3.0
    max_open_trades: int = 5
    max_position_size_pct: float = 10.0
    max_total_exposure_pct: float = 50.0
    consecutive_loss_pause_count: int = 3
    min_trade_interval_seconds: float = 300.0
    max_rejection_rate: float = 0.3

    @classmethod
    def from_env(cls) -> "RiskLimits":
        return cls(
            max_daily_loss_pct=float(os.environ.get("MAX_DAILY_LOSS_PCT", "2.0")),
            max_drawdown_pct=float(os.environ.get("MAX_DRAWDOWN_PCT", "10.0")),
            kill_switch_drawdown_pct=float(os.environ.get("KILL_SWITCH_DRAWDOWN_PCT", "15.0")),
            max_leverage=float(os.environ.get("MAX_LEVERAGE", "3.0")),
            max_open_trades=int(os.environ.get("MAX_OPEN_TRADES", "5")),
            max_position_size_pct=float(os.environ.get("MAX_POSITION_SIZE_PCT", "10.0")),
            max_total_exposure_pct=float(os.environ.get("MAX_TOTAL_EXPOSURE_PCT", "50.0")),
            consecutive_loss_pause_count=int(os.environ.get("CONSECUTIVE_LOSS_PAUSE_COUNT", "3")),
            min_trade_interval_seconds=float(os.environ.get("MIN_TRADE_INTERVAL_SECONDS", "300.0")),
            max_rejection_rate=float(os.environ.get("MAX_REJECTION_RATE", "0.3")),
        )

    def to_dict(self) -> dict:
        return {
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "kill_switch_drawdown_pct": self.kill_switch_drawdown_pct,
            "max_leverage": self.max_leverage,
            "max_open_trades": self.max_open_trades,
            "max_position_size_pct": self.max_position_size_pct,
            "max_total_exposure_pct": self.max_total_exposure_pct,
            "consecutive_loss_pause_count": self.consecutive_loss_pause_count,
        }
