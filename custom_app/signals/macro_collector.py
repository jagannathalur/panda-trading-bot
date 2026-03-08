"""
MacroSignalCollector — 30-second background polling loop.

Collects macro signals from free public APIs and pre-computes a
MacroSignalState snapshot every 30 seconds. Strategy callbacks read
from this pre-computed state with zero additional API latency.

Data collected per cycle:
  Every 30s  : Bybit open interest, liquidations (with side), orderbook (per pair)
  Every 6h   : Fear & Greed Index (Alternative.me)
  Every 15m  : GDELT geopolitical risk score

Hard blocks (evaluated in confirm_trade_entry):
  - Long liq cascade     : long positions >$5M liquidated in 5min → block longs
  - Short liq cascade    : short positions >$5M liquidated in 5min → block shorts
  - OI divergence        : OI declining when entering long → block long
                           OI surging when entering short → block short
  - Extreme fear (F&G<15): block longs
  - Extreme greed (F&G>85): block shorts
  - Geopolitical spike   : GDELT risk > 0.8 → block both sides

Liquidation side semantics:
  Long cascade  = longs being wiped (sell pressure) → block new longs
  Short cascade = shorts being squeezed (buy pressure) → block new shorts
  Previously: total cascade blocked BOTH sides regardless of which side was flushing.
  Now: side-specific — a short squeeze no longer blocks new longs.

Thread-safety: MacroSignalState reference replaced atomically under lock.
Fail-open: if a data source is unavailable, checks using that source are skipped.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests

from custom_app.signals.market_microstructure import (
    OIData, LiqData, OrderbookData,
    fetch_open_interest, fetch_liquidations, fetch_orderbook_imbalance,
    pair_to_symbol,
)
from custom_app.signals.geopolitical import GeopoliticalGate, GeopoliticalRisk

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 30
_FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1"
_FEAR_GREED_CACHE_TTL = 6 * 60 * 60   # 6 hours (updates daily)
_FEAR_GREED_REQUEST_TIMEOUT = 5

# Block thresholds
_FEAR_BLOCK_LONG_THRESHOLD = 15         # F&G < 15 = Extreme Fear → no longs
_GREED_BLOCK_SHORT_THRESHOLD = 85       # F&G > 85 = Extreme Greed → no shorts
_GEO_SPIKE_THRESHOLD = 0.8             # GDELT risk > 0.8 → block all


_LIQ_CASCADE_USD = 5_000_000  # $5M liquidated in 5 min = cascade


@dataclass(frozen=True)
class PairMicroData:
    """Per-pair microstructure snapshot."""
    symbol: str
    oi_usd: float = 0.0
    oi_change_pct: float = 0.0         # vs previous reading
    liq_volume_5min_usd: float = 0.0   # total liquidations
    liq_count_5min: int = 0
    liq_long_usd: float = 0.0          # long positions liquidated (sell pressure)
    liq_short_usd: float = 0.0         # short positions liquidated (buy/squeeze pressure)
    orderbook_imbalance: float = 0.5   # 0=asks, 1=bids, 0.5=neutral


@dataclass
class MacroSignalState:
    """
    Immutable-by-convention macro snapshot.
    Not frozen (dict field), but treated as read-only after creation.
    """
    pair_data: dict[str, PairMicroData] = field(default_factory=dict)
    fear_greed_value: int = 50           # 0-100 (50 = neutral/unknown)
    fear_greed_label: str = "Neutral"
    geo_risk_score: float = 0.0
    geo_risk_summary: str = "unknown"
    fetched_at: float = field(default_factory=time.monotonic)

    # ── Hard block checks ─────────────────────────────────────────────

    def is_liquidation_cascade(self, pair: str) -> bool:
        """Total liquidation volume exceeded threshold (used for LLM context)."""
        pd = self.pair_data.get(pair)
        return pd is not None and pd.liq_volume_5min_usd >= _LIQ_CASCADE_USD

    def is_long_liq_cascade(self, pair: str) -> bool:
        """Long positions cascading (sell pressure). Block new longs."""
        pd = self.pair_data.get(pair)
        return pd is not None and pd.liq_long_usd >= _LIQ_CASCADE_USD

    def is_short_liq_cascade(self, pair: str) -> bool:
        """Short positions cascading/squeezed (buy pressure). Block new shorts."""
        pd = self.pair_data.get(pair)
        return pd is not None and pd.liq_short_usd >= _LIQ_CASCADE_USD

    def is_oi_declining_long_block(self, pair: str) -> bool:
        """Block new longs when open interest is falling (longs closing)."""
        pd = self.pair_data.get(pair)
        return pd is not None and pd.oi_change_pct < -5.0

    def is_oi_surging_short_block(self, pair: str) -> bool:
        """Block new shorts when OI is surging (shorts getting crowded)."""
        pd = self.pair_data.get(pair)
        return pd is not None and pd.oi_change_pct > 20.0

    def blocks_long(self, pair: str) -> Optional[str]:
        """Return reason string if long should be blocked, else None."""
        if self.is_long_liq_cascade(pair):
            pd = self.pair_data.get(pair)
            vol = pd.liq_long_usd if pd else 0
            return f"long liquidation cascade ${vol:,.0f} in 5min — sell pressure"
        if self.fear_greed_value < _FEAR_BLOCK_LONG_THRESHOLD:
            return f"extreme fear (F&G={self.fear_greed_value})"
        if self.geo_risk_score > _GEO_SPIKE_THRESHOLD:
            return f"geopolitical crisis (score={self.geo_risk_score:.2f})"
        if self.is_oi_declining_long_block(pair):
            pd = self.pair_data.get(pair)
            chg = pd.oi_change_pct if pd else 0
            return f"OI declining {chg:.1f}% — weakening long conviction"
        return None

    def blocks_short(self, pair: str) -> Optional[str]:
        """Return reason string if short should be blocked, else None."""
        if self.is_short_liq_cascade(pair):
            pd = self.pair_data.get(pair)
            vol = pd.liq_short_usd if pd else 0
            return f"short liquidation cascade ${vol:,.0f} in 5min — squeeze pressure"
        if self.fear_greed_value > _GREED_BLOCK_SHORT_THRESHOLD:
            return f"extreme greed (F&G={self.fear_greed_value})"
        if self.geo_risk_score > _GEO_SPIKE_THRESHOLD:
            return f"geopolitical crisis (score={self.geo_risk_score:.2f})"
        if self.is_oi_surging_short_block(pair):
            pd = self.pair_data.get(pair)
            chg = pd.oi_change_pct if pd else 0
            return f"OI surging {chg:.1f}% — crowded short"
        return None

    def to_macro_context(self, pair: str) -> "MacroContext":
        pd = self.pair_data.get(pair)
        return MacroContext(
            fear_greed_value=self.fear_greed_value,
            fear_greed_label=self.fear_greed_label,
            geo_risk_score=self.geo_risk_score,
            geo_risk_summary=self.geo_risk_summary,
            liquidation_alert=self.is_liquidation_cascade(pair),
            oi_change_pct=pd.oi_change_pct if pd else 0.0,
            orderbook_imbalance=pd.orderbook_imbalance if pd else 0.5,
        )

    def age_seconds(self) -> float:
        return time.monotonic() - self.fetched_at


@dataclass(frozen=True)
class MacroContext:
    """Slim context passed to the LLM gate for prompt enrichment."""
    fear_greed_value: int
    fear_greed_label: str
    geo_risk_score: float
    geo_risk_summary: str
    liquidation_alert: bool
    oi_change_pct: float
    orderbook_imbalance: float


# Shared empty state — returned before first fetch completes
_EMPTY_STATE = MacroSignalState()


class MacroSignalCollector:
    """
    Singleton daemon thread that polls macro signals every 30 seconds.

    Usage:
        collector = MacroSignalCollector.get_instance()
        collector.start(["BTC/USDT:USDT", "ETH/USDT:USDT"])
        state = collector.get_state("BTC/USDT:USDT")
    """

    _instance: Optional["MacroSignalCollector"] = None
    _class_lock = threading.Lock()

    def __init__(self) -> None:
        self._state: MacroSignalState = _EMPTY_STATE
        self._state_lock = threading.Lock()
        self._pairs: list[str] = []
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._geo_gate = GeopoliticalGate()
        # Fear & Greed cache (separate from geo since TTL is 6h)
        self._fg_cache: Optional[tuple[float, int, str]] = None  # (fetch_time, value, label)

    @classmethod
    def get_instance(cls) -> "MacroSignalCollector":
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def _reset_for_testing(cls) -> None:
        with cls._class_lock:
            if cls._instance is not None:
                cls._instance._stop_event.set()
            cls._instance = None

    def start(self, pairs: list[str]) -> None:
        """Start the background polling thread. Safe to call multiple times."""
        with self._state_lock:
            self._pairs = list(pairs)

        if self._thread is not None and self._thread.is_alive():
            logger.debug("[MacroCollector] Already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="macro-collector",
            daemon=True,
        )
        self._thread.start()
        logger.info("[MacroCollector] Started — polling %d pairs every %ds",
                    len(pairs), _POLL_INTERVAL_SECONDS)

    def stop(self) -> None:
        """Signal the background thread to stop."""
        self._stop_event.set()

    def get_state(self, pair: str = "") -> MacroSignalState:
        """Return the latest macro state snapshot. Thread-safe."""
        with self._state_lock:
            return self._state

    # ── Background loop ───────────────────────────────────────────────

    def _run_loop(self) -> None:
        # Run first fetch immediately, then wait between cycles
        while not self._stop_event.is_set():
            try:
                self._fetch_cycle()
            except Exception as exc:
                logger.error("[MacroCollector] Cycle error: %s", exc)
            self._stop_event.wait(timeout=_POLL_INTERVAL_SECONDS)

    def _fetch_cycle(self) -> None:
        with self._state_lock:
            pairs = list(self._pairs)

        pair_data: dict[str, PairMicroData] = {}
        for pair in pairs:
            symbol = pair_to_symbol(pair)
            if not symbol:
                continue
            oi = fetch_open_interest(symbol)
            liq = fetch_liquidations(symbol)
            ob = fetch_orderbook_imbalance(symbol)
            pair_data[pair] = PairMicroData(
                symbol=symbol,
                oi_usd=oi.open_interest_usd if oi else 0.0,
                oi_change_pct=oi.oi_change_pct if oi else 0.0,
                liq_volume_5min_usd=liq.liq_volume_5min_usd if liq else 0.0,
                liq_count_5min=liq.liq_count_5min if liq else 0,
                liq_long_usd=liq.liq_long_usd if liq else 0.0,
                liq_short_usd=liq.liq_short_usd if liq else 0.0,
                orderbook_imbalance=ob.imbalance if ob else 0.5,
            )

        fg_value, fg_label = self._fetch_fear_greed()
        geo = self._geo_gate.get_risk()

        new_state = MacroSignalState(
            pair_data=pair_data,
            fear_greed_value=fg_value,
            fear_greed_label=fg_label,
            geo_risk_score=geo.score,
            geo_risk_summary=geo.summary,
            fetched_at=time.monotonic(),
        )

        with self._state_lock:
            self._state = new_state

        logger.debug(
            "[MacroCollector] Cycle done — F&G=%d (%s), Geo=%.2f, pairs=%d",
            fg_value, fg_label, geo.score, len(pair_data),
        )

        # Log any active hard blocks for visibility
        for pair, pd in pair_data.items():
            if pd.liq_volume_5min_usd > 1_000_000:
                logger.warning(
                    "[MacroCollector] High liquidations on %s: $%.0fM in 5min",
                    pair, pd.liq_volume_5min_usd / 1_000_000,
                )

    def _fetch_fear_greed(self) -> tuple[int, str]:
        """Fetch Fear & Greed index. Cached for 6 hours."""
        now = time.monotonic()
        if self._fg_cache is not None:
            fetch_time, value, label = self._fg_cache
            if now - fetch_time < _FEAR_GREED_CACHE_TTL:
                return value, label

        try:
            resp = requests.get(_FEAR_GREED_URL, timeout=_FEAR_GREED_REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json().get("data", [{}])
            if data:
                value = int(data[0]["value"])
                label = str(data[0]["value_classification"])
                self._fg_cache = (now, value, label)
                logger.info("[MacroCollector] Fear & Greed: %d (%s)", value, label)
                return value, label
        except Exception as exc:
            logger.warning("[MacroCollector] Fear & Greed fetch failed: %s", exc)

        # Return cached value if available (even if stale), else neutral
        if self._fg_cache is not None:
            _, v, l = self._fg_cache
            return v, l
        return 50, "Neutral"
