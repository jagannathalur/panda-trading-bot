"""
Tests for custom_app/signals — funding_rate, news_fetcher, llm_sentiment.

All external HTTP calls are mocked. API key is never required.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from custom_app.signals.funding_rate import FundingRateGate, FundingRateError
from custom_app.signals.news_fetcher import NewsFetcher
from custom_app.signals.llm_sentiment import LLMSentimentGate, SentimentResult


# ──────────────────────────────────────────────────────────────
# FundingRateGate
# ──────────────────────────────────────────────────────────────

class TestFundingRateGatePairConversion:

    def test_futures_pair_converts_to_symbol(self):
        assert FundingRateGate._pair_to_symbol("BTC/USDT:USDT") == "BTCUSDT"
        assert FundingRateGate._pair_to_symbol("ETH/USDT:USDT") == "ETHUSDT"
        assert FundingRateGate._pair_to_symbol("SOL/USDT:USDT") == "SOLUSDT"

    def test_spot_pair_returns_none(self):
        assert FundingRateGate._pair_to_symbol("BTC/USDT") is None

    def test_spot_pair_check_always_passes(self):
        gate = FundingRateGate()
        assert gate.check("BTC/USDT", "long") is True
        assert gate.check("BTC/USDT", "short") is True


class TestFundingRateGateLogic:

    def _gate_with_rate(self, rate: float, max_rate: float = 0.0005) -> FundingRateGate:
        gate = FundingRateGate(max_adverse_rate=max_rate)
        gate._cache["BTCUSDT"] = (time.monotonic(), rate)
        return gate

    def test_normal_positive_rate_allows_long(self):
        gate = self._gate_with_rate(0.0001)
        assert gate.check("BTC/USDT:USDT", "long") is True

    def test_high_positive_rate_blocks_long(self):
        gate = self._gate_with_rate(0.001)  # 0.1% > threshold 0.05%
        assert gate.check("BTC/USDT:USDT", "long") is False

    def test_high_negative_rate_blocks_short(self):
        gate = self._gate_with_rate(-0.001)
        assert gate.check("BTC/USDT:USDT", "short") is False

    def test_high_positive_rate_allows_short(self):
        gate = self._gate_with_rate(0.001)  # positive rate hurts longs, not shorts
        assert gate.check("BTC/USDT:USDT", "short") is True

    def test_fail_open_on_api_error(self):
        gate = FundingRateGate()
        with patch("custom_app.signals.funding_rate.requests.get", side_effect=Exception("network down")):
            result = gate.check("BTC/USDT:USDT", "long")
        assert result is True  # Fail-open

    def test_cache_hit_skips_api(self):
        gate = FundingRateGate()
        gate._cache["BTCUSDT"] = (time.monotonic(), 0.0001)
        with patch("custom_app.signals.funding_rate.requests.get") as mock_get:
            gate.check("BTC/USDT:USDT", "long")
            mock_get.assert_not_called()

    def test_stale_cache_triggers_refetch(self):
        gate = FundingRateGate()
        # Put a very old cache entry
        gate._cache["BTCUSDT"] = (time.monotonic() - 9999, 0.0001)

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "result": {"list": [{"fundingRate": "0.0001"}]}
        }
        with patch("custom_app.signals.funding_rate.requests.get", return_value=mock_resp):
            result = gate.check("BTC/USDT:USDT", "long")
        assert result is True

    def test_empty_api_response_fails_open(self):
        gate = FundingRateGate()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"result": {"list": []}}
        with patch("custom_app.signals.funding_rate.requests.get", return_value=mock_resp):
            result = gate.check("BTC/USDT:USDT", "long")
        assert result is True  # None rate → fail-open


# ──────────────────────────────────────────────────────────────
# NewsFetcher
# ──────────────────────────────────────────────────────────────

class TestNewsFetcherCurrencyExtraction:

    def test_spot_pair(self):
        assert NewsFetcher._extract_currency("BTC/USDT") == "BTC"

    def test_futures_pair(self):
        assert NewsFetcher._extract_currency("ETH/USDT:USDT") == "ETH"

    def test_lowercase_normalised(self):
        assert NewsFetcher._extract_currency("sol/usdt") == "SOL"


class TestNewsFetcherFetch:

    def _mock_api_response(self, titles: list[str]) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "results": [{"title": t} for t in titles]
        }
        return mock_resp

    def test_returns_headlines_from_api(self):
        fetcher = NewsFetcher()
        headlines = ["BTC breaks ATH", "Bitcoin ETF approved"]
        mock_resp = self._mock_api_response(headlines)
        with patch("custom_app.signals.news_fetcher.requests.get", return_value=mock_resp):
            result = fetcher.fetch("BTC/USDT")
        assert result == headlines

    def test_empty_on_request_error(self):
        fetcher = NewsFetcher()
        with patch("custom_app.signals.news_fetcher.requests.get", side_effect=Exception("timeout")):
            result = fetcher.fetch("BTC/USDT")
        assert result == []

    def test_empty_on_empty_results(self):
        fetcher = NewsFetcher()
        mock_resp = self._mock_api_response([])
        with patch("custom_app.signals.news_fetcher.requests.get", return_value=mock_resp):
            result = fetcher.fetch("BTC/USDT")
        assert result == []

    def test_cache_hit_returns_cached(self):
        fetcher = NewsFetcher()
        fetcher._cache["BTC"] = (time.monotonic(), ["Cached headline"])
        with patch("custom_app.signals.news_fetcher.requests.get") as mock_get:
            result = fetcher.fetch("BTC/USDT")
            mock_get.assert_not_called()
        assert result == ["Cached headline"]

    def test_stale_cache_refetches(self):
        fetcher = NewsFetcher()
        fetcher._cache["BTC"] = (time.monotonic() - 9999, ["Old headline"])
        mock_resp = self._mock_api_response(["Fresh headline"])
        with patch("custom_app.signals.news_fetcher.requests.get", return_value=mock_resp):
            result = fetcher.fetch("BTC/USDT")
        assert result == ["Fresh headline"]

    def test_headline_truncated_to_max_chars(self):
        fetcher = NewsFetcher()
        long_title = "X" * 200
        mock_resp = self._mock_api_response([long_title])
        with patch("custom_app.signals.news_fetcher.requests.get", return_value=mock_resp):
            result = fetcher.fetch("BTC/USDT")
        assert len(result[0]) == 120

    def test_max_headlines_limit(self):
        fetcher = NewsFetcher()
        titles = [f"Headline {i}" for i in range(20)]
        mock_resp = self._mock_api_response(titles)
        with patch("custom_app.signals.news_fetcher.requests.get", return_value=mock_resp):
            result = fetcher.fetch("BTC/USDT")
        assert len(result) <= 8  # _MAX_HEADLINES = 8

    def test_non_printable_chars_stripped(self):
        fetcher = NewsFetcher()
        dirty_title = "BTC\x00breaks\x1fATH"
        mock_resp = self._mock_api_response([dirty_title])
        with patch("custom_app.signals.news_fetcher.requests.get", return_value=mock_resp):
            result = fetcher.fetch("BTC/USDT")
        assert "\x00" not in result[0]
        assert "\x1f" not in result[0]


# ──────────────────────────────────────────────────────────────
# LLMSentimentGate
# ──────────────────────────────────────────────────────────────

def _make_gate(model: str = "test-model") -> LLMSentimentGate:
    """Return a gate with no real API client."""
    gate = LLMSentimentGate(model=model)
    gate._client = None  # disable real API calls
    return gate


def _mock_llm_response(json_str: str) -> MagicMock:
    mock_client = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=json_str)]
    mock_client.messages.create.return_value = mock_msg
    return mock_client


class TestLLMSentimentGate:

    def test_no_client_fails_open(self):
        gate = _make_gate()
        result = gate.evaluate("BTC/USDT", "long", [])
        assert result.allowed is True
        assert result.source == "skipped"

    def test_allows_bullish_long(self):
        gate = _make_gate()
        gate._client = _mock_llm_response(
            '{"sentiment": 0.7, "confidence": 0.8, "black_swan": false, "reason": "Strong rally"}'
        )
        result = gate.evaluate("BTC/USDT", "long", ["BTC ATH incoming"])
        assert result.allowed is True
        assert result.sentiment == pytest.approx(0.7)

    def test_blocks_bearish_long(self):
        gate = _make_gate()
        gate._client = _mock_llm_response(
            '{"sentiment": -0.6, "confidence": 0.85, "black_swan": false, "reason": "Major crash"}'
        )
        result = gate.evaluate("BTC/USDT", "long", ["BTC crash"])
        assert result.allowed is False

    def test_allows_bearish_short(self):
        gate = _make_gate()
        gate._client = _mock_llm_response(
            '{"sentiment": -0.5, "confidence": 0.8, "black_swan": false, "reason": "Bear market"}'
        )
        result = gate.evaluate("BTC/USDT", "short", ["BTC declining"])
        assert result.allowed is True

    def test_blocks_bullish_short(self):
        gate = _make_gate()
        gate._client = _mock_llm_response(
            '{"sentiment": 0.6, "confidence": 0.9, "black_swan": false, "reason": "Huge rally"}'
        )
        result = gate.evaluate("BTC/USDT", "short", ["BTC ATH"])
        assert result.allowed is False

    def test_black_swan_blocks_all(self):
        gate = _make_gate()
        gate._client = _mock_llm_response(
            '{"sentiment": 0.0, "confidence": 1.0, "black_swan": true, "reason": "Exchange hacked"}'
        )
        result = gate.evaluate("BTC/USDT", "long", ["Exchange collapsed"])
        assert result.allowed is False
        assert result.black_swan is True

    def test_black_swan_sets_cooldown(self):
        gate = _make_gate()
        gate._client = _mock_llm_response(
            '{"sentiment": 0.0, "confidence": 1.0, "black_swan": true, "reason": "Exchange hacked"}'
        )
        gate.evaluate("BTC/USDT", "long", [])
        with gate._lock:
            assert gate._black_swan_until > time.monotonic()

    def test_black_swan_cooldown_blocks_next_call(self):
        gate = _make_gate()
        with gate._lock:
            gate._black_swan_until = time.monotonic() + 9999
        result = gate.evaluate("ETH/USDT", "long", [])
        assert result.allowed is False
        assert result.black_swan is True

    def test_cache_hit_returns_cached_result(self):
        gate = _make_gate()
        cached = SentimentResult(
            pair="BTC/USDT", side="long", sentiment=0.5, confidence=0.8,
            black_swan=False, reason="Cached", allowed=True, source="llm"
        )
        with gate._lock:
            gate._cache[("BTC/USDT", "long")] = (time.monotonic(), cached)
        result = gate.evaluate("BTC/USDT", "long", [])
        assert result.source == "cache"
        assert result.sentiment == 0.5

    def test_stale_cache_triggers_new_call(self):
        gate = _make_gate()
        cached = SentimentResult(
            pair="BTC/USDT", side="long", sentiment=0.5, confidence=0.8,
            black_swan=False, reason="Old", allowed=True, source="llm"
        )
        with gate._lock:
            gate._cache[("BTC/USDT", "long")] = (time.monotonic() - 9999, cached)
        # client=None → falls through to skipped
        result = gate.evaluate("BTC/USDT", "long", [])
        assert result.source == "skipped"

    def test_circuit_breaker_opens_after_failures(self):
        gate = _make_gate()
        gate._client = MagicMock()
        gate._client.messages.create.side_effect = Exception("API down")
        for _ in range(5):
            gate.evaluate("BTC/USDT", "long", [])
        with gate._lock:
            assert gate._circuit_open_until > time.monotonic()

    def test_circuit_open_skips_api(self):
        gate = _make_gate()
        gate._client = MagicMock()
        with gate._lock:
            gate._circuit_open_until = time.monotonic() + 9999
        result = gate.evaluate("BTC/USDT", "long", [])
        gate._client.messages.create.assert_not_called()
        assert result.source == "circuit_open"

    def test_failure_count_resets_on_success(self):
        gate = _make_gate()
        with gate._lock:
            gate._failure_count = 3
        gate._client = _mock_llm_response(
            '{"sentiment": 0.5, "confidence": 0.8, "black_swan": false, "reason": "ok"}'
        )
        gate.evaluate("BTC/USDT", "long", [])
        with gate._lock:
            assert gate._failure_count == 0

    def test_low_confidence_allows_trade(self):
        gate = _make_gate()
        gate._client = _mock_llm_response(
            '{"sentiment": -0.5, "confidence": 0.3, "black_swan": false, "reason": "Uncertain"}'
        )
        result = gate.evaluate("BTC/USDT", "long", [])
        # Confidence < 0.4 → allowed (uncertain data shouldn't block)
        assert result.allowed is True

    def test_api_error_fails_open(self):
        gate = _make_gate()
        gate._client = MagicMock()
        gate._client.messages.create.side_effect = Exception("Connection refused")
        result = gate.evaluate("BTC/USDT", "long", [])
        assert result.allowed is True
        assert result.source == "skipped"

    def test_sentiment_clamped_to_valid_range(self):
        gate = _make_gate()
        gate._client = _mock_llm_response(
            '{"sentiment": 5.0, "confidence": 2.0, "black_swan": false, "reason": "extreme"}'
        )
        result = gate.evaluate("BTC/USDT", "long", [])
        assert result.sentiment <= 1.0
        assert result.confidence <= 1.0

    def test_sanitise_error_redacts_api_key(self):
        msg = "Auth failed: sk-ant-api03-ABCDEF1234567890"
        redacted = LLMSentimentGate._sanitise_error(msg)
        assert "sk-ant" not in redacted
        assert "[REDACTED]" in redacted

    def test_malformed_json_response_fails_open(self):
        gate = _make_gate()
        gate._client = _mock_llm_response("not json at all")
        result = gate.evaluate("BTC/USDT", "long", [])
        # Parse error → caught → fail open
        assert result.allowed is True
