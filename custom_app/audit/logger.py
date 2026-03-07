"""
AuditLogger — append-only, thread-safe audit trail.

Format: JSON-Lines (one JSON object per line).
Each write is fsynced for durability.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Optional

from custom_app.audit.events import AuditEvent, AuditEventType

logger = logging.getLogger(__name__)


class AuditLogger:
    """Append-only audit logger. Singleton. Thread-safe."""

    _instance: Optional["AuditLogger"] = None
    _class_lock: threading.Lock = threading.Lock()

    def __init__(self, log_path: Optional[str] = None) -> None:
        self._log_path = Path(
            log_path or os.environ.get("AUDIT_LOG_PATH", "./data/audit.log")
        )
        self._write_lock = threading.Lock()
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("[AuditLogger] Log path: %s", self._log_path)

    @classmethod
    def initialize(cls, log_path: Optional[str] = None) -> "AuditLogger":
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = cls(log_path)
            return cls._instance

    @classmethod
    def get_instance(cls) -> "AuditLogger":
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def _reset_for_testing(cls) -> None:
        with cls._class_lock:
            cls._instance = None

    def log_event(
        self,
        event_type: AuditEventType,
        actor: str,
        action: str,
        details: Optional[dict[str, Any]] = None,
        before_state: Optional[dict] = None,
        after_state: Optional[dict] = None,
        outcome: str = "recorded",
    ) -> AuditEvent:
        """Write an audit event. Thread-safe. Append-only."""
        event = AuditEvent(
            event_type=event_type,
            actor=actor,
            action=action,
            details=details or {},
            before_state=before_state,
            after_state=after_state,
            outcome=outcome,
        )
        self._write(event)
        return event

    def _write(self, event: AuditEvent) -> None:
        line = json.dumps(event.to_dict(), ensure_ascii=False, default=str)
        with self._write_lock:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())

    def read_events(
        self,
        limit: int = 100,
        event_type: Optional[AuditEventType] = None,
    ) -> list[dict]:
        """Read recent audit events for dashboard display."""
        if not self._log_path.exists():
            return []
        events = []
        with open(self._log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                    if event_type is None or evt.get("event_type") == str(event_type):
                        events.append(evt)
                except json.JSONDecodeError:
                    logger.warning("[AuditLogger] Skipping malformed audit line")
        return events[-limit:]
