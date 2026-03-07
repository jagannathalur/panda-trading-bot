"""
Dashboard REST API endpoints.

IMPORTANT: The trading mode endpoint is READ-ONLY.
No endpoint in this API can change the trading mode.
Mode changes require operator restart with new environment.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


@router.get("/status")
async def get_status() -> dict:
    """
    Get overall bot status.
    Trading mode is returned as READ-ONLY information.
    """
    # Risk engine status
    risk_status = {}
    try:
        from custom_app.risk_layer import RiskEngine
        risk_status = RiskEngine.get_instance().get_status()
    except RuntimeError:
        risk_status = {"error": "Risk engine not initialized"}

    # Mode (read-only)
    mode_display = {}
    try:
        from custom_app.mode_control import ModeGuard
        mode_display = ModeGuard.get_instance().to_display_dict()
    except RuntimeError:
        mode_display = {"mode": "unknown", "read_only": True}

    return {
        "trading_mode": mode_display.get("mode", "unknown"),
        "mode_read_only": True,  # Always true — mode cannot be changed via API
        "risk": risk_status,
        "timestamp": _now_iso(),
    }


@router.get("/mode")
async def get_trading_mode() -> dict:
    """
    Get current trading mode. READ-ONLY.

    This endpoint returns mode information only.
    It does not accept POST/PUT/PATCH requests.
    Mode cannot be changed via the API.
    """
    try:
        from custom_app.mode_control import ModeGuard
        guard = ModeGuard.get_instance()
        return {
            **guard.to_display_dict(),
            "warning": "Trading mode is read-only. Changes require operator restart.",
        }
    except RuntimeError:
        return {"mode": "unknown", "read_only": True, "error": "ModeGuard not initialized"}


@router.get("/risk")
async def get_risk_status() -> dict:
    """Get current risk engine status."""
    try:
        from custom_app.risk_layer import RiskEngine
        return RiskEngine.get_instance().get_status()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Risk engine not initialized")


@router.get("/audit")
async def get_audit_log(
    limit: int = Query(default=50, le=500),
    event_type: Optional[str] = None,
) -> list:
    """Get recent audit log events."""
    try:
        from custom_app.audit import AuditLogger, AuditEventType
        log = AuditLogger.get_instance()
        et = AuditEventType(event_type) if event_type else None
        return log.read_events(limit=limit, event_type=et)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/promotion")
async def get_promotion_status() -> list:
    """Get strategy promotion status for all registered strategies."""
    try:
        from custom_app.promotion import StrategyRegistry
        registry = StrategyRegistry()
        return registry.all_statuses()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/no-alpha-thresholds")
async def get_no_alpha_thresholds() -> dict:
    """Get current no-alpha gate thresholds."""
    try:
        from custom_app.no_alpha import NoAlphaGate
        gate = NoAlphaGate()
        return gate.get_thresholds()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# Explicitly block any attempt to change mode via API
@router.post("/mode", include_in_schema=False)
@router.put("/mode", include_in_schema=False)
@router.patch("/mode", include_in_schema=False)
async def reject_mode_change():
    """
    This endpoint always returns 403.
    Trading mode cannot be changed via the API.
    Mode changes require operator restart.
    """
    raise HTTPException(
        status_code=403,
        detail=(
            "Trading mode cannot be changed via the API. "
            "Mode is operator-controlled and requires a restart with updated environment variables. "
            "See docs/operator_controls.md for the correct procedure."
        ),
    )


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
