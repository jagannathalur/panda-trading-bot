"""
Audit Module — Append-only audit trail for all critical actions.

Public API:
    AuditLogger.get_instance() -> AuditLogger
    AuditEventType
    AuditEvent
"""

from custom_app.audit.logger import AuditLogger
from custom_app.audit.events import AuditEventType, AuditEvent

__all__ = ["AuditLogger", "AuditEventType", "AuditEvent"]
