"""
Tests for mode_control — proves trading mode immutability.

CRITICAL TESTS: These verify that:
1. Mode is set ONCE at startup and cannot be changed.
2. Any attempt to change mode raises ModeViolationError.
3. Real trading requires ALL operator gates.
4. Paper is the default safe mode.
5. Config inconsistencies are caught at creation time.
"""

import os
import pytest
from unittest.mock import patch

from custom_app.mode_control.config import (
    TradingMode,
    TradingModeConfig,
    resolve_trading_mode_from_env,
    check_real_trading_acknowledged,
    validate_operator_token,
)
from custom_app.mode_control.guard import ModeGuard, ModeViolationError


@pytest.fixture(autouse=True)
def reset_mode_guard():
    """Reset ModeGuard singleton before each test."""
    ModeGuard._reset_for_testing()
    yield
    ModeGuard._reset_for_testing()


def _paper_config() -> TradingModeConfig:
    return TradingModeConfig(
        mode=TradingMode.PAPER,
        real_trading_acknowledged=False,
        operator_token_valid=False,
        dry_run=True,
    )


def _real_config() -> TradingModeConfig:
    return TradingModeConfig(
        mode=TradingMode.REAL,
        real_trading_acknowledged=True,
        operator_token_valid=True,
        dry_run=False,
    )


# ─────────────────────────────────────────────────────────────
# TradingModeConfig validation
# ─────────────────────────────────────────────────────────────

class TestTradingModeConfig:
    def test_paper_mode_valid(self):
        cfg = _paper_config()
        assert cfg.is_paper
        assert not cfg.is_real

    def test_real_mode_valid_with_all_gates(self):
        cfg = _real_config()
        assert cfg.is_real
        assert not cfg.is_paper

    def test_paper_with_dry_run_false_raises(self):
        with pytest.raises(ValueError, match="mode=paper but dry_run=False"):
            TradingModeConfig(mode=TradingMode.PAPER, real_trading_acknowledged=False,
                              operator_token_valid=False, dry_run=False)

    def test_real_with_dry_run_true_raises(self):
        with pytest.raises(ValueError, match="mode=real but dry_run=True"):
            TradingModeConfig(mode=TradingMode.REAL, real_trading_acknowledged=True,
                              operator_token_valid=True, dry_run=True)

    def test_real_without_acknowledgement_raises(self):
        with pytest.raises(ValueError, match="REAL_TRADING_ACKNOWLEDGED"):
            TradingModeConfig(mode=TradingMode.REAL, real_trading_acknowledged=False,
                              operator_token_valid=True, dry_run=False)

    def test_real_without_token_raises(self):
        with pytest.raises(ValueError, match="OPERATOR_APPROVAL_TOKEN"):
            TradingModeConfig(mode=TradingMode.REAL, real_trading_acknowledged=True,
                              operator_token_valid=False, dry_run=False)

    def test_config_is_frozen(self):
        cfg = _paper_config()
        with pytest.raises((AttributeError, TypeError)):
            cfg.mode = TradingMode.REAL  # type: ignore


# ─────────────────────────────────────────────────────────────
# ModeGuard immutability — CRITICAL
# ─────────────────────────────────────────────────────────────

class TestModeGuardImmutability:

    def test_initializes_paper(self):
        guard = ModeGuard.initialize(_paper_config())
        assert guard.is_paper()
        assert not guard.is_real()
        assert guard.current_mode == TradingMode.PAPER

    def test_initializes_real(self):
        guard = ModeGuard.initialize(_real_config())
        assert guard.is_real()
        assert not guard.is_paper()

    def test_attempt_change_raises_violation(self):
        guard = ModeGuard.initialize(_paper_config())
        with pytest.raises(ModeViolationError):
            guard.attempt_mode_change("real", caller="test")

    def test_violation_error_message_says_immutable(self):
        guard = ModeGuard.initialize(_paper_config())
        with pytest.raises(ModeViolationError) as exc_info:
            guard.attempt_mode_change("real", caller="dashboard")
        assert "SECURITY VIOLATION" in str(exc_info.value)
        assert "IMMUTABLE" in str(exc_info.value)

    def test_singleton_cannot_initialize_twice(self):
        ModeGuard.initialize(_paper_config())
        with pytest.raises(RuntimeError, match="called more than once"):
            ModeGuard.initialize(_paper_config())

    def test_get_instance_before_init_raises(self):
        with pytest.raises(RuntimeError, match="not initialized"):
            ModeGuard.get_instance()

    def test_get_instance_returns_same_object(self):
        g1 = ModeGuard.initialize(_paper_config())
        g2 = ModeGuard.get_instance()
        assert g1 is g2

    def test_display_dict_is_read_only(self):
        guard = ModeGuard.initialize(_paper_config())
        d = guard.to_display_dict()
        assert d["read_only"] is True
        assert d["mode"] == "paper"

    def test_no_api_can_change_mode(self):
        guard = ModeGuard.initialize(_paper_config())
        with pytest.raises(ModeViolationError):
            guard.attempt_mode_change("real", caller="api_endpoint")

    def test_no_strategy_callback_can_change_mode(self):
        guard = ModeGuard.initialize(_paper_config())
        with pytest.raises(ModeViolationError):
            guard.attempt_mode_change("real", caller="strategy_callback")

    def test_no_self_healing_can_change_mode(self):
        guard = ModeGuard.initialize(_paper_config())
        with pytest.raises(ModeViolationError):
            guard.attempt_mode_change("real", caller="self_healing_routine")

    def test_no_promotion_can_change_mode(self):
        guard = ModeGuard.initialize(_paper_config())
        with pytest.raises(ModeViolationError):
            guard.attempt_mode_change("real", caller="promotion_workflow")

    def test_no_dashboard_can_change_mode(self):
        guard = ModeGuard.initialize(_paper_config())
        with pytest.raises(ModeViolationError):
            guard.attempt_mode_change("real", caller="dashboard_toggle")

    def test_real_mode_also_immutable(self):
        guard = ModeGuard.initialize(_real_config())
        with pytest.raises(ModeViolationError):
            guard.attempt_mode_change("paper", caller="test")


# ─────────────────────────────────────────────────────────────
# Environment resolution
# ─────────────────────────────────────────────────────────────

class TestEnvironmentResolution:
    def test_default_mode_is_paper(self):
        env = {k: v for k, v in os.environ.items() if k != "TRADING_MODE"}
        with patch.dict(os.environ, env, clear=True):
            assert resolve_trading_mode_from_env() == TradingMode.PAPER

    def test_paper_from_env(self):
        with patch.dict(os.environ, {"TRADING_MODE": "paper"}):
            assert resolve_trading_mode_from_env() == TradingMode.PAPER

    def test_real_from_env(self):
        with patch.dict(os.environ, {"TRADING_MODE": "real"}):
            assert resolve_trading_mode_from_env() == TradingMode.REAL

    def test_invalid_mode_raises(self):
        with patch.dict(os.environ, {"TRADING_MODE": "live"}):
            with pytest.raises(ValueError, match="Invalid TRADING_MODE"):
                resolve_trading_mode_from_env()

    def test_acknowledgement_false_by_default(self):
        env = {k: v for k, v in os.environ.items() if k != "REAL_TRADING_ACKNOWLEDGED"}
        with patch.dict(os.environ, env, clear=True):
            assert not check_real_trading_acknowledged()

    def test_acknowledgement_true(self):
        with patch.dict(os.environ, {"REAL_TRADING_ACKNOWLEDGED": "true"}):
            assert check_real_trading_acknowledged()

    def test_operator_token_valid(self):
        import hashlib
        token = "test-operator-token"
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with patch.dict(os.environ, {
            "OPERATOR_APPROVAL_TOKEN": token,
            "OPERATOR_APPROVAL_TOKEN_HASH": token_hash,
        }):
            assert validate_operator_token()

    def test_operator_token_wrong_token_fails(self):
        import hashlib
        token = "correct"
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with patch.dict(os.environ, {
            "OPERATOR_APPROVAL_TOKEN": "wrong",
            "OPERATOR_APPROVAL_TOKEN_HASH": token_hash,
        }):
            assert not validate_operator_token()

    def test_operator_token_missing_fails(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("OPERATOR_APPROVAL_TOKEN", "OPERATOR_APPROVAL_TOKEN_HASH")}
        with patch.dict(os.environ, env, clear=True):
            assert not validate_operator_token()
