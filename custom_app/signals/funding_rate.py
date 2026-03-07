"""
FundingRateGate — blocks trades when funding rate is too costly.

Perpetual futures charge a funding rate every 8 hours:
  Positive rate → longs pay shorts  (bad for new longs)
  Negative rate → shorts pay longs  (bad for new shorts)

Skip the trade when funding cost would erode expected edge.
Uses Bybit's public market API — no API key required.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_BYBIT_FUNDING_URL = "https://api.bybit.com/v5/market/funding/history"
_REQUEST_TIMEOUT = 5
_CACHE_TTL = 5 * 60  # 5 minutes

# Skip trade if funding rate exceeds this threshold (per 8h, as a decimal)
# 0.0005 = 0.05% per 8h ≈ 0.15%/day — well above normal (~0.01%)
_MAX_ADVERSE_FUNDING_RATE = 0.0005


class FundingRateError(Exception):
    """Raised when funding rate check blocks a trade."""

    def __init__(self, pair: str, side: str, rate: float) -> None:
        direction = "long" if side == "long" else "short"
        super().__init__(
            f"[FundingRate] Skipping {direction} on {pair}: "
            f"funding rate {rate*100:.4f}% is too adverse"
        )
        self.pair = pair
        self.side = side
        self.rate = rate


class FundingRateGate:
    """
    Checks Bybit perpetual funding rate before entry.
    Skips trade if rate would significantly erode expected edge.
    Fail-open on API errors (funding check is advisory, not gating).
    """

    def __init__(self, max_adverse_rate: float = _MAX_ADVERSE_FUNDING_RATE) -> None:
        self._max_rate = max_adverse_rate
        # {symbol: (fetch_time, rate)}
        self._cache: dict[str, tuple[float, float]] = {}

    def check(self, pair: str, side: str) -> bool:
        """
        Returns True if trade is allowed, False if funding is too adverse.
        On API failure, returns True (fail-open — funding is advisory).
        """
        symbol = self._pair_to_symbol(pair)
        if not symbol:
            return True  # Spot pair, no funding rate

        rate = self._get_funding_rate(symbol)
        if rate is None:
            logger.warning("[FundingRate] Could not fetch rate for %s — skipping check", pair)
            return True  # Fail-open

        is_adverse = (
            (side == "long" and rate > self._max_rate)
            or (side == "short" and rate < -self._max_rate)
        )

        if is_adverse:
            logger.info(
                "[FundingRate] Blocking %s %s: rate=%.4f%% exceeds threshold %.4f%%",
                side, pair, rate * 100, self._max_rate * 100,
            )
            self._audit(pair, side, rate, blocked=True)
            return False

        logger.debug("[FundingRate] %s %s approved: rate=%.4f%%", side, pair, rate * 100)
        return True

    def _get_funding_rate(self, symbol: str) -> Optional[float]:
        cached = self._cache.get(symbol)
        if cached:
            fetch_time, rate = cached
            if time.monotonic() - fetch_time < _CACHE_TTL:
                return rate

        try:
            resp = requests.get(
                _BYBIT_FUNDING_URL,
                params={"category": "linear", "symbol": symbol, "limit": 1},
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            entries = data.get("result", {}).get("list", [])
            if not entries:
                return None
            rate = float(entries[0]["fundingRate"])
            self._cache[symbol] = (time.monotonic(), rate)
            return rate
        except requests.RequestException as exc:
            logger.warning("[FundingRate] Request error for %s: %s", symbol, exc)
            return None
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("[FundingRate] Parse error for %s: %s", symbol, exc)
            return None
        except Exception as exc:
            logger.warning("[FundingRate] Unexpected error for %s: %s", symbol, exc)
            return None

    @staticmethod
    def _pair_to_symbol(pair: str) -> Optional[str]:
        """BTC/USDT:USDT → BTCUSDT (Bybit linear format). Spot → None."""
        if ":" not in pair:
            return None  # Spot pair, no funding rate
        base, rest = pair.split("/")
        quote = rest.split(":")[0]
        return f"{base}{quote}"

    def _audit(self, pair: str, side: str, rate: float, blocked: bool) -> None:
        try:
            from custom_app.audit import AuditLogger, AuditEventType
            AuditLogger.get_instance().log_event(
                event_type=AuditEventType.RISK_VETO,
                actor="funding_rate_gate",
                action=f"Funding rate {'blocked' if blocked else 'passed'}: {pair} {side}",
                details={"pair": pair, "side": side, "funding_rate": rate},
                outcome="blocked" if blocked else "approved",
            )
        except Exception:
            pass
