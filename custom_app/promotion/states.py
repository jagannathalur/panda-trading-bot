"""Promotion state machine definition."""

from __future__ import annotations

from enum import StrEnum


class PromotionState(StrEnum):
    """
    Strategy promotion lifecycle states. Strictly ordered — no skipping.

    IMPORTANT: Promotion to small_live/full_live does NOT enable real trading.
    Real trading requires separate operator action via mode_control.
    """
    DRAFT = "draft"
    RESEARCH = "research"
    BACKTEST_PASSED = "backtest_passed"
    WALK_FORWARD_PASSED = "walk_forward_passed"
    PAPER_SHADOW = "paper_shadow"
    PAPER_ACTIVE = "paper_active"
    SMALL_LIVE = "small_live"
    FULL_LIVE = "full_live"
    FAILED = "failed"
    DEPRECATED = "deprecated"


VALID_TRANSITIONS: dict[PromotionState, list[PromotionState]] = {
    PromotionState.DRAFT: [PromotionState.RESEARCH, PromotionState.FAILED],
    PromotionState.RESEARCH: [PromotionState.BACKTEST_PASSED, PromotionState.FAILED, PromotionState.DRAFT],
    PromotionState.BACKTEST_PASSED: [PromotionState.WALK_FORWARD_PASSED, PromotionState.FAILED, PromotionState.RESEARCH],
    PromotionState.WALK_FORWARD_PASSED: [PromotionState.PAPER_SHADOW, PromotionState.FAILED, PromotionState.RESEARCH],
    PromotionState.PAPER_SHADOW: [PromotionState.PAPER_ACTIVE, PromotionState.FAILED, PromotionState.RESEARCH],
    PromotionState.PAPER_ACTIVE: [PromotionState.SMALL_LIVE, PromotionState.FAILED, PromotionState.RESEARCH],
    PromotionState.SMALL_LIVE: [PromotionState.FULL_LIVE, PromotionState.FAILED, PromotionState.PAPER_ACTIVE],
    PromotionState.FULL_LIVE: [PromotionState.FAILED, PromotionState.PAPER_ACTIVE, PromotionState.DEPRECATED],
    PromotionState.FAILED: [PromotionState.DRAFT],
    PromotionState.DEPRECATED: [],
}

# States that require explicit operator action — cannot be automated
OPERATOR_REQUIRED_STATES = {PromotionState.SMALL_LIVE, PromotionState.FULL_LIVE}


def validate_transition(from_state: PromotionState, to_state: PromotionState) -> None:
    """Validate a state transition. Raises ValueError if invalid."""
    allowed = VALID_TRANSITIONS.get(from_state, [])
    if to_state not in allowed:
        raise ValueError(
            f"Invalid promotion transition: {from_state} -> {to_state}. "
            f"Allowed: {[str(s) for s in allowed]}"
        )
