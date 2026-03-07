"""Audit storage utilities — querying and exporting audit logs."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from custom_app.audit.events import AuditEventType


def query_audit_log(
    log_path: str,
    event_type: Optional[AuditEventType] = None,
    actor: Optional[str] = None,
    since: Optional[datetime] = None,
    limit: int = 500,
) -> list[dict]:
    """Query the audit log with optional filters. Returns most recent first."""
    path = Path(log_path)
    if not path.exists():
        return []

    results = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event_type and evt.get("event_type") != str(event_type):
                continue
            if actor and evt.get("actor") != actor:
                continue
            if since:
                try:
                    evt_time = datetime.fromisoformat(evt.get("timestamp", ""))
                    if evt_time < since:
                        continue
                except ValueError:
                    continue
            results.append(evt)

    return list(reversed(results))[-limit:]


def export_audit_log_json(log_path: str, output_path: str) -> int:
    """Export audit log to a JSON array file. Returns event count."""
    events = query_audit_log(log_path, limit=100_000)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2, default=str)
    return len(events)
