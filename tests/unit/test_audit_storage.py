"""Tests for audit storage query/export helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from custom_app.audit.events import AuditEventType
from custom_app.audit.storage import export_audit_log_json, query_audit_log


def _event(ts: str, actor: str, event_type: str = "startup.mode_set") -> dict:
    return {
        "timestamp": ts,
        "event_type": event_type,
        "actor": actor,
        "action": "test",
        "outcome": "recorded",
    }


class TestQueryAuditLog:
    def test_returns_most_recent_events_first(self, tmp_path):
        log_path = tmp_path / "audit.log"
        events = [
            _event("2026-03-08T00:00:00+00:00", "oldest"),
            _event("2026-03-08T01:00:00+00:00", "middle"),
            _event("2026-03-08T02:00:00+00:00", "newest"),
        ]
        log_path.write_text("".join(json.dumps(evt) + "\n" for evt in events), encoding="utf-8")

        result = query_audit_log(str(log_path), limit=2)

        assert [evt["actor"] for evt in result] == ["newest", "middle"]

    def test_filters_by_event_type_and_since(self, tmp_path):
        log_path = tmp_path / "audit.log"
        events = [
            _event("2026-03-08T00:00:00+00:00", "skip", "risk.veto"),
            _event("2026-03-08T01:00:00+00:00", "keep", "risk.veto"),
            _event("2026-03-08T02:00:00+00:00", "other", "startup.mode_set"),
        ]
        log_path.write_text("".join(json.dumps(evt) + "\n" for evt in events), encoding="utf-8")

        result = query_audit_log(
            str(log_path),
            event_type=AuditEventType.RISK_VETO,
            since=datetime(2026, 3, 8, 0, 30, tzinfo=timezone.utc),
        )

        assert [evt["actor"] for evt in result] == ["keep"]


class TestExportAuditLogJson:
    def test_exports_filtered_events_to_json_array(self, tmp_path):
        log_path = tmp_path / "audit.log"
        out_path = tmp_path / "audit.json"
        events = [
            _event("2026-03-08T00:00:00+00:00", "one"),
            _event("2026-03-08T01:00:00+00:00", "two"),
        ]
        log_path.write_text("".join(json.dumps(evt) + "\n" for evt in events), encoding="utf-8")

        count = export_audit_log_json(str(log_path), str(out_path))

        assert count == 2
        assert json.loads(out_path.read_text(encoding="utf-8"))[0]["actor"] == "two"
