"""Promotion pipeline — strategy promotion state machine."""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from custom_app.promotion.states import (
    PromotionState,
    validate_transition,
    OPERATOR_REQUIRED_STATES,
)
from custom_app.promotion.artifacts import PromotionArtifact

logger = logging.getLogger(__name__)


class PromotionPipeline:
    """
    Manages strategy promotion state transitions.

    Rules:
    - Transitions validated against VALID_TRANSITIONS.
    - Operator-required states (small_live, full_live) require token.
    - Promotion to live states does NOT enable real trading.
      Real trading requires separate operator action via mode_control.
    - All transitions audited.
    """

    def __init__(
        self,
        strategy_id: str,
        initial_state: PromotionState = PromotionState.DRAFT,
    ) -> None:
        self.strategy_id = strategy_id
        self._state = initial_state
        self._history: list[dict] = []
        self._artifact: Optional[PromotionArtifact] = None

    @property
    def current_state(self) -> PromotionState:
        return self._state

    @property
    def artifact(self) -> Optional[PromotionArtifact]:
        return self._artifact

    def attach_artifact(self, artifact: PromotionArtifact) -> None:
        artifact.assert_passed()
        artifact.assert_fresh()
        if artifact.strategy_id != self.strategy_id:
            raise ValueError(
                f"Artifact strategy_id '{artifact.strategy_id}' != pipeline '{self.strategy_id}'"
            )
        self._artifact = artifact

    def advance(
        self,
        to_state: PromotionState,
        operator_token: Optional[str] = None,
        notes: str = "",
    ) -> None:
        """Advance to next promotion state."""
        validate_transition(self._state, to_state)

        if to_state in OPERATOR_REQUIRED_STATES:
            if not operator_token:
                raise ValueError(
                    f"Operator token required to advance to {to_state}. "
                    "This transition cannot be automated."
                )
            self._validate_operator_token(operator_token)

        if to_state not in {PromotionState.DRAFT, PromotionState.RESEARCH, PromotionState.FAILED}:
            if self._artifact is None:
                raise ValueError(
                    f"Cannot advance to {to_state} without a promotion artifact. "
                    "Run the full validation pipeline first."
                )
            self._artifact.assert_fresh()
            self._artifact.assert_passed()

        old_state = self._state
        self._state = to_state
        self._record_transition(old_state, to_state, notes)
        self._audit_transition(old_state, to_state)

        logger.info("[Promotion] %s: %s -> %s", self.strategy_id, old_state, to_state)

        if to_state in OPERATOR_REQUIRED_STATES:
            logger.warning(
                "[Promotion] Strategy %s promoted to %s. "
                "NOTE: This does NOT enable real trading. "
                "Real trading requires separate operator action via mode_control.",
                self.strategy_id, to_state,
            )

    def _validate_operator_token(self, token: str) -> None:
        import hmac
        stored_hash = os.environ.get("OPERATOR_APPROVAL_TOKEN_HASH", "")
        computed = hashlib.sha256(token.encode()).hexdigest()
        if not stored_hash or not hmac.compare_digest(computed, stored_hash):
            raise ValueError("Invalid operator token for promotion to live state.")

    def _record_transition(
        self, from_state: PromotionState, to_state: PromotionState, notes: str
    ) -> None:
        self._history.append({
            "from_state": str(from_state),
            "to_state": str(to_state),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "notes": notes,
        })

    def _audit_transition(self, from_state: PromotionState, to_state: PromotionState) -> None:
        try:
            from custom_app.audit import AuditLogger, AuditEventType
            AuditLogger.get_instance().log_event(
                event_type=AuditEventType.PROMOTION_STATE_CHANGE,
                actor="promotion_pipeline",
                action=f"Promotion: {from_state} -> {to_state}",
                before_state={"state": str(from_state)},
                after_state={"state": str(to_state)},
                details={"strategy_id": self.strategy_id},
            )
        except Exception:
            pass

    def get_status(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "current_state": str(self._state),
            "history": self._history,
            "artifact_id": self._artifact.artifact_id if self._artifact else None,
            "artifact_fresh": self._artifact.is_fresh() if self._artifact else None,
        }
