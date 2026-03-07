"""
MetricsCollector — collects and exposes Prometheus metrics for Panda Trading Bot.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from prometheus_client import (
        Counter,
        Gauge,
        Histogram,
        CollectorRegistry,
        generate_latest,
        CONTENT_TYPE_LATEST,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning("[Metrics] prometheus_client not installed. Metrics disabled.")


class MetricsCollector:
    """Prometheus metrics for the Panda Trading Bot platform."""

    def __init__(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            return

        # Trading mode (0 = paper, 1 = real)
        self.trading_mode = Gauge("panda_trading_mode", "Trading mode (0=paper, 1=real)")
        self.trading_mode.set(0)  # Default paper

        # Kill switch
        self.kill_switch_active = Gauge("panda_kill_switch_active", "Kill switch state (0=disarmed, 1=armed)")

        # PnL
        self.daily_pnl_usdt = Gauge("panda_daily_pnl_usdt", "Daily PnL in USDT")
        self.cumulative_pnl_usdt = Gauge("panda_cumulative_pnl_usdt", "Cumulative PnL in USDT")
        self.fees_paid_usdt = Gauge("panda_fees_paid_usdt", "Total fees paid in USDT")

        # Risk
        self.drawdown_pct = Gauge("panda_drawdown_pct", "Current drawdown %")
        self.total_exposure_pct = Gauge("panda_total_exposure_pct", "Total portfolio exposure %")
        self.open_trades = Gauge("panda_open_trades", "Number of open trades")
        self.daily_loss_pct = Gauge("panda_daily_loss_pct", "Daily loss as % of equity")

        # Execution quality
        self.fill_ratio = Gauge("panda_fill_ratio", "Order fill ratio (0-1)")
        self.order_rejection_rate = Gauge("panda_order_rejection_rate", "Order rejection rate (0-1)")
        self.order_latency_ms = Histogram(
            "panda_order_latency_ms", "Order submission latency in ms",
            buckets=[10, 25, 50, 100, 250, 500, 1000, 2500]
        )

        # No-alpha gate
        self.no_alpha_blocks_total = Counter("panda_no_alpha_blocks_total", "Total no-alpha gate blocks")
        self.no_alpha_passes_total = Counter("panda_no_alpha_passes_total", "Total no-alpha gate passes")

        # Risk vetoes
        self.risk_vetoes_total = Counter("panda_risk_vetoes_total", "Total risk vetoes", ["check_name"])

        # Drift
        self.live_vs_backtest_drift_pct = Gauge("panda_live_vs_backtest_drift_pct", "Live vs backtest drift %")
        self.live_vs_paper_drift_pct = Gauge("panda_live_vs_paper_drift_pct", "Live vs paper drift %")

        # Promotion
        self.promotion_stage = Gauge(
            "panda_promotion_stage", "Strategy promotion stage",
            ["strategy_id"]
        )
        self.artifact_age_hours = Gauge(
            "panda_artifact_age_hours", "Age of promotion artifact in hours",
            ["strategy_id"]
        )

    def record_risk_veto(self, check_name: str) -> None:
        if PROMETHEUS_AVAILABLE:
            self.risk_vetoes_total.labels(check_name=check_name).inc()

    def record_no_alpha_block(self) -> None:
        if PROMETHEUS_AVAILABLE:
            self.no_alpha_blocks_total.inc()

    def record_no_alpha_pass(self) -> None:
        if PROMETHEUS_AVAILABLE:
            self.no_alpha_passes_total.inc()

    def update_risk_state(self, drawdown: float, exposure: float, open_trades: int) -> None:
        if PROMETHEUS_AVAILABLE:
            self.drawdown_pct.set(drawdown)
            self.total_exposure_pct.set(exposure)
            self.open_trades.set(open_trades)
