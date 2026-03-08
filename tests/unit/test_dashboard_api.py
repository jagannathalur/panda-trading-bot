"""Tests for dashboard API configuration wiring."""

from __future__ import annotations

import asyncio
import importlib


def test_dashboard_uses_project_standard_freqtrade_env_names(monkeypatch):
    monkeypatch.setenv("FREQTRADE_API_USERNAME", "project-user")
    monkeypatch.setenv("FREQTRADE_API_PASSWORD", "project-pass")
    monkeypatch.delenv("FREQTRADE_API_USER", raising=False)
    monkeypatch.delenv("FREQTRADE_API_PASS", raising=False)

    from custom_app.dashboard import api as dashboard_api

    dashboard_api = importlib.reload(dashboard_api)

    assert dashboard_api._FT_AUTH == ("project-user", "project-pass")


def test_dashboard_falls_back_to_legacy_env_names(monkeypatch):
    monkeypatch.delenv("FREQTRADE_API_USERNAME", raising=False)
    monkeypatch.delenv("FREQTRADE_API_PASSWORD", raising=False)
    monkeypatch.setenv("FREQTRADE_API_USER", "legacy-user")
    monkeypatch.setenv("FREQTRADE_API_PASS", "legacy-pass")

    from custom_app.dashboard import api as dashboard_api

    dashboard_api = importlib.reload(dashboard_api)

    assert dashboard_api._FT_AUTH == ("legacy-user", "legacy-pass")


def test_weekly_review_endpoint_returns_placeholder_when_no_review(monkeypatch):
    from custom_app.dashboard import api as dashboard_api

    dashboard_api = importlib.reload(dashboard_api)
    monkeypatch.setattr(
        "custom_app.reviews.load_latest_weekly_review",
        lambda: None,
    )

    result = asyncio.run(dashboard_api.get_weekly_review())

    assert result["status"] == "unavailable"
    assert result["recommendation"] == "none"
