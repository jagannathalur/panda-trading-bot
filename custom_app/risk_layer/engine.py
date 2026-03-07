"""
RiskEngine — central veto-power risk gating mechanism.

All trade intents must pass through the risk engine before reaching
Freqtrade's execution path.

Design:
- Fail closed: any check failure or exception = veto.
- Veto is final within a trade lifecycle.
- All vetoes are audited.
- Kill switch halts ALL new trades.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from custom_app.risk_layer.limits import RiskLimits

logger = logging.getLogger(__name__)


class RiskVetoError(Exception):
    """Raised when the risk engine vetoes a trade intent."""

    def __init__(self, reason: str, check_name: str) -> None:
        super().__init__(f"[RiskVeto:{check_name}] {reason}")
        self.reason = reason
        self.check_name = check_name


@dataclass
class TradeIntent:
    """Represents an intent to open a trade."""
    pair: str
    side: str                    # "buy" | "sell"
    amount_quote: float          # Quote currency amount
    leverage: float = 1.0
    strategy_id: str = "unknown"
    signal_strength: float = 0.0


@dataclass
class RiskState:
    """Current snapshot of portfolio risk metrics."""
    total_equity: float = 0.0
    daily_loss_pct: float = 0.0
    current_drawdown_pct: float = 0.0
    open_trade_count: int = 0
    total_exposure_pct: float = 0.0
    consecutive_losses: int = 0
    kill_switch_active: bool = False
    daily_date: date = field(default_factory=date.today)

    def reset_daily_if_needed(self) -> None:
        today = date.today()
        if self.daily_date != today:
            self.daily_loss_pct = 0.0
            self.daily_date = today


class RiskEngine:
    """
    Veto-power risk engine. Singleton. Thread-safe. Fail-closed.
    """

    _instance: Optional["RiskEngine"] = None
    _class_lock: threading.Lock = threading.Lock()

    def __init__(self, limits: Optional[RiskLimits] = None) -> None:
        self._limits = limits or RiskLimits.from_env()
        self._state = RiskState()
        self._state_lock = threading.Lock()
        self._kill_switch_active = False
        logger.info("[RiskEngine] Initialized with limits: %s", self._limits.to_dict())

    @classmethod
    def initialize(cls, limits: Optional[RiskLimits] = None) -> "RiskEngine":
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = cls(limits)
            return cls._instance

    @classmethod
    def get_instance(cls) -> "RiskEngine":
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def _reset_for_testing(cls) -> None:
        with cls._class_lock:
            cls._instance = None

    def update_state(self, **kwargs) -> None:
        """Update risk state metrics. Thread-safe."""
        with self._state_lock:
            for key, value in kwargs.items():
                if hasattr(self._state, key):
                    setattr(self._state, key, value)
            self._state.reset_daily_if_needed()

    def arm_kill_switch(self, reason: str) -> None:
        """Arm the kill switch. Halts all new trades immediately."""
        with self._state_lock:
            self._kill_switch_active = True
            self._state.kill_switch_active = True
        logger.critical("[RiskEngine] KILL SWITCH ARMED: %s", reason)
        try:
            from custom_app.audit import AuditLogger, AuditEventType
            AuditLogger.get_instance().log_event(
                event_type=AuditEventType.KILL_SWITCH_ARMED,
                actor="risk_engine",
                action="Kill switch armed",
                details={"reason": reason},
            )
        except Exception:
            pass

    def is_kill_switch_active(self) -> bool:
        return self._kill_switch_active

    def evaluate(self, intent: TradeIntent) -> None:
        """
        Evaluate a trade intent against all risk checks.
        Raises RiskVetoError if any check fails.
        Fail-closed: unhandled exceptions also result in veto.
        """
        try:
            with self._state_lock:
                snap = RiskState(
                    total_equity=self._state.total_equity,
                    daily_loss_pct=self._state.daily_loss_pct,
                    current_drawdown_pct=self._state.current_drawdown_pct,
                    open_trade_count=self._state.open_trade_count,
                    total_exposure_pct=self._state.total_exposure_pct,
                    consecutive_losses=self._state.consecutive_losses,
                    kill_switch_active=self._kill_switch_active,
                )
            self._check_kill_switch(snap)
            self._check_daily_loss(snap)
            self._check_drawdown(snap)
            self._check_open_trades(snap)
            self._check_position_size(intent, snap)
            self._check_total_exposure(intent, snap)
            self._check_leverage(intent)
            self._check_consecutive_losses(snap)
        except RiskVetoError:
            self._audit_veto(intent)
            raise
        except Exception as exc:
            logger.error("[RiskEngine] Unexpected error in risk check: %s", exc)
            self._audit_veto(intent, reason=f"Unexpected error: {exc}")
            raise RiskVetoError(
                reason=f"Risk engine encountered unexpected error: {exc}",
                check_name="unexpected_error",
            )

    def _check_kill_switch(self, state: RiskState) -> None:
        if state.kill_switch_active:
            raise RiskVetoError("Kill switch is active. All new trades halted.", "kill_switch")

    def _check_daily_loss(self, state: RiskState) -> None:
        if state.daily_loss_pct >= self._limits.max_daily_loss_pct:
            raise RiskVetoError(
                f"Daily loss cap: {state.daily_loss_pct:.2f}% >= {self._limits.max_daily_loss_pct:.2f}%",
                "daily_loss_cap",
            )

    def _check_drawdown(self, state: RiskState) -> None:
        if state.current_drawdown_pct >= self._limits.kill_switch_drawdown_pct:
            self.arm_kill_switch(
                f"Drawdown {state.current_drawdown_pct:.2f}% >= kill threshold {self._limits.kill_switch_drawdown_pct:.2f}%"
            )
            raise RiskVetoError(
                f"Drawdown kill switch: {state.current_drawdown_pct:.2f}%", "drawdown_kill_switch"
            )
        if state.current_drawdown_pct >= self._limits.max_drawdown_pct:
            raise RiskVetoError(
                f"Drawdown cap: {state.current_drawdown_pct:.2f}% >= {self._limits.max_drawdown_pct:.2f}%",
                "drawdown_cap",
            )

    def _check_open_trades(self, state: RiskState) -> None:
        if state.open_trade_count >= self._limits.max_open_trades:
            raise RiskVetoError(
                f"Open trade cap: {state.open_trade_count} >= {self._limits.max_open_trades}",
                "open_trade_cap",
            )

    def _check_position_size(self, intent: TradeIntent, state: RiskState) -> None:
        import math
        if math.isnan(intent.amount_quote) or math.isinf(intent.amount_quote):
            raise RiskVetoError(
                reason=f"Invalid amount_quote: {intent.amount_quote}",
                check_name="invalid_amount",
            )
        if intent.amount_quote < 0:
            raise RiskVetoError(
                reason=f"Negative amount_quote: {intent.amount_quote}",
                check_name="negative_amount",
            )
        if state.total_equity <= 0:
            return
        pct = (intent.amount_quote / state.total_equity) * 100.0
        if pct > self._limits.max_position_size_pct:
            raise RiskVetoError(
                f"Position size {pct:.2f}% > max {self._limits.max_position_size_pct:.2f}%",
                "position_size_cap",
            )

    def _check_total_exposure(self, intent: TradeIntent, state: RiskState) -> None:
        if state.total_equity <= 0:
            return
        new_exp = state.total_exposure_pct + (intent.amount_quote / state.total_equity) * 100.0
        if new_exp > self._limits.max_total_exposure_pct:
            raise RiskVetoError(
                f"Total exposure {new_exp:.2f}% > max {self._limits.max_total_exposure_pct:.2f}%",
                "total_exposure_cap",
            )

    def _check_leverage(self, intent: TradeIntent) -> None:
        if intent.leverage > self._limits.max_leverage:
            raise RiskVetoError(
                f"Leverage {intent.leverage:.1f}x > max {self._limits.max_leverage:.1f}x",
                "leverage_cap",
            )

    def _check_consecutive_losses(self, state: RiskState) -> None:
        if state.consecutive_losses >= self._limits.consecutive_loss_pause_count:
            raise RiskVetoError(
                f"Consecutive loss pause: {state.consecutive_losses} >= {self._limits.consecutive_loss_pause_count}",
                "consecutive_loss_pause",
            )

    def _audit_veto(self, intent: TradeIntent, reason: str = "") -> None:
        try:
            from custom_app.audit import AuditLogger, AuditEventType
            AuditLogger.get_instance().log_event(
                event_type=AuditEventType.RISK_VETO,
                actor="risk_engine",
                action="Trade intent vetoed",
                details={"pair": intent.pair, "side": intent.side, "reason": reason},
                outcome="vetoed",
            )
        except Exception:
            pass

    def get_status(self) -> dict:
        with self._state_lock:
            return {
                "kill_switch_active": self._kill_switch_active,
                "daily_loss_pct": self._state.daily_loss_pct,
                "current_drawdown_pct": self._state.current_drawdown_pct,
                "open_trade_count": self._state.open_trade_count,
                "total_exposure_pct": self._state.total_exposure_pct,
                "consecutive_losses": self._state.consecutive_losses,
                "limits": self._limits.to_dict(),
            }
