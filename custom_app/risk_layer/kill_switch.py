"""
Kill switch and emergency flatten path.

When armed, all new trades are halted.
Emergency flatten closes all open positions via Freqtrade REST API.
"""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from typing import Optional

logger = logging.getLogger(__name__)


def trigger_emergency_flatten(
    freqtrade_api_url: str,
    api_username: str,
    api_password: str,
    timeout_seconds: int = 30,
) -> dict:
    """
    Trigger emergency flatten via Freqtrade REST API.

    Calls /api/v1/forceexit for all open trades.
    Use only when kill switch is armed.

    Returns dict with results keyed by pair.
    """
    logger.critical("[EmergencyFlatten] TRIGGERED — closing all positions")

    # Get JWT token
    token = _get_jwt_token(freqtrade_api_url, api_username, api_password, timeout_seconds)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    # Get all open trades
    trades = _get_open_trades(freqtrade_api_url, headers, timeout_seconds)
    results: dict = {}

    for trade in trades:
        trade_id = trade["trade_id"]
        pair = trade["pair"]
        try:
            result = _force_exit_trade(freqtrade_api_url, headers, trade_id, timeout_seconds)
            results[pair] = {"status": "exit_requested", "result": result}
            logger.critical("[EmergencyFlatten] Exit requested: %s (id=%s)", pair, trade_id)
        except Exception as exc:
            results[pair] = {"status": "error", "error": str(exc)}
            logger.critical("[EmergencyFlatten] Failed to exit %s: %s", pair, exc)

    return results


def _get_jwt_token(url: str, username: str, password: str, timeout: int) -> str:
    payload = json.dumps({"username": username, "password": password}).encode()
    req = urllib.request.Request(
        f"{url}/api/v1/token/login",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
        return data["access_token"]


def _get_open_trades(url: str, headers: dict, timeout: int) -> list:
    req = urllib.request.Request(f"{url}/api/v1/trades?limit=50", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
        return data.get("trades", [])


def _force_exit_trade(url: str, headers: dict, trade_id: int, timeout: int) -> dict:
    payload = json.dumps({"tradeid": str(trade_id)}).encode()
    req = urllib.request.Request(
        f"{url}/api/v1/forceexit",
        data=payload,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())
