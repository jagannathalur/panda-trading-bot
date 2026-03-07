"""Audit event types and the AuditEvent dataclass."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Optional


class AuditEventType(StrEnum):
    """All auditable event types in the platform."""
    # Startup
    STARTUP_MODE_SET = "startup.mode_set"
    # Mode control
    MODE_CHANGE_ATTEMPTED = "mode_control.change_attempted"
    MODE_CHANGE_REJECTED = "mode_control.change_rejected"
    # Promotion
    PROMOTION_STATE_CHANGE = "promotion.state_change"
    PROMOTION_ARTIFACT_GENERATED = "promotion.artifact_generated"
    PROMOTION_ARTIFACT_REJECTED = "promotion.artifact_rejected"
    PROMOTION_LIVE_ENABLED = "promotion.live_enabled"
    # Risk engine
    RISK_VETO = "risk.veto"
    RISK_LIMIT_BREACH = "risk.limit_breach"
    KILL_SWITCH_ARMED = "risk.kill_switch_armed"
    KILL_SWITCH_TRIGGERED = "risk.kill_switch_triggered"
    EMERGENCY_FLATTEN = "risk.emergency_flatten"
    DAILY_LOSS_CAP_HIT = "risk.daily_loss_cap_hit"
    DRAWDOWN_CAP_HIT = "risk.drawdown_cap_hit"
    CONSECUTIVE_LOSS_PAUSE = "risk.consecutive_loss_pause"
    # No-alpha gate
    NO_ALPHA_GATE_BLOCK = "no_alpha.gate_block"
    NO_ALPHA_GATE_PASS = "no_alpha.gate_pass"
    # Validation
    BACKTEST_STARTED = "validation.backtest_started"
    BACKTEST_COMPLETED = "validation.backtest_completed"
    WALK_FORWARD_STARTED = "validation.walk_forward_started"
    WALK_FORWARD_COMPLETED = "validation.walk_forward_completed"
    SHADOW_STARTED = "validation.shadow_started"
    SHADOW_COMPLETED = "validation.shadow_completed"
    # Config
    CONFIG_HASH_CHANGE = "config.hash_change"
    CONFIG_APPLIED = "config.applied"
    # Orders
    ORDER_SUBMITTED = "order.submitted"
    ORDER_FILLED = "order.filled"
    ORDER_REJECTED = "order.rejected"
    ORDER_CANCELLED = "order.cancelled"


@dataclass
class AuditEvent:
    """An immutable audit log entry."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: AuditEventType = field(default=AuditEventType.STARTUP_MODE_SET)
    actor: str = "system"
    action: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    before_state: Optional[dict] = None
    after_state: Optional[dict] = None
    outcome: str = "recorded"

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "event_type": str(self.event_type),
            "actor": self.actor,
            "action": self.action,
            "details": self.details,
            "before_state": self.before_state,
            "after_state": self.after_state,
            "outcome": self.outcome,
        }
