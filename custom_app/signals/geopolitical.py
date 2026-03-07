"""
GeopoliticalGate — GDELT-based geopolitical risk scoring.

Uses the GDELT 2.0 Document API (free, no auth, updated every ~15 min).
Queries for destabilizing global events and computes a risk score 0.0–1.0.

Score interpretation:
  0.0 – 0.3  calm
  0.3 – 0.5  elevated
  0.5 – 0.7  high
  0.7 – 1.0  crisis → hard block all trades

Fail-open: returns score=0.0 on any API failure.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
_CACHE_TTL = 15 * 60       # 15 minutes (GDELT updates ~every 15 min)
_REQUEST_TIMEOUT = 10

# GDELT query — topics relevant to crypto market macro risk
_RISK_QUERY = (
    "war OR conflict OR sanctions OR nuclear OR \"military attack\" "
    "OR \"financial crisis\" OR \"market crash\" OR \"exchange collapse\" "
    "OR \"central bank\" OR inflation OR recession"
)

# Calibration constants
# ~15 articles in 15 min at neutral tone = "normal" background
_BASELINE_ARTICLE_COUNT = 15
# Count producing risk score ≈ 0.9 at neutral tone
_HIGH_RISK_COUNT = 60


@dataclass(frozen=True)
class GeopoliticalRisk:
    score: float          # 0.0 (calm) to 1.0 (crisis)
    article_count: int    # raw GDELT article count in last 15 min
    avg_tone: float       # average GDELT tone (-100=neg, +100=pos)
    summary: str          # human-readable label


def _risk_score(article_count: int, avg_tone: float) -> float:
    """
    Compute 0–1 risk score from GDELT article count + average tone.
    More articles × more negative tone = higher risk.
    """
    # Tone multiplier: negative tone amplifies risk
    tone_factor = max(0.0, -avg_tone / 20.0)
    effective_count = article_count * (1.0 + tone_factor)

    # Sigmoid scaled so baseline → ~0.3, high_risk_count → ~0.9
    x = (effective_count - _BASELINE_ARTICLE_COUNT) / max(1, _HIGH_RISK_COUNT / 4)
    score = 1.0 / (1.0 + math.exp(-x))
    return round(min(1.0, max(0.0, score)), 3)


def _label(score: float) -> str:
    if score < 0.3:
        return "calm"
    if score < 0.5:
        return "elevated"
    if score < 0.7:
        return "high"
    return "crisis"


class GeopoliticalGate:
    """
    GDELT geopolitical risk gate.
    Cache is per-instance (15-min TTL). One instance per process is sufficient.
    Fail-open: returns score=0.0 on API failure.
    """

    def __init__(self) -> None:
        self._cache: Optional[tuple[float, GeopoliticalRisk]] = None

    def get_risk(self) -> GeopoliticalRisk:
        """Return current geopolitical risk (cached 15 min)."""
        now = time.monotonic()
        if self._cache is not None:
            fetch_time, cached = self._cache
            if now - fetch_time < _CACHE_TTL:
                return cached

        risk = self._fetch()
        self._cache = (now, risk)
        return risk

    def _fetch(self) -> GeopoliticalRisk:
        try:
            resp = requests.get(
                _GDELT_DOC_URL,
                params={
                    "query": _RISK_QUERY,
                    "mode": "artlist",
                    "format": "json",
                    "maxrecords": "75",
                    "timespan": "15min",
                    "sourcelang": "eng",
                },
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            articles = data.get("articles") or []

            if not articles:
                return GeopoliticalRisk(
                    score=0.1, article_count=0, avg_tone=0.0,
                    summary="calm (no recent articles)"
                )

            count = len(articles)
            tones: list[float] = []
            for art in articles:
                tone_str = str(art.get("tone", "") or "")
                if tone_str:
                    try:
                        tones.append(float(tone_str.split(",")[0]))
                    except (ValueError, IndexError):
                        pass

            avg_tone = sum(tones) / len(tones) if tones else 0.0
            score = _risk_score(count, avg_tone)
            summary = f"{_label(score)} ({count} articles, tone={avg_tone:.1f})"

            logger.info("[GeoPolitical] Score=%.2f — %s", score, summary)
            return GeopoliticalRisk(score=score, article_count=count, avg_tone=avg_tone, summary=summary)

        except requests.RequestException as exc:
            logger.warning("[GeoPolitical] GDELT request failed: %s — fail-open (0.0)", exc)
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("[GeoPolitical] GDELT parse error: %s — fail-open (0.0)", exc)
        except Exception as exc:
            logger.warning("[GeoPolitical] Unexpected error: %s — fail-open (0.0)", exc)

        return GeopoliticalRisk(
            score=0.0, article_count=0, avg_tone=0.0,
            summary="unavailable (fail-open)"
        )
