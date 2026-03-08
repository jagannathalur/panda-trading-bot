"""
MarketMicrostructure — Bybit public API signals.

Fetches real-time market data every 30 seconds:
  - Open interest (position trend, crowding detection)
  - Recent liquidations (cascade detection, split by long/short side)
  - Orderbook imbalance (immediate buying/selling pressure)

Liquidation side semantics (Bybit convention):
  side=="Sell"  → long position liquidated (exchange sold to close the long)
  side=="Buy"   → short position liquidated (exchange bought to close the short)

All endpoints are public — no API key required.
Fail-open on errors: returns None so callers can skip checks gracefully.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_BYBIT_BASE = "https://api.bybit.com/v5/market"
_REQUEST_TIMEOUT = 5

# Hard thresholds — single source of truth, imported by macro_collector and strategy
LIQ_CASCADE_USD = 5_000_000   # $5M liquidated in 5 min = cascade
OI_DECLINE_PCT  = -5.0         # OI dropped >5% = weakening long conviction
OI_SURGE_PCT    = 20.0         # OI surged >20% = crowded trade (block short, halve stake)
OB_BID_DOMINATED = 0.65        # imbalance > 0.65 = strong buy pressure
OB_ASK_DOMINATED = 0.35        # imbalance < 0.35 = strong sell pressure


@dataclass(frozen=True)
class OIData:
    symbol: str
    open_interest_usd: float
    prev_open_interest_usd: float
    oi_change_pct: float              # (current - prev) / prev * 100

    @property
    def is_declining(self) -> bool:
        return self.oi_change_pct < OI_DECLINE_PCT

    @property
    def is_crowded(self) -> bool:
        return self.oi_change_pct > OI_SURGE_PCT


@dataclass(frozen=True)
class LiqData:
    symbol: str
    liq_volume_5min_usd: float        # total (long + short)
    liq_count_5min: int
    liq_long_usd: float = 0.0         # long positions liquidated (side=="Sell")
    liq_short_usd: float = 0.0        # short positions liquidated (side=="Buy")

    @property
    def is_cascade(self) -> bool:
        """Total liquidation volume exceeded threshold."""
        return self.liq_volume_5min_usd >= LIQ_CASCADE_USD

    @property
    def is_long_cascade(self) -> bool:
        """Long positions cascading — sustained sell pressure, block new longs."""
        return self.liq_long_usd >= LIQ_CASCADE_USD

    @property
    def is_short_cascade(self) -> bool:
        """Short positions cascading (squeeze) — sustained buy pressure, block new shorts."""
        return self.liq_short_usd >= LIQ_CASCADE_USD


@dataclass(frozen=True)
class OrderbookData:
    symbol: str
    imbalance: float          # 0 (all asks) → 1 (all bids), 0.5 = neutral

    @property
    def bid_dominated(self) -> bool:
        return self.imbalance > OB_BID_DOMINATED

    @property
    def ask_dominated(self) -> bool:
        return self.imbalance < OB_ASK_DOMINATED


def pair_to_symbol(pair: str) -> Optional[str]:
    """BTC/USDT:USDT → BTCUSDT. Spot pair (no ':') → None."""
    if ":" not in pair:
        return None
    base, rest = pair.split("/")
    quote = rest.split(":")[0]
    return f"{base}{quote}"


def fetch_open_interest(symbol: str) -> Optional[OIData]:
    """
    Fetch current and previous open interest from Bybit.
    Returns None on any failure (fail-open).
    """
    try:
        resp = requests.get(
            f"{_BYBIT_BASE}/open-interest",
            params={
                "category": "linear",
                "symbol": symbol,
                "intervalTime": "5min",
                "limit": "2",
            },
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        entries = resp.json().get("result", {}).get("list", [])
        if not entries:
            return None

        current_oi = float(entries[0]["openInterestValue"])
        prev_oi = float(entries[1]["openInterestValue"]) if len(entries) > 1 else current_oi
        oi_change_pct = ((current_oi - prev_oi) / prev_oi * 100.0) if prev_oi > 0 else 0.0

        return OIData(
            symbol=symbol,
            open_interest_usd=current_oi,
            prev_open_interest_usd=prev_oi,
            oi_change_pct=round(oi_change_pct, 2),
        )
    except Exception as exc:
        logger.debug("[MarketMicro] OI fetch failed for %s: %s", symbol, exc)
        return None


def fetch_liquidations(symbol: str, window_ms: int = 300_000) -> Optional[LiqData]:
    """
    Fetch recent liquidation records from Bybit within the given time window.
    window_ms: look-back in milliseconds (default 5 min = 300,000 ms).
    Returns None on failure.
    """
    try:
        resp = requests.get(
            f"{_BYBIT_BASE}/liq-records",
            params={"category": "linear", "symbol": symbol, "limit": "200"},
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        records = resp.json().get("result", {}).get("list", [])

        cutoff_ms = int(time.time() * 1000) - window_ms
        recent = [r for r in records if int(r.get("updatedTime", 0)) >= cutoff_ms]

        total_usd = 0.0
        long_usd = 0.0    # side=="Sell" → long position liquidated
        short_usd = 0.0   # side=="Buy"  → short position liquidated
        for r in recent:
            value = float(r.get("size", 0)) * float(r.get("price", 0))
            total_usd += value
            if r.get("side", "") == "Sell":
                long_usd += value
            else:
                short_usd += value

        return LiqData(
            symbol=symbol,
            liq_volume_5min_usd=round(total_usd, 2),
            liq_count_5min=len(recent),
            liq_long_usd=round(long_usd, 2),
            liq_short_usd=round(short_usd, 2),
        )
    except Exception as exc:
        logger.debug("[MarketMicro] Liquidation fetch failed for %s: %s", symbol, exc)
        return None


def fetch_orderbook_imbalance(symbol: str) -> Optional[OrderbookData]:
    """
    Fetch top-5 orderbook and compute bid volume / total volume.
    0.5 = balanced, >0.65 = bids dominating (bullish pressure),
    <0.35 = asks dominating (bearish pressure).
    Returns None on failure.
    """
    try:
        resp = requests.get(
            f"{_BYBIT_BASE}/orderbook",
            params={"category": "linear", "symbol": symbol, "limit": "5"},
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        result = resp.json().get("result", {})
        bids = result.get("b", [])
        asks = result.get("a", [])

        bid_vol = sum(float(b[1]) for b in bids)
        ask_vol = sum(float(a[1]) for a in asks)
        total = bid_vol + ask_vol
        if total <= 0:
            return None

        return OrderbookData(symbol=symbol, imbalance=round(bid_vol / total, 3))
    except Exception as exc:
        logger.debug("[MarketMicro] Orderbook fetch failed for %s: %s", symbol, exc)
        return None
