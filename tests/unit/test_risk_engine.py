"""
Tests for the risk engine — proves veto power and all risk checks.
"""

import pytest
from custom_app.risk_layer import RiskEngine, RiskVetoError, TradeIntent, RiskLimits, RiskState


@pytest.fixture(autouse=True)
def reset_risk_engine():
    RiskEngine._reset_for_testing()
    yield
    RiskEngine._reset_for_testing()


def _limits(**overrides) -> RiskLimits:
    defaults = dict(
        max_daily_loss_pct=2.0,
        max_drawdown_pct=10.0,
        kill_switch_drawdown_pct=15.0,
        max_leverage=3.0,
        max_open_trades=5,
        max_position_size_pct=10.0,
        max_total_exposure_pct=50.0,
        consecutive_loss_pause_count=3,
        min_trade_interval_seconds=0.0,
        max_rejection_rate=0.3,
    )
    defaults.update(overrides)
    return RiskLimits(**defaults)


def _intent(**kwargs) -> TradeIntent:
    defaults = dict(pair="BTC/USDT", side="buy", amount_quote=100.0, leverage=1.0)
    defaults.update(kwargs)
    return TradeIntent(**defaults)


class TestRiskEngineVeto:

    def test_clean_trade_passes(self):
        engine = RiskEngine.initialize(_limits())
        engine.update_state(total_equity=10000.0, open_trade_count=0)
        engine.evaluate(_intent(amount_quote=100.0))  # Should not raise

    def test_kill_switch_vetoes_all_trades(self):
        engine = RiskEngine.initialize(_limits())
        engine.arm_kill_switch("test")
        with pytest.raises(RiskVetoError, match="kill_switch"):
            engine.evaluate(_intent())

    def test_daily_loss_cap_vetoes(self):
        engine = RiskEngine.initialize(_limits(max_daily_loss_pct=2.0))
        engine.update_state(daily_loss_pct=2.5)
        with pytest.raises(RiskVetoError, match="daily_loss_cap"):
            engine.evaluate(_intent())

    def test_drawdown_cap_vetoes(self):
        engine = RiskEngine.initialize(_limits(max_drawdown_pct=10.0))
        engine.update_state(current_drawdown_pct=11.0)
        with pytest.raises(RiskVetoError, match="drawdown_cap"):
            engine.evaluate(_intent())

    def test_drawdown_kill_switch_triggers_at_threshold(self):
        engine = RiskEngine.initialize(_limits(kill_switch_drawdown_pct=15.0))
        engine.update_state(current_drawdown_pct=16.0)
        with pytest.raises(RiskVetoError, match="drawdown_kill_switch"):
            engine.evaluate(_intent())
        assert engine.is_kill_switch_active()

    def test_open_trade_cap_vetoes(self):
        engine = RiskEngine.initialize(_limits(max_open_trades=3))
        engine.update_state(open_trade_count=3)
        with pytest.raises(RiskVetoError, match="open_trade_cap"):
            engine.evaluate(_intent())

    def test_position_size_cap_vetoes(self):
        engine = RiskEngine.initialize(_limits(max_position_size_pct=10.0))
        engine.update_state(total_equity=1000.0)
        with pytest.raises(RiskVetoError, match="position_size_cap"):
            engine.evaluate(_intent(amount_quote=200.0))  # 20% > 10%

    def test_total_exposure_cap_vetoes(self):
        engine = RiskEngine.initialize(_limits(max_total_exposure_pct=50.0))
        engine.update_state(total_equity=1000.0, total_exposure_pct=45.0)
        with pytest.raises(RiskVetoError, match="total_exposure_cap"):
            engine.evaluate(_intent(amount_quote=100.0))  # Would push to 55%

    def test_leverage_cap_vetoes(self):
        engine = RiskEngine.initialize(_limits(max_leverage=3.0))
        with pytest.raises(RiskVetoError, match="leverage_cap"):
            engine.evaluate(_intent(leverage=5.0))

    def test_consecutive_loss_pause_vetoes(self):
        engine = RiskEngine.initialize(_limits(consecutive_loss_pause_count=3))
        engine.update_state(consecutive_losses=3)
        with pytest.raises(RiskVetoError, match="consecutive_loss_pause"):
            engine.evaluate(_intent())

    def test_fail_closed_on_exception(self):
        """Risk engine must fail closed (veto) on unexpected errors."""
        engine = RiskEngine.initialize(_limits())
        # Force a non-zero equity so NaN position size triggers division
        engine.update_state(total_equity=1000.0)
        bad_intent = TradeIntent(pair="BTC/USDT", side="buy", amount_quote=float("nan"), leverage=1.0)
        # NaN comparisons in position size check raise or produce unexpected results
        # Either RiskVetoError or caught exception → RiskVetoError
        with pytest.raises(RiskVetoError):
            engine.evaluate(bad_intent)

    def test_singleton_behavior(self):
        e1 = RiskEngine.initialize(_limits())
        e2 = RiskEngine.get_instance()
        assert e1 is e2


class TestRiskLimits:
    def test_defaults_are_conservative(self):
        limits = RiskLimits()
        assert limits.max_daily_loss_pct <= 3.0
        assert limits.max_drawdown_pct <= 15.0
        assert limits.max_leverage <= 5.0
        assert limits.max_open_trades <= 10
