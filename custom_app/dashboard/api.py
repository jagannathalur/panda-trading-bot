"""
Dashboard REST API endpoints.

IMPORTANT: The trading mode endpoint is READ-ONLY.
No endpoint in this API can change the trading mode.
Mode changes require operator restart with new environment.
"""

from __future__ import annotations

import os
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

# Freqtrade REST API connection
_FT_BASE = os.environ.get("FREQTRADE_API_URL", "http://127.0.0.1:8081/api/v1")
_FT_USER = os.environ.get("FREQTRADE_API_USER", "freqtrade")
_FT_PASS = os.environ.get("FREQTRADE_API_PASS", "change-me")
_FT_AUTH = (_FT_USER, _FT_PASS)
_FT_TIMEOUT = 5.0


async def _ft_get(path: str) -> dict | list:
    """Proxy a GET request to the Freqtrade API. Raises HTTPException on failure."""
    url = f"{_FT_BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=_FT_TIMEOUT) as client:
            resp = await client.get(url, auth=_FT_AUTH)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code,
                            detail=f"Freqtrade API error: {exc.response.text}")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Freqtrade API unreachable: {exc}")


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


@router.get("/risk-config")
async def get_risk_config() -> dict:
    """Get the current risk limit configuration (what the caps are set to)."""
    try:
        from custom_app.risk_layer.limits import RiskLimits
        limits = RiskLimits.from_env()
        return limits.to_dict()
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


@router.get("/bot-status")
async def get_bot_status() -> dict:
    """Get live Freqtrade bot status (strategy, state, pair count)."""
    try:
        cfg = await _ft_get("/show_config")
        return {
            "strategy": cfg.get("strategy", "unknown"),
            "state": cfg.get("state", "unknown"),
            "dry_run": cfg.get("dry_run", True),
            "timeframe": cfg.get("timeframe", ""),
            "pair_count": len(cfg.get("available_pairs", [])),
        }
    except HTTPException:
        return {"strategy": "unknown", "state": "unreachable", "dry_run": True}


@router.get("/pnl")
async def get_pnl() -> dict:
    """Get profit/loss summary from Freqtrade (all-time + open trades)."""
    profit = await _ft_get("/profit")
    open_trades = await _ft_get("/status")

    unrealized = sum(t.get("profit_abs", 0) for t in open_trades) if isinstance(open_trades, list) else 0.0
    total_fees = sum(
        t.get("fee_open_cost", 0) + t.get("fee_close_cost", 0)
        for t in open_trades
    ) if isinstance(open_trades, list) else 0.0

    return {
        "profit_closed_abs": profit.get("profit_closed_coin", 0.0),
        "profit_all_abs": profit.get("profit_all_coin", 0.0),
        "profit_closed_pct": profit.get("profit_closed_percent", 0.0),
        "trade_count": profit.get("trade_count", 0),
        "closed_trade_count": profit.get("closed_trade_count", 0),
        "winning_trades": profit.get("winning_trades", 0),
        "losing_trades": profit.get("losing_trades", 0),
        "winrate": profit.get("winrate", 0.0),
        "avg_duration": profit.get("avg_duration", "—"),
        "best_pair": profit.get("best_pair", "—"),
        "sharpe": profit.get("sharpe", 0.0),
        "unrealized_abs": unrealized,
        "open_trade_count": len(open_trades) if isinstance(open_trades, list) else 0,
        "timestamp": _now_iso(),
    }


@router.get("/trades")
async def get_trades(limit: int = Query(default=20, le=100)) -> list:
    """Get recent closed trades from Freqtrade."""
    result = await _ft_get(f"/trades?limit={limit}")
    trades = result.get("trades", result) if isinstance(result, dict) else result
    if not isinstance(trades, list):
        return []
    return [
        {
            "id": t.get("trade_id"),
            "pair": t.get("pair"),
            "side": "short" if t.get("is_short") else "long",
            "open_date": t.get("open_date", ""),
            "close_date": t.get("close_date", ""),
            "profit_abs": t.get("profit_abs", 0.0),
            "profit_pct": t.get("profit_pct", 0.0),
            "exit_reason": t.get("exit_reason", ""),
            "strategy": t.get("strategy", ""),
        }
        for t in trades
    ]


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
