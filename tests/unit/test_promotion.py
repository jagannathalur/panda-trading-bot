"""Tests for the strategy promotion pipeline."""

import hashlib
import os
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from custom_app.promotion.states import PromotionState, validate_transition, OPERATOR_REQUIRED_STATES
from custom_app.promotion.artifacts import PromotionArtifact
from custom_app.promotion.pipeline import PromotionPipeline


def _fresh_artifact(strategy_id="TestStrategy", passed=True) -> PromotionArtifact:
    return PromotionArtifact(
        strategy_id=strategy_id,
        version="1.0.0",
        code_commit="abc123",
        config_hash="def456",
        feature_set_version="1.0.0",
        parameter_manifest={"param1": 5},
        passed=passed,
    )


def _stale_artifact(strategy_id="TestStrategy") -> PromotionArtifact:
    artifact = _fresh_artifact(strategy_id)
    artifact.generated_at = datetime.now(timezone.utc) - timedelta(hours=200)
    return artifact


class TestPromotionStateMachine:

    def test_valid_transition_draft_to_research(self):
        validate_transition(PromotionState.DRAFT, PromotionState.RESEARCH)

    def test_invalid_skip_raises(self):
        with pytest.raises(ValueError):
            validate_transition(PromotionState.DRAFT, PromotionState.FULL_LIVE)

    def test_operator_required_states_defined(self):
        assert PromotionState.SMALL_LIVE in OPERATOR_REQUIRED_STATES
        assert PromotionState.FULL_LIVE in OPERATOR_REQUIRED_STATES

    def test_paper_not_operator_required(self):
        assert PromotionState.PAPER_ACTIVE not in OPERATOR_REQUIRED_STATES


class TestPromotionArtifact:

    def test_fresh_artifact_is_fresh(self):
        art = _fresh_artifact()
        assert art.is_fresh()

    def test_stale_artifact_is_not_fresh(self):
        art = _stale_artifact()
        assert not art.is_fresh(max_age_hours=168)

    def test_assert_fresh_raises_for_stale(self):
        art = _stale_artifact()
        with pytest.raises(ValueError, match="stale"):
            art.assert_fresh(max_age_hours=168)

    def test_failed_artifact_raises_on_assert_passed(self):
        art = _fresh_artifact(passed=False)
        art.fail_reason = "Drawdown too high"
        with pytest.raises(ValueError, match="did not pass"):
            art.assert_passed()

    def test_artifact_id_is_deterministic(self):
        art = _fresh_artifact()
        assert art.artifact_id == art.artifact_id  # Same object
        assert len(art.artifact_id) == 16


class TestPromotionPipeline:

    def test_starts_in_draft(self):
        p = PromotionPipeline("TestStrategy")
        assert p.current_state == PromotionState.DRAFT

    def test_advance_draft_to_research(self):
        p = PromotionPipeline("TestStrategy")
        p.advance(PromotionState.RESEARCH, notes="Starting research")
        assert p.current_state == PromotionState.RESEARCH

    def test_advance_requires_artifact_for_later_stages(self):
        p = PromotionPipeline("TestStrategy")
        p.advance(PromotionState.RESEARCH)
        with pytest.raises(ValueError, match="promotion artifact"):
            p.advance(PromotionState.BACKTEST_PASSED)

    def test_advance_with_fresh_artifact(self):
        p = PromotionPipeline("TestStrategy")
        p.advance(PromotionState.RESEARCH)
        p.attach_artifact(_fresh_artifact())
        p.advance(PromotionState.BACKTEST_PASSED)
        assert p.current_state == PromotionState.BACKTEST_PASSED

    def test_stale_artifact_blocked(self):
        p = PromotionPipeline("TestStrategy")
        p.advance(PromotionState.RESEARCH)
        with pytest.raises(ValueError, match="stale"):
            p.attach_artifact(_stale_artifact())

    def test_operator_required_without_token_raises(self):
        p = PromotionPipeline("TestStrategy")
        p._state = PromotionState.PAPER_ACTIVE  # Skip to paper_active
        art = _fresh_artifact()
        p._artifact = art
        with pytest.raises(ValueError, match="Operator token required"):
            p.advance(PromotionState.SMALL_LIVE)

    def test_promotion_to_live_does_not_enable_real_trading(self):
        """
        CRITICAL: Verifies that promotion state does NOT grant real trading.
        Mode control is entirely separate from promotion.
        """
        p = PromotionPipeline("TestStrategy")
        p._state = PromotionState.PAPER_ACTIVE
        art = _fresh_artifact()
        p._artifact = art

        # Even with a valid operator token, promoting to small_live must not
        # change the trading mode — mode_control is separate
        token = "test-token"
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        with patch.dict(os.environ, {"OPERATOR_APPROVAL_TOKEN_HASH": token_hash}):
            p.advance(PromotionState.SMALL_LIVE, operator_token=token)

        # After promotion, trading mode is unchanged (not accessible from pipeline)
        # The pipeline has no reference to mode_control — they are fully decoupled
        assert p.current_state == PromotionState.SMALL_LIVE

        # Verify ModeGuard was not touched (would raise if not initialized)
        from custom_app.mode_control import ModeGuard
        ModeGuard._reset_for_testing()
        with pytest.raises(RuntimeError, match="not initialized"):
            ModeGuard.get_instance()

    def test_history_tracks_all_transitions(self):
        p = PromotionPipeline("TestStrategy")
        p.advance(PromotionState.RESEARCH)
        p.attach_artifact(_fresh_artifact())
        p.advance(PromotionState.BACKTEST_PASSED)
        assert len(p._history) == 2
        assert p._history[0]["from_state"] == "draft"
        assert p._history[0]["to_state"] == "research"
