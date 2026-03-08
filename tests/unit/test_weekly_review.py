"""Tests for weekly strategy review generation and decision tracking."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from custom_app.reviews import weekly


def test_summarise_closed_trades_computes_weekly_metrics():
    trades = [
        {
            "pair": "BTC/USDT:USDT",
            "close_profit_abs": 1.25,
            "open_date": "2026-03-01 00:00:00",
            "close_date": "2026-03-01 01:00:00",
            "exit_reason": "roi",
            "is_short": 0,
        },
        {
            "pair": "ETH/USDT:USDT",
            "close_profit_abs": -0.75,
            "open_date": "2026-03-02 00:00:00",
            "close_date": "2026-03-02 02:00:00",
            "exit_reason": "exit_signal",
            "is_short": 1,
        },
    ]

    summary = weekly._summarise_closed_trades(trades)

    assert summary["closed_trade_count"] == 2
    assert summary["weekly_pnl_abs"] == 0.5
    assert summary["wins"] == 1
    assert summary["losses"] == 1
    assert summary["win_rate"] == 0.5
    assert summary["avg_hold_minutes"] == 90.0
    assert summary["side_counts"] == {"long": 1, "short": 1}
    assert summary["pair_breakdown"][0]["pair"] == "BTC/USDT:USDT"


def test_fallback_review_recommends_research_when_losses_and_feed_failures():
    context = {
        "generated_at": "2026-03-08T00:00:00+00:00",
        "period_start": "2026-03-01T00:00:00+00:00",
        "period_end": "2026-03-08T00:00:00+00:00",
        "strategy_id": "GridTrendV2",
        "weekly_metrics": {
            "closed_trade_count": 5,
            "weekly_pnl_abs": -3.2,
        },
        "log_context": {
            "fear_greed": {"value": 12, "label": "Extreme Fear"},
            "oi_failures": 7,
            "liquidation_failures": 5,
            "llm_disabled": True,
        },
    }

    review = weekly._fallback_review(context, "llm unavailable")

    assert review["recommendation"] == "research_recommended"
    assert review["should_revalidate"] is True
    assert review["operator_action"] == "open_research_candidate"
    assert any("Fix broken OI/liquidation data feeds" in item for item in review["recommended_changes"])


def test_record_weekly_review_decision_updates_latest_review(tmp_path):
    review = {
        "review_id": "abc123",
        "generated_at": "2026-03-08T00:00:00+00:00",
        "period_start": "2026-03-01T00:00:00+00:00",
        "period_end": "2026-03-08T00:00:00+00:00",
        "strategy_id": "GridTrendV2",
        "model": "fallback-local",
        "recommendation": "research_recommended",
        "summary": "Research is warranted.",
        "recommended_changes": ["Test a tighter entry filter."],
        "operator_decision": None,
        "report_markdown": "# report",
        "context": {},
    }
    review_path = tmp_path / "20260308_GridTrendV2.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")

    updated = weekly.record_weekly_review_decision(
        "accept",
        notes="Run bounded research only.",
        review_dir=tmp_path,
        decided_at=datetime(2026, 3, 8, tzinfo=timezone.utc),
    )

    assert updated["operator_decision"]["decision"] == "accept"
    assert updated["operator_decision"]["action"] == "open_research_candidate"

    persisted = json.loads(review_path.read_text(encoding="utf-8"))
    assert persisted["operator_decision"]["notes"] == "Run bounded research only."
