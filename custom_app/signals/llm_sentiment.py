"""
LLMSentimentGate — Claude Haiku as the final trade filter.

Called ONLY after all technical, risk, and funding gates pass.
This keeps API costs near zero (typically 5–15 calls/day).

Design:
- Fail-open on API errors (LLM is enhancement, not primary gate)
- Fail-closed on black_swan events (halt all trading for 30 min)
- 15-minute cache per pair to avoid redundant calls
- Circuit breaker: disable LLM after 5 consecutive failures
- Prompt injection protection: headlines sanitised before sending
- API key never logged
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from custom_app.signals.macro_collector import MacroContext

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_REQUEST_TIMEOUT = 15  # seconds
_CACHE_TTL = 15 * 60  # 15 minutes per pair/side
_CIRCUIT_BREAKER_THRESHOLD = 5   # failures before disabling
_CIRCUIT_BREAKER_RESET = 30 * 60  # re-enable after 30 min
_BLACK_SWAN_COOLDOWN = 30 * 60   # halt all trades for 30 min

# Thresholds: trade blocked if sentiment score is adverse
_LONG_MIN_SENTIMENT = -0.3   # block long if sentiment < -0.3
_SHORT_MAX_SENTIMENT = 0.3   # block short if sentiment > +0.3
_MIN_CONFIDENCE = 0.4        # block if LLM is uncertain


@dataclass(frozen=True)
class SentimentResult:
    """Structured output from the LLM sentiment gate."""
    pair: str
    side: str
    sentiment: float      # -1.0 (very bearish) to +1.0 (very bullish)
    confidence: float     # 0.0 to 1.0
    black_swan: bool      # True = halt all trading for 30 min
    reason: str           # Short explanation (max 20 words)
    allowed: bool         # Final allow/block decision
    source: str           # "llm" | "cache" | "skipped" | "circuit_open"


class SentimentUnavailable(Exception):
    """LLM service is temporarily unavailable."""


class LLMSentimentGate:
    """
    Claude Haiku sentiment gate.
    One instance per strategy — not a singleton (strategies may run isolated).
    Thread-safe caching with monotonic clock.
    """

    def __init__(self, model: Optional[str] = None) -> None:
        self._model = model or os.environ.get("SENTIMENT_MODEL", _DEFAULT_MODEL)
        self._client = self._build_client()
        # Cache: {(pair, side): (timestamp, SentimentResult)}
        self._cache: dict[tuple[str, str], tuple[float, SentimentResult]] = {}
        # Circuit breaker
        self._failure_count = 0
        self._circuit_open_until: float = 0.0
        # Black swan: time until which ALL trades are halted
        self._black_swan_until: float = 0.0
        # Lock protecting all mutable state above
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        pair: str,
        side: str,
        headlines: list[str],
        macro_context: "Optional[MacroContext]" = None,
    ) -> SentimentResult:
        """
        Evaluate sentiment and return a SentimentResult.
        Never raises — returns a result with allowed=True on API errors (fail-open).
        Thread-safe.
        macro_context: optional pre-computed macro state for richer LLM context.
        """
        now = time.monotonic()

        with self._lock:
            # Black swan check — blocks all pairs
            if now < self._black_swan_until:
                remaining = int(self._black_swan_until - now) // 60
                logger.warning(
                    "[LLMSentiment] Black swan cooldown active — blocking all trades (%d min remaining)",
                    remaining,
                )
                return SentimentResult(
                    pair=pair, side=side, sentiment=0.0, confidence=1.0,
                    black_swan=True, reason="Black swan cooldown active",
                    allowed=False, source="circuit_open",
                )

            # Cache check
            cached = self._get_cached_locked(pair, side, now)
            if cached is not None:
                logger.debug("[LLMSentiment] Cache hit for %s %s", side, pair)
                return cached

            # Circuit breaker
            if now < self._circuit_open_until:
                logger.warning("[LLMSentiment] Circuit open — skipping LLM call for %s", pair)
                return self._make_result(pair, side, 0.0, 0.5, False, "Circuit breaker open", "circuit_open")

        # No headlines — proceed with neutral context
        if not headlines:
            logger.debug("[LLMSentiment] No headlines for %s — calling LLM with no context", pair)

        result = self._call_llm(pair, side, headlines, macro_context)

        with self._lock:
            # Only cache successful LLM results — don't cache errors/skipped
            # so that transient failures retry on the next call
            if result.source == "llm":
                self._cache[(pair, side)] = (time.monotonic(), result)
            if result.black_swan:
                self._black_swan_until = time.monotonic() + _BLACK_SWAN_COOLDOWN
                logger.critical(
                    "[LLMSentiment] BLACK SWAN detected for %s — halting all trades for 30 min: %s",
                    pair, result.reason,
                )

        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _call_llm(
        self,
        pair: str,
        side: str,
        headlines: list[str],
        macro_context: "Optional[MacroContext]" = None,
    ) -> SentimentResult:
        if self._client is None:
            logger.warning("[LLMSentiment] Client not available — skipping LLM gate")
            return self._make_result(pair, side, 0.0, 0.0, False, "LLM unavailable", "skipped")

        prompt = self._build_prompt(pair, side, headlines, macro_context)
        try:
            message = self._client.messages.create(
                model=self._model,
                max_tokens=120,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text.strip()
            result = self._parse_response(pair, side, raw)
            with self._lock:
                self._failure_count = 0  # Reset on success
            self._audit(result)
            return result

        except Exception as exc:
            # Strip any potential key fragments from logs
            safe_msg = self._sanitise_error(str(exc))
            logger.warning("[LLMSentiment] API error for %s: %s — failing open", pair, safe_msg)
            with self._lock:
                self._failure_count += 1
                if self._failure_count >= _CIRCUIT_BREAKER_THRESHOLD:
                    self._circuit_open_until = time.monotonic() + _CIRCUIT_BREAKER_RESET
                    logger.error(
                        "[LLMSentiment] %d consecutive failures — circuit open for 30 min",
                        self._failure_count,
                    )
            return self._make_result(pair, side, 0.0, 0.0, False, f"API error: {safe_msg}", "skipped")

    def _build_prompt(
        self,
        pair: str,
        side: str,
        headlines: list[str],
        macro_context: "Optional[MacroContext]" = None,
    ) -> str:
        direction = "buying (long)" if side == "long" else "selling short"
        if headlines:
            headline_block = "\n".join(f"- {h}" for h in headlines)
        else:
            headline_block = "(no recent headlines available)"

        # Macro context block — added when pre-computed state is available
        if macro_context is not None:
            ob_pct = round(macro_context.orderbook_imbalance * 100)
            liq_str = "YES — cascade in progress" if macro_context.liquidation_alert else "none"
            oi_str = f"{macro_context.oi_change_pct:+.1f}%"
            macro_block = (
                f"\nMACRO CONTEXT (pre-computed, 30s old max):\n"
                f"Fear & Greed: {macro_context.fear_greed_value} ({macro_context.fear_greed_label})\n"
                f"Geopolitical risk: {macro_context.geo_risk_score:.2f}/1.0 ({macro_context.geo_risk_summary})\n"
                f"Liquidation cascade: {liq_str}\n"
                f"Open interest trend: {oi_str} (negative = positions closing)\n"
                f"Orderbook: {ob_pct}% bids (>65% bullish pressure, <35% bearish)\n"
            )
        else:
            macro_block = ""

        return (
            f"You are a crypto market sentiment filter for an automated trading bot.\n"
            f"PAIR: {pair}\n"
            f"DIRECTION: {direction}\n"
            f"RECENT HEADLINES:\n{headline_block}\n"
            f"{macro_block}\n"
            f"Respond in JSON only — no explanation outside the JSON:\n"
            f'{{"sentiment": <float -1.0 to 1.0>, '
            f'"confidence": <float 0.0 to 1.0>, '
            f'"black_swan": <bool — true ONLY for: exchange hacks/bankruptcy, '
            f'regulatory bans, major protocol exploits>, '
            f'"reason": "<max 15 words>"}}\n\n'
            f"Rules: sentiment>0 = bullish, sentiment<0 = bearish. "
            f"Low confidence if news is old or irrelevant. "
            f"black_swan only for catastrophic, market-halting events. "
            f"Consider macro context in your assessment."
        )

    def _parse_response(self, pair: str, side: str, raw: str) -> SentimentResult:
        # Extract JSON from response (LLM sometimes wraps in markdown)
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            raise ValueError(f"No JSON found in LLM response: {raw[:100]}")

        data = json.loads(json_match.group())

        sentiment = float(data.get("sentiment", 0.0))
        confidence = float(data.get("confidence", 0.0))
        black_swan = bool(data.get("black_swan", False))
        reason = str(data.get("reason", ""))[:100]

        # Clamp to valid ranges
        sentiment = max(-1.0, min(1.0, sentiment))
        confidence = max(0.0, min(1.0, confidence))

        # Determine if trade is allowed
        allowed = self._is_allowed(side, sentiment, confidence, black_swan)

        return SentimentResult(
            pair=pair, side=side, sentiment=sentiment, confidence=confidence,
            black_swan=black_swan, reason=reason, allowed=allowed, source="llm",
        )

    def _is_allowed(self, side: str, sentiment: float, confidence: float, black_swan: bool) -> bool:
        if black_swan:
            return False
        if confidence < _MIN_CONFIDENCE:
            # Low confidence → allow but log
            logger.info("[LLMSentiment] Low confidence (%.2f) — allowing trade", confidence)
            return True
        if side == "long" and sentiment < _LONG_MIN_SENTIMENT:
            return False
        if side == "short" and sentiment > _SHORT_MAX_SENTIMENT:
            return False
        return True

    def _get_cached_locked(self, pair: str, side: str, now: float) -> Optional[SentimentResult]:
        """Return cached result if still valid. Must be called while holding self._lock."""
        entry = self._cache.get((pair, side))
        if entry is None:
            return None
        ts, result = entry
        if now - ts > _CACHE_TTL:
            del self._cache[(pair, side)]
            return None
        return SentimentResult(
            pair=result.pair, side=result.side, sentiment=result.sentiment,
            confidence=result.confidence, black_swan=result.black_swan,
            reason=result.reason, allowed=result.allowed, source="cache",
        )

    def _make_result(
        self, pair: str, side: str, sentiment: float, confidence: float,
        black_swan: bool, reason: str, source: str,
    ) -> SentimentResult:
        allowed = not black_swan  # On skip/error, allow unless black swan
        return SentimentResult(
            pair=pair, side=side, sentiment=sentiment, confidence=confidence,
            black_swan=black_swan, reason=reason, allowed=allowed, source=source,
        )

    def _build_client(self):
        try:
            import anthropic
            api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
            if not api_key:
                logger.warning(
                    "[LLMSentiment] ANTHROPIC_API_KEY not set — LLM gate disabled. "
                    "Add it to .env to enable sentiment filtering."
                )
                return None
            return anthropic.Anthropic(
                api_key=api_key,
                timeout=_REQUEST_TIMEOUT,
            )
        except ImportError:
            logger.warning(
                "[LLMSentiment] anthropic package not installed. "
                "Run: pip install anthropic"
            )
            return None

    @staticmethod
    def _sanitise_error(msg: str) -> str:
        """Remove any potential API key fragments from error messages."""
        # API keys start with sk-ant-, strip anything that looks like one
        return re.sub(r"sk-[a-zA-Z0-9\-_]{10,}", "[REDACTED]", msg)

    def _audit(self, result: SentimentResult) -> None:
        try:
            from custom_app.audit import AuditLogger, AuditEventType
            event = (
                AuditEventType.NO_ALPHA_GATE_BLOCK
                if not result.allowed
                else AuditEventType.NO_ALPHA_GATE_PASS
            )
            AuditLogger.get_instance().log_event(
                event_type=event,
                actor="llm_sentiment_gate",
                action=f"LLM sentiment {'blocked' if not result.allowed else 'approved'}: "
                       f"{result.side} {result.pair}",
                details={
                    "pair": result.pair,
                    "side": result.side,
                    "sentiment": result.sentiment,
                    "confidence": result.confidence,
                    "black_swan": result.black_swan,
                    "reason": result.reason,
                    "source": result.source,
                    "model": self._model,
                },
                outcome="blocked" if not result.allowed else "approved",
            )
        except Exception:
            pass
