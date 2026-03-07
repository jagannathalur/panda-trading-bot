"""
NewsFetcher — fetches recent crypto headlines for LLM sentiment input.

Uses CryptoPanic free API (no auth required for public posts).
Caches results per currency to avoid hammering the API.
Fail-safe: returns empty list on any error (LLM gate handles missing context).
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_CRYPTOPANIC_URL = "https://cryptopanic.com/api/v1/posts/"
_REQUEST_TIMEOUT = 8  # seconds
_CACHE_TTL = 10 * 60  # 10 minutes per currency
_MAX_HEADLINES = 8
_MAX_HEADLINE_CHARS = 120  # prevent prompt bloat


class NewsFetcher:
    """
    Fetches recent cryptocurrency headlines.
    Thread-safe via per-instance cache (one instance per strategy).
    """

    def __init__(self) -> None:
        # {currency: (fetch_time, headlines)}
        self._cache: dict[str, tuple[float, list[str]]] = {}

    def fetch(self, pair: str) -> list[str]:
        """
        Return recent headlines for the given pair.
        Returns empty list on failure — never raises.
        """
        currency = self._extract_currency(pair)
        cached = self._cache.get(currency)
        if cached:
            fetch_time, headlines = cached
            if time.monotonic() - fetch_time < _CACHE_TTL:
                return headlines

        headlines = self._fetch_from_api(currency)
        self._cache[currency] = (time.monotonic(), headlines)
        return headlines

    def _fetch_from_api(self, currency: str) -> list[str]:
        try:
            resp = requests.get(
                _CRYPTOPANIC_URL,
                params={
                    "auth_token": "free",
                    "currencies": currency,
                    "filter": "important",
                    "public": "true",
                },
                timeout=_REQUEST_TIMEOUT,
                headers={"User-Agent": "panda-trading-bot/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            headlines = []
            for item in results[:_MAX_HEADLINES]:
                title = str(item.get("title", "")).strip()
                if title:
                    # Sanitise: strip non-printable chars, truncate
                    title = "".join(c for c in title if c.isprintable())
                    headlines.append(title[:_MAX_HEADLINE_CHARS])
            logger.debug("[NewsFetcher] %s: fetched %d headlines", currency, len(headlines))
            return headlines
        except requests.exceptions.Timeout:
            logger.warning("[NewsFetcher] Timeout fetching news for %s", currency)
        except requests.exceptions.RequestException as exc:
            logger.warning("[NewsFetcher] Request error for %s: %s", currency, exc)
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("[NewsFetcher] Parse error for %s: %s", currency, exc)
        except Exception as exc:
            logger.warning("[NewsFetcher] Unexpected error for %s: %s", currency, exc)
        return []

    @staticmethod
    def _extract_currency(pair: str) -> str:
        """BTC/USDT:USDT → BTC"""
        return pair.split("/")[0].upper()
