"""
GridTrendV2 — Long + Short strategy with LLM sentiment gate.

Upgrades from V1:
  - can_short = True             (profit from both directions)
  - Trailing stoploss            (don't leave upside on table)
  - Funding rate gate            (avoids costly perpetual positions)
  - LLM sentiment gate           (Claude Haiku as final filter)
  - Volatility-aware sizing      (ATR scales position size)
  - 30s macro signal polling     (liquidations, OI, F&G, geopolitical)
  - MTF 15m EMA alignment        (blocks entries against the higher-timeframe trend)
  - Orderbook imbalance gate     (blocks entries into adverse order pressure)
  - Side-aware liq cascade       (long cascade ≠ short squeeze — handled separately)

Gate order (cheapest first — LLM is last):
  1. Technical signal (EMA crossover + RSI)
  2. Time filter (02:00–04:00 UTC blocked)
  3. MTF 15m EMA alignment (CPU only — fail-open)
  4. Macro hard blocks (side-aware liq cascade, F&G extreme, geo spike, OI divergence)
  5. Orderbook imbalance gate (free, already in macro state — no extra API call)
  6. Funding rate check (free Bybit API, cached 5 min)
  7. LLM sentiment (Claude Haiku, cached 15 min, ~$0.0004/call, enriched with macro)
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

# Add project root to path so custom_app is importable.
# APPEND (not insert) so installed packages (freqtrade) take precedence.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.append(_PROJECT_ROOT)

import pandas as pd
from pandas import DataFrame
import talib.abstract as ta

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter

logger = logging.getLogger(__name__)

# Import signal gates — degrade gracefully if unavailable
try:
    from custom_app.signals.funding_rate import FundingRateGate
    from custom_app.signals.llm_sentiment import LLMSentimentGate
    from custom_app.signals.news_fetcher import NewsFetcher
    from custom_app.signals.macro_collector import MacroSignalCollector
    from custom_app.signals.entry_filters import mtf_ema_aligned, orderbook_allows_entry
    from custom_app.signals.market_microstructure import OI_SURGE_PCT
    _SIGNALS_AVAILABLE = True
except ImportError:
    logger.warning("[GridTrendV2] custom_app.signals not available — running without LLM/funding gates")
    _SIGNALS_AVAILABLE = False
    OI_SURGE_PCT = 20.0  # fallback constant if signals module unavailable


class GridTrendV2(IStrategy):
    """
    EMA crossover long+short strategy with AI sentiment overlay.

    Entry (long):  EMA9 crosses above EMA21, RSI < 65, volume > avg
    Entry (short): EMA9 crosses below EMA21, RSI > 35, volume > avg
    Exit (long):   EMA9 crosses below EMA21, or RSI > 75
    Exit (short):  EMA9 crosses above EMA21, or RSI < 25

    Both entries additionally require:
      - Funding rate not adverse (perpetuals only)
      - Claude Haiku sentiment not opposed to direction
    """

    INTERFACE_VERSION = 3
    can_short = True

    # --- Trailing stoploss -------------------------------------------
    # Hard floor at -5% until trade reaches +2% profit.
    # After +2%, trail at 1.5% from the highest point reached.
    # This locks in gains while not getting stopped out by noise.
    stoploss = -0.05
    trailing_stop = True
    trailing_stop_positive = 0.015          # 1.5% trail from peak
    trailing_stop_positive_offset = 0.02   # activate after 2% profit
    trailing_only_offset_is_reached = True  # don't trail before offset

    # --- Strategy settings -------------------------------------------
    timeframe = "5m"
    startup_candle_count = 30  # need 21 for EMA21 + buffer
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    process_only_new_candles = True

    # ROI table — take profits progressively
    minimal_roi = {
        "0": 0.05,    # 5% anytime
        "30": 0.03,   # 3% after 30 min
        "60": 0.015,  # 1.5% after 1h
        "120": 0.005, # 0.5% after 2h (almost breakeven)
    }

    # --- Hyperopt parameters -----------------------------------------
    ema_fast = IntParameter(5, 20, default=9, space="buy", optimize=True)
    ema_slow = IntParameter(15, 50, default=21, space="buy", optimize=True)
    rsi_long_max = IntParameter(50, 70, default=65, space="buy", optimize=True)
    rsi_short_min = IntParameter(30, 55, default=35, space="buy", optimize=True)
    rsi_long_exit = IntParameter(65, 85, default=75, space="sell", optimize=True)
    rsi_short_exit = IntParameter(15, 40, default=25, space="sell", optimize=True)

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._funding_gate: Optional[FundingRateGate] = None
        self._sentiment_gate: Optional[LLMSentimentGate] = None
        self._news_fetcher: Optional[NewsFetcher] = None
        if _SIGNALS_AVAILABLE:
            self._funding_gate = FundingRateGate()
            self._sentiment_gate = LLMSentimentGate()
            self._news_fetcher = NewsFetcher()
            # Start 30-second background macro signal collector
            # (pairs populated on first confirm_trade_entry call via bot_start)
            MacroSignalCollector.get_instance().start([])
            logger.info("[GridTrendV2] LLM sentiment gate, funding rate gate, and macro collector initialised")
        else:
            logger.warning("[GridTrendV2] Signal gates unavailable — trading on technical signals only")

    def bot_start(self) -> None:
        """Called by Freqtrade after the pairlist is fully resolved.
        Use this to populate the macro collector with the actual pair list."""
        if _SIGNALS_AVAILABLE:
            pairs = self.dp.current_whitelist()
            MacroSignalCollector.get_instance().start(pairs)
            logger.info("[GridTrendV2] Macro collector updated with %d pairs: %s", len(pairs), pairs)

    # ------------------------------------------------------------------
    # Indicator computation
    # ------------------------------------------------------------------

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_fast"] = ta.EMA(dataframe["close"], timeperiod=self.ema_fast.value)
        dataframe["ema_slow"] = ta.EMA(dataframe["close"], timeperiod=self.ema_slow.value)
        dataframe["rsi"] = ta.RSI(dataframe["close"], timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe["high"], dataframe["low"], dataframe["close"], timeperiod=14)
        dataframe["volume_mean"] = dataframe["volume"].rolling(20).mean()
        return dataframe

    # ------------------------------------------------------------------
    # Entry signals
    # ------------------------------------------------------------------

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Long: EMA crossover upward, not overbought, above-average volume
        dataframe.loc[
            (
                (dataframe["ema_fast"] > dataframe["ema_slow"])
                & (dataframe["ema_fast"].shift(1) <= dataframe["ema_slow"].shift(1))
                & (dataframe["rsi"] < self.rsi_long_max.value)
                & (dataframe["volume"] > dataframe["volume_mean"])
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1

        # Short: EMA crossover downward, not oversold, above-average volume
        dataframe.loc[
            (
                (dataframe["ema_fast"] < dataframe["ema_slow"])
                & (dataframe["ema_fast"].shift(1) >= dataframe["ema_slow"].shift(1))
                & (dataframe["rsi"] > self.rsi_short_min.value)
                & (dataframe["volume"] > dataframe["volume_mean"])
                & (dataframe["volume"] > 0)
            ),
            "enter_short",
        ] = 1

        return dataframe

    # ------------------------------------------------------------------
    # Exit signals
    # ------------------------------------------------------------------

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Long exit: EMA crosses down, or overbought
        dataframe.loc[
            (
                (dataframe["ema_fast"] < dataframe["ema_slow"])
                & (dataframe["ema_fast"].shift(1) >= dataframe["ema_slow"].shift(1))
            )
            | (dataframe["rsi"] > self.rsi_long_exit.value),
            "exit_long",
        ] = 1

        # Short exit: EMA crosses up, or oversold
        dataframe.loc[
            (
                (dataframe["ema_fast"] > dataframe["ema_slow"])
                & (dataframe["ema_fast"].shift(1) <= dataframe["ema_slow"].shift(1))
            )
            | (dataframe["rsi"] < self.rsi_short_exit.value),
            "exit_short",
        ] = 1

        return dataframe

    # ------------------------------------------------------------------
    # Final gate: funding rate + LLM sentiment
    # Called by Freqtrade right before placing an order.
    # ------------------------------------------------------------------

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> bool:
        """
        Final pre-order gate. Runs AFTER technical signal, risk engine, and no-alpha gate.
        Checks (cheapest first):
          1. MTF 15m EMA alignment (CPU only — fail-open)
          2. Macro hard blocks (side-aware liq cascade, F&G extreme, geo spike, OI divergence)
          3. Orderbook imbalance gate (free, already in macro state)
          4. Funding rate (free, cached)
          5. LLM sentiment (Claude Haiku, cached 15 min, enriched with macro context)
        Returns False to silently cancel the order.
        """
        # 1. MTF 15m EMA alignment — block entries against the higher-timeframe trend
        if not self._check_mtf_ema(pair, side):
            return False

        # 2. Macro hard blocks (pre-computed by background thread — zero latency)
        macro_context = None
        if _SIGNALS_AVAILABLE:
            macro_state = MacroSignalCollector.get_instance().get_state(pair)
            block_reason = (
                macro_state.blocks_long(pair) if side == "long"
                else macro_state.blocks_short(pair)
            )
            if block_reason:
                logger.info(
                    "[GridTrendV2] Macro block: %s %s — %s",
                    side, pair, block_reason,
                )
                return False

            # 3. Orderbook imbalance gate (free — already in macro state, no extra API call)
            pair_micro = macro_state.pair_data.get(pair)
            if pair_micro is not None:
                if not orderbook_allows_entry(pair_micro.orderbook_imbalance, side):
                    logger.info(
                        "[GridTrendV2] Orderbook gate blocked %s %s (imbalance=%.2f)",
                        side, pair, pair_micro.orderbook_imbalance,
                    )
                    return False

            macro_context = macro_state.to_macro_context(pair)

        # 4. Funding rate gate (futures only — fast, free)
        if self._funding_gate is not None:
            if not self._funding_gate.check(pair, side):
                logger.info("[GridTrendV2] Funding rate blocked %s %s", side, pair)
                return False
            # Enrich macro_context with the rate (already cached by check above)
            if macro_context is not None:
                rate = self._funding_gate.get_last_rate(pair)
                if rate is not None:
                    from dataclasses import replace as _replace
                    macro_context = _replace(macro_context, funding_rate_pct=rate * 100)

        # 5. LLM sentiment gate (last — most expensive per call but rare)
        if self._sentiment_gate is not None and self._news_fetcher is not None:
            headlines = self._news_fetcher.fetch(pair)
            result = self._sentiment_gate.evaluate(pair, side, headlines, macro_context)

            logger.info(
                "[GridTrendV2] LLM sentiment for %s %s: %.2f (confidence=%.2f, source=%s) — %s",
                side, pair, result.sentiment, result.confidence,
                result.source, "ALLOWED" if result.allowed else "BLOCKED",
            )

            if not result.allowed:
                return False

        return True

    def _check_mtf_ema(self, pair: str, side: str) -> bool:
        """
        15m EMA trend alignment filter. Delegates to entry_filters.mtf_ema_aligned.
        Fail-open when 15m data is unavailable.
        """
        try:
            df_15m = self.dp.get_pair_dataframe(pair=pair, timeframe="15m")
        except Exception as exc:
            logger.debug("[GridTrendV2] MTF data fetch failed for %s: %s — fail-open", pair, exc)
            return True
        return mtf_ema_aligned(df_15m, self.ema_fast.value, self.ema_slow.value, side)

    # ------------------------------------------------------------------
    # Position sizing: ATR-based (scales down in high volatility)
    # ------------------------------------------------------------------

    def custom_stake_amount(
        self,
        current_time,
        current_rate: float,
        proposed_stake: float,
        min_stake: Optional[float],
        max_stake: float,
        leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        """
        Reduce stake in high-volatility conditions.
        Uses ATR relative to price: if ATR/price > 3%, use half stake.
        This protects against getting stopped out in choppy conditions.
        """
        dataframe, _ = self.dp.get_analyzed_dataframe(kwargs.get("pair", ""), self.timeframe)
        if dataframe is None or dataframe.empty:
            return proposed_stake

        last = dataframe.iloc[-1]
        atr = last.get("atr", 0)
        price = last.get("close", current_rate)

        stake = proposed_stake
        pair_str = kwargs.get("pair", "")

        if price > 0 and atr > 0:
            atr_pct = atr / price
            if atr_pct > 0.03:  # > 3% ATR = high volatility
                stake = stake * 0.5
                logger.info(
                    "[GridTrendV2] High volatility (ATR=%.2f%%) — stake reduced 50%% to %.2f",
                    atr_pct * 100, stake,
                )

        # Further reduce stake in crowded OI conditions
        if _SIGNALS_AVAILABLE and pair_str:
            macro_state = MacroSignalCollector.get_instance().get_state(pair_str)
            pd = macro_state.pair_data.get(pair_str)
            if pd is not None and pd.oi_change_pct > OI_SURGE_PCT:
                stake = stake * 0.5
                logger.info(
                    "[GridTrendV2] Crowded trade (OI +%.1f%%) — stake reduced 50%% to %.2f",
                    pd.oi_change_pct, stake,
                )

        if min_stake and stake < min_stake:
            return min_stake
        return stake
