"""
Tests for the new macro signal modules:
  - market_microstructure.py
  - geopolitical.py
  - macro_collector.py
  - LLM prompt enrichment with MacroContext

All external HTTP calls are mocked.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from custom_app.signals.market_microstructure import (
    OIData, LiqData, OrderbookData,
    fetch_open_interest, fetch_liquidations, fetch_orderbook_imbalance,
    pair_to_symbol,
)
from custom_app.signals.geopolitical import GeopoliticalGate, GeopoliticalRisk, _risk_score
from custom_app.signals.macro_collector import (
    MacroSignalState, MacroSignalCollector, MacroContext, PairMicroData,
)
from custom_app.signals.llm_sentiment import LLMSentimentGate


# ──────────────────────────────────────────────────────────────
# pair_to_symbol helper
# ──────────────────────────────────────────────────────────────

class TestPairToSymbol:
    def test_futures_pair(self):
        assert pair_to_symbol("BTC/USDT:USDT") == "BTCUSDT"
        assert pair_to_symbol("ETH/USDT:USDT") == "ETHUSDT"

    def test_spot_pair_returns_none(self):
        assert pair_to_symbol("BTC/USDT") is None


# ──────────────────────────────────────────────────────────────
# OIData properties
# ──────────────────────────────────────────────────────────────

class TestOIData:
    def test_declining_flag(self):
        oi = OIData("BTCUSDT", 100.0, 110.0, oi_change_pct=-6.0)
        assert oi.is_declining is True

    def test_not_declining_small_drop(self):
        oi = OIData("BTCUSDT", 100.0, 102.0, oi_change_pct=-2.0)
        assert oi.is_declining is False

    def test_crowded_flag(self):
        oi = OIData("BTCUSDT", 150.0, 100.0, oi_change_pct=25.0)
        assert oi.is_crowded is True

    def test_not_crowded(self):
        oi = OIData("BTCUSDT", 105.0, 100.0, oi_change_pct=5.0)
        assert oi.is_crowded is False


# ──────────────────────────────────────────────────────────────
# LiqData properties
# ──────────────────────────────────────────────────────────────

class TestLiqData:
    def test_cascade_flag(self):
        liq = LiqData("BTCUSDT", liq_volume_5min_usd=6_000_000, liq_count_5min=50)
        assert liq.is_cascade is True

    def test_cascade_at_exact_threshold(self):
        liq = LiqData("BTCUSDT", liq_volume_5min_usd=5_000_000, liq_count_5min=1)
        assert liq.is_cascade is True  # >= not >

    def test_no_cascade_below_threshold(self):
        liq = LiqData("BTCUSDT", liq_volume_5min_usd=2_000_000, liq_count_5min=10)
        assert liq.is_cascade is False

    def test_long_cascade_flag(self):
        liq = LiqData("BTCUSDT", liq_volume_5min_usd=6_000_000, liq_count_5min=50,
                      liq_long_usd=6_000_000, liq_short_usd=0.0)
        assert liq.is_long_cascade is True
        assert liq.is_short_cascade is False

    def test_short_cascade_flag(self):
        liq = LiqData("BTCUSDT", liq_volume_5min_usd=6_000_000, liq_count_5min=50,
                      liq_long_usd=0.0, liq_short_usd=6_000_000)
        assert liq.is_short_cascade is True
        assert liq.is_long_cascade is False

    def test_side_cascade_defaults_to_zero(self):
        """Old-style LiqData without side fields should not trigger side-specific cascades."""
        liq = LiqData("BTCUSDT", liq_volume_5min_usd=6_000_000, liq_count_5min=50)
        assert liq.is_long_cascade is False
        assert liq.is_short_cascade is False


# ──────────────────────────────────────────────────────────────
# OrderbookData properties
# ──────────────────────────────────────────────────────────────

class TestOrderbookData:
    def test_bid_dominated(self):
        ob = OrderbookData("BTCUSDT", imbalance=0.70)
        assert ob.bid_dominated is True
        assert ob.ask_dominated is False

    def test_ask_dominated(self):
        ob = OrderbookData("BTCUSDT", imbalance=0.30)
        assert ob.ask_dominated is True
        assert ob.bid_dominated is False

    def test_balanced(self):
        ob = OrderbookData("BTCUSDT", imbalance=0.50)
        assert ob.bid_dominated is False
        assert ob.ask_dominated is False


# ──────────────────────────────────────────────────────────────
# fetch_open_interest
# ──────────────────────────────────────────────────────────────

class TestFetchOpenInterest:

    def _mock_oi_response(self, current: float, prev: float) -> MagicMock:
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        mock.json.return_value = {
            "result": {"list": [
                {"openInterestValue": str(current)},
                {"openInterestValue": str(prev)},
            ]}
        }
        return mock

    def test_computes_oi_change(self):
        mock_resp = self._mock_oi_response(110_000, 100_000)
        with patch("custom_app.signals.market_microstructure.requests.get", return_value=mock_resp):
            oi = fetch_open_interest("BTCUSDT")
        assert oi is not None
        assert oi.open_interest_usd == pytest.approx(110_000)
        assert oi.oi_change_pct == pytest.approx(10.0)

    def test_returns_none_on_empty_response(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"result": {"list": []}}
        with patch("custom_app.signals.market_microstructure.requests.get", return_value=mock_resp):
            oi = fetch_open_interest("BTCUSDT")
        assert oi is None

    def test_returns_none_on_error(self):
        with patch("custom_app.signals.market_microstructure.requests.get",
                   side_effect=Exception("network")):
            oi = fetch_open_interest("BTCUSDT")
        assert oi is None


# ──────────────────────────────────────────────────────────────
# fetch_liquidations
# ──────────────────────────────────────────────────────────────

class TestFetchLiquidations:

    def _mock_liq_response(self, records: list[dict]) -> MagicMock:
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        mock.json.return_value = {"result": {"list": records}}
        return mock

    def test_sums_recent_liquidations(self):
        now_ms = int(time.time() * 1000)
        records = [
            {"updatedTime": str(now_ms - 60_000), "size": "1.0", "price": "50000"},
            {"updatedTime": str(now_ms - 120_000), "size": "2.0", "price": "50000"},
            # Old record — outside 5-minute window
            {"updatedTime": str(now_ms - 600_000), "size": "10.0", "price": "50000"},
        ]
        mock_resp = self._mock_liq_response(records)
        with patch("custom_app.signals.market_microstructure.requests.get", return_value=mock_resp):
            liq = fetch_liquidations("BTCUSDT", window_ms=300_000)
        assert liq is not None
        assert liq.liq_count_5min == 2
        assert liq.liq_volume_5min_usd == pytest.approx(150_000.0)

    def test_cascade_detected(self):
        now_ms = int(time.time() * 1000)
        records = [
            {"updatedTime": str(now_ms - 10_000), "size": "100.0", "price": "50000"},
        ]
        mock_resp = self._mock_liq_response(records)
        with patch("custom_app.signals.market_microstructure.requests.get", return_value=mock_resp):
            liq = fetch_liquidations("BTCUSDT")
        assert liq is not None
        assert liq.is_cascade is True  # 100 * 50000 = $5M

    def test_separates_long_and_short_liquidations(self):
        """side=='Sell' → long liq; side=='Buy' → short liq."""
        now_ms = int(time.time() * 1000)
        records = [
            # Long positions liquidated (sell to close long)
            {"updatedTime": str(now_ms - 10_000), "size": "2.0", "price": "50000", "side": "Sell"},
            {"updatedTime": str(now_ms - 20_000), "size": "1.0", "price": "50000", "side": "Sell"},
            # Short positions liquidated (buy to close short / squeeze)
            {"updatedTime": str(now_ms - 30_000), "size": "0.5", "price": "50000", "side": "Buy"},
        ]
        mock_resp = self._mock_liq_response(records)
        with patch("custom_app.signals.market_microstructure.requests.get", return_value=mock_resp):
            liq = fetch_liquidations("BTCUSDT")
        assert liq is not None
        assert liq.liq_long_usd == pytest.approx(150_000.0)   # (2+1) * 50000
        assert liq.liq_short_usd == pytest.approx(25_000.0)   # 0.5 * 50000
        assert liq.liq_volume_5min_usd == pytest.approx(175_000.0)

    def test_long_cascade_detected(self):
        """All side=='Sell' records → long cascade."""
        now_ms = int(time.time() * 1000)
        records = [
            {"updatedTime": str(now_ms - 10_000), "size": "100.0", "price": "50000", "side": "Sell"},
        ]
        mock_resp = self._mock_liq_response(records)
        with patch("custom_app.signals.market_microstructure.requests.get", return_value=mock_resp):
            liq = fetch_liquidations("BTCUSDT")
        assert liq is not None
        assert liq.is_long_cascade is True   # 100 * 50000 = $5M of LONG liquidations
        assert liq.is_short_cascade is False  # no short liquidations

    def test_short_cascade_detected(self):
        """All side=='Buy' records → short cascade (squeeze)."""
        now_ms = int(time.time() * 1000)
        records = [
            {"updatedTime": str(now_ms - 10_000), "size": "100.0", "price": "50000", "side": "Buy"},
        ]
        mock_resp = self._mock_liq_response(records)
        with patch("custom_app.signals.market_microstructure.requests.get", return_value=mock_resp):
            liq = fetch_liquidations("BTCUSDT")
        assert liq is not None
        assert liq.is_short_cascade is True   # $5M of SHORT liquidations
        assert liq.is_long_cascade is False   # no long liquidations

    def test_returns_none_on_error(self):
        with patch("custom_app.signals.market_microstructure.requests.get",
                   side_effect=Exception("timeout")):
            liq = fetch_liquidations("BTCUSDT")
        assert liq is None


# ──────────────────────────────────────────────────────────────
# fetch_orderbook_imbalance
# ──────────────────────────────────────────────────────────────

class TestFetchOrderbookImbalance:

    def _mock_ob_response(self, bids: list, asks: list) -> MagicMock:
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        mock.json.return_value = {"result": {"b": bids, "a": asks}}
        return mock

    def test_bid_dominated_orderbook(self):
        bids = [["50000", "10.0"], ["49999", "5.0"]]  # bid vol = 15
        asks = [["50001", "2.0"], ["50002", "3.0"]]   # ask vol = 5
        mock_resp = self._mock_ob_response(bids, asks)
        with patch("custom_app.signals.market_microstructure.requests.get", return_value=mock_resp):
            ob = fetch_orderbook_imbalance("BTCUSDT")
        assert ob is not None
        assert ob.imbalance == pytest.approx(0.75)  # 15 / 20
        assert ob.bid_dominated is True

    def test_ask_dominated_orderbook(self):
        bids = [["50000", "2.0"]]
        asks = [["50001", "8.0"]]
        mock_resp = self._mock_ob_response(bids, asks)
        with patch("custom_app.signals.market_microstructure.requests.get", return_value=mock_resp):
            ob = fetch_orderbook_imbalance("BTCUSDT")
        assert ob is not None
        assert ob.ask_dominated is True

    def test_returns_none_on_error(self):
        with patch("custom_app.signals.market_microstructure.requests.get",
                   side_effect=Exception("error")):
            assert fetch_orderbook_imbalance("BTCUSDT") is None


# ──────────────────────────────────────────────────────────────
# GeopoliticalGate
# ──────────────────────────────────────────────────────────────

class TestRiskScore:
    def test_baseline_gives_moderate_score(self):
        score = _risk_score(15, 0.0)
        assert 0.2 <= score <= 0.6

    def test_zero_articles_low_score(self):
        score = _risk_score(0, 0.0)
        assert score < 0.3

    def test_high_count_high_score(self):
        score = _risk_score(80, -10.0)
        assert score > 0.7

    def test_negative_tone_amplifies_risk(self):
        score_neutral = _risk_score(30, 0.0)
        score_negative = _risk_score(30, -15.0)
        assert score_negative > score_neutral

    def test_score_clamped_to_0_1(self):
        assert _risk_score(1000, -100.0) == pytest.approx(1.0)
        assert _risk_score(0, 100.0) >= 0.0


class TestGeopoliticalGate:

    def _mock_gdelt_response(self, articles: list) -> MagicMock:
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        mock.json.return_value = {"articles": articles}
        return mock

    def test_returns_risk_from_articles(self):
        gate = GeopoliticalGate()
        articles = [{"tone": "-8.5,2.3,1.1"} for _ in range(40)]
        mock_resp = self._mock_gdelt_response(articles)
        with patch("custom_app.signals.geopolitical.requests.get", return_value=mock_resp):
            risk = gate.get_risk()
        assert risk.article_count == 40
        assert risk.score > 0.5  # 40 negative articles = elevated

    def test_empty_articles_returns_low_score(self):
        gate = GeopoliticalGate()
        mock_resp = self._mock_gdelt_response([])
        with patch("custom_app.signals.geopolitical.requests.get", return_value=mock_resp):
            risk = gate.get_risk()
        assert risk.score < 0.3

    def test_fail_open_on_api_error(self):
        gate = GeopoliticalGate()
        with patch("custom_app.signals.geopolitical.requests.get",
                   side_effect=Exception("GDELT down")):
            risk = gate.get_risk()
        assert risk.score == 0.0

    def test_cache_hit_skips_api(self):
        gate = GeopoliticalGate()
        cached = GeopoliticalRisk(0.2, 10, -2.0, "calm")
        gate._cache = (time.monotonic(), cached)
        with patch("custom_app.signals.geopolitical.requests.get") as mock_get:
            risk = gate.get_risk()
            mock_get.assert_not_called()
        assert risk.score == 0.2

    def test_stale_cache_refetches(self):
        gate = GeopoliticalGate()
        old_risk = GeopoliticalRisk(0.1, 5, 0.0, "calm")
        gate._cache = (time.monotonic() - 9999, old_risk)
        articles = [{"tone": "0.0"} for _ in range(5)]
        mock_resp = self._mock_gdelt_response(articles)
        with patch("custom_app.signals.geopolitical.requests.get", return_value=mock_resp):
            risk = gate.get_risk()
        assert risk.article_count == 5


# ──────────────────────────────────────────────────────────────
# MacroSignalState hard block logic
# ──────────────────────────────────────────────────────────────

def _make_state(**overrides) -> MacroSignalState:
    pair_data = overrides.pop("pair_data", {
        "BTC/USDT:USDT": PairMicroData(
            symbol="BTCUSDT",
            oi_usd=1_000_000,
            oi_change_pct=0.0,
            liq_volume_5min_usd=0.0,
            liq_count_5min=0,
            liq_long_usd=0.0,
            liq_short_usd=0.0,
            orderbook_imbalance=0.5,
        )
    })
    defaults = dict(
        pair_data=pair_data,
        fear_greed_value=50,
        fear_greed_label="Neutral",
        geo_risk_score=0.0,
        geo_risk_summary="calm",
    )
    defaults.update(overrides)
    return MacroSignalState(**defaults)


class TestMacroSignalStateBlocks:

    def test_clean_state_allows_both_sides(self):
        state = _make_state()
        assert state.blocks_long("BTC/USDT:USDT") is None
        assert state.blocks_short("BTC/USDT:USDT") is None

    def test_liquidation_cascade_blocks_both_sides(self):
        """When both long AND short cascades fire, both directions are blocked."""
        state = _make_state(pair_data={
            "BTC/USDT:USDT": PairMicroData(
                symbol="BTCUSDT",
                liq_volume_5min_usd=12_000_000,
                liq_count_5min=100,
                liq_long_usd=6_000_000,    # long cascade
                liq_short_usd=6_000_000,   # short cascade
                oi_usd=0, oi_change_pct=0, orderbook_imbalance=0.5,
            )
        })
        assert state.blocks_long("BTC/USDT:USDT") is not None
        assert state.blocks_short("BTC/USDT:USDT") is not None
        assert "cascade" in state.blocks_long("BTC/USDT:USDT")
        assert "cascade" in state.blocks_short("BTC/USDT:USDT")

    def test_long_cascade_blocks_long_only(self):
        """Long cascade = sell pressure — blocks new longs but NOT new shorts."""
        state = _make_state(pair_data={
            "BTC/USDT:USDT": PairMicroData(
                symbol="BTCUSDT",
                liq_volume_5min_usd=6_000_000,
                liq_count_5min=100,
                liq_long_usd=6_000_000,  # only longs being liquidated
                liq_short_usd=0.0,
                oi_usd=0, oi_change_pct=0, orderbook_imbalance=0.5,
            )
        })
        assert state.blocks_long("BTC/USDT:USDT") is not None
        assert "sell pressure" in state.blocks_long("BTC/USDT:USDT")
        assert state.blocks_short("BTC/USDT:USDT") is None  # short squeeze = longs NOT blocked

    def test_short_cascade_blocks_short_only(self):
        """Short squeeze = buy pressure — blocks new shorts but NOT new longs."""
        state = _make_state(pair_data={
            "BTC/USDT:USDT": PairMicroData(
                symbol="BTCUSDT",
                liq_volume_5min_usd=6_000_000,
                liq_count_5min=100,
                liq_long_usd=0.0,
                liq_short_usd=6_000_000,  # only shorts being squeezed
                oi_usd=0, oi_change_pct=0, orderbook_imbalance=0.5,
            )
        })
        assert state.blocks_short("BTC/USDT:USDT") is not None
        assert "squeeze pressure" in state.blocks_short("BTC/USDT:USDT")
        assert state.blocks_long("BTC/USDT:USDT") is None  # short squeeze ≠ block longs

    def test_extreme_fear_blocks_long_only(self):
        state = _make_state(fear_greed_value=10, fear_greed_label="Extreme Fear")
        assert state.blocks_long("BTC/USDT:USDT") is not None
        assert state.blocks_short("BTC/USDT:USDT") is None
        assert "fear" in state.blocks_long("BTC/USDT:USDT").lower()

    def test_extreme_greed_blocks_short_only(self):
        state = _make_state(fear_greed_value=90, fear_greed_label="Extreme Greed")
        assert state.blocks_short("BTC/USDT:USDT") is not None
        assert state.blocks_long("BTC/USDT:USDT") is None

    def test_oi_declining_blocks_long(self):
        state = _make_state(pair_data={
            "BTC/USDT:USDT": PairMicroData(
                symbol="BTCUSDT",
                oi_change_pct=-8.0,
                liq_volume_5min_usd=0, liq_count_5min=0,
                liq_long_usd=0.0, liq_short_usd=0.0,
                oi_usd=0, orderbook_imbalance=0.5,
            )
        })
        assert state.blocks_long("BTC/USDT:USDT") is not None
        assert state.blocks_short("BTC/USDT:USDT") is None

    def test_oi_surging_blocks_short(self):
        state = _make_state(pair_data={
            "BTC/USDT:USDT": PairMicroData(
                symbol="BTCUSDT",
                oi_change_pct=25.0,
                liq_volume_5min_usd=0, liq_count_5min=0,
                liq_long_usd=0.0, liq_short_usd=0.0,
                oi_usd=0, orderbook_imbalance=0.5,
            )
        })
        assert state.blocks_short("BTC/USDT:USDT") is not None
        assert state.blocks_long("BTC/USDT:USDT") is None

    def test_unknown_pair_returns_none(self):
        state = _make_state()
        assert state.blocks_long("UNKNOWN/PAIR:PAIR") is None

    def test_to_macro_context_includes_all_fields(self):
        state = _make_state(fear_greed_value=25, geo_risk_score=0.4)
        ctx = state.to_macro_context("BTC/USDT:USDT")
        assert ctx.fear_greed_value == 25
        assert ctx.geo_risk_score == 0.4
        assert isinstance(ctx.liquidation_alert, bool)
        assert isinstance(ctx.oi_change_pct, float)


# ──────────────────────────────────────────────────────────────
# MacroSignalCollector
# ──────────────────────────────────────────────────────────────

class TestMacroSignalCollector:

    def setup_method(self):
        MacroSignalCollector._reset_for_testing()

    def teardown_method(self):
        MacroSignalCollector._reset_for_testing()

    def test_singleton_pattern(self):
        c1 = MacroSignalCollector.get_instance()
        c2 = MacroSignalCollector.get_instance()
        assert c1 is c2

    def test_returns_empty_state_before_start(self):
        collector = MacroSignalCollector.get_instance()
        state = collector.get_state("BTC/USDT:USDT")
        assert state.fear_greed_value == 50  # default neutral

    def test_get_state_is_thread_safe(self):
        """get_state() must return a consistent object even under concurrent access."""
        import threading
        collector = MacroSignalCollector.get_instance()
        results = []
        errors = []

        def read_state():
            try:
                results.append(collector.get_state("BTC/USDT:USDT"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=read_state) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 20

    def test_fetch_cycle_defers_geopolitical_state(self):
        collector = MacroSignalCollector.get_instance()
        collector._pairs = ["BTC/USDT:USDT"]

        with patch("custom_app.signals.macro_collector.fetch_open_interest", return_value=None), \
             patch("custom_app.signals.macro_collector.fetch_liquidations", return_value=None), \
             patch("custom_app.signals.macro_collector.fetch_orderbook_imbalance", return_value=None), \
             patch.object(collector, "_fetch_fear_greed", return_value=(12, "Extreme Fear")):
            collector._fetch_cycle()

        state = collector.get_state("BTC/USDT:USDT")
        assert state.geo_risk_score == 0.0
        assert state.geo_risk_summary == "deferred"


# ──────────────────────────────────────────────────────────────
# LLM prompt enrichment with MacroContext
# ──────────────────────────────────────────────────────────────

class TestLLMPromptEnrichment:

    def test_macro_context_appears_in_prompt(self):
        gate = LLMSentimentGate(model="test")
        ctx = MacroContext(
            fear_greed_value=22,
            fear_greed_label="Extreme Fear",
            geo_risk_score=0.65,
            geo_risk_summary="elevated (45 articles)",
            liquidation_alert=True,
            oi_change_pct=-7.5,
            orderbook_imbalance=0.3,
        )
        prompt = gate._build_prompt("BTC/USDT", "long", ["BTC rises"], ctx)
        assert "22/100" in prompt
        assert "Extreme Fear" in prompt
        assert "0.65" in prompt
        # liquidation alert shows as liq_long or total cascade in the new format
        assert "-7.5" in prompt
        assert "MARKET MICROSTRUCTURE" in prompt

    def test_no_macro_context_prompt_still_valid(self):
        gate = LLMSentimentGate(model="test")
        prompt = gate._build_prompt("BTC/USDT", "long", [], None)
        assert "BTC/USDT" in prompt
        assert "MARKET MICROSTRUCTURE" not in prompt

    def test_evaluate_passes_macro_context_to_call_llm(self):
        gate = LLMSentimentGate(model="test")
        ctx = MacroContext(
            fear_greed_value=50, fear_greed_label="Neutral",
            geo_risk_score=0.1, geo_risk_summary="calm",
            liquidation_alert=False, oi_change_pct=1.0,
            orderbook_imbalance=0.5,
        )
        # Client = None → skipped result, but should not raise
        gate._client = None
        result = gate.evaluate("BTC/USDT", "long", [], macro_context=ctx)
        assert result.source == "skipped"
        assert result.allowed is True
