"""
Startup validation for trading mode.

Runs at process startup BEFORE Freqtrade's worker starts.
Validates mode, checks operator gates, writes audit log entry.
Aborts with sys.exit(1) if mode requirements are not met.
"""

from __future__ import annotations

import logging
import sys

from custom_app.mode_control.config import (
    TradingMode,
    TradingModeConfig,
    check_real_trading_acknowledged,
    resolve_trading_mode_from_env,
    validate_operator_token,
)
from custom_app.mode_control.guard import ModeGuard

logger = logging.getLogger(__name__)


def validate_startup_mode(dry_run_from_config: bool) -> TradingModeConfig:
    """
    Validate trading mode at startup. Called before Freqtrade worker starts.

    Parameters:
        dry_run_from_config: The dry_run value from Freqtrade config.

    Returns:
        Frozen TradingModeConfig if all checks pass.

    Raises:
        SystemExit(1): If mode requirements are not met.
    """
    logger.info("[Startup] Validating trading mode configuration...")

    try:
        mode = resolve_trading_mode_from_env()
    except ValueError as exc:
        logger.critical("[Startup] Invalid trading mode: %s", exc)
        sys.exit(1)

    acknowledged = check_real_trading_acknowledged()
    token_valid = validate_operator_token()

    if mode == TradingMode.REAL:
        _validate_real_mode_gates(acknowledged, token_valid, dry_run_from_config)

    try:
        config = TradingModeConfig(
            mode=mode,
            real_trading_acknowledged=acknowledged,
            operator_token_valid=token_valid,
            dry_run=dry_run_from_config,
        )
    except ValueError as exc:
        logger.critical("[Startup] Mode config validation failed: %s", exc)
        sys.exit(1)

    _write_startup_audit_entry(config)
    guard = ModeGuard.initialize(config)
    logger.info("[Startup] ModeGuard initialized: mode=%s", guard.current_mode)
    _log_startup_banner(config)
    return config


def _validate_real_mode_gates(
    acknowledged: bool,
    token_valid: bool,
    dry_run_from_config: bool,
) -> None:
    """Validate all gates for real trading. Exits on failure."""
    errors = []
    if not acknowledged:
        errors.append("REAL_TRADING_ACKNOWLEDGED must be 'true' in environment")
    if not token_valid:
        errors.append("OPERATOR_APPROVAL_TOKEN must match OPERATOR_APPROVAL_TOKEN_HASH")
    if dry_run_from_config:
        errors.append("dry_run must be false in config for real trading mode")

    if errors:
        logger.critical("[Startup] Real trading REJECTED. Missing requirements:")
        for i, err in enumerate(errors, 1):
            logger.critical("[Startup]   %d. %s", i, err)
        sys.exit(1)

    logger.info("[Startup] Real trading gates: ALL PASSED")


def _write_startup_audit_entry(config: TradingModeConfig) -> None:
    try:
        from custom_app.audit import AuditLogger, AuditEventType
        AuditLogger.get_instance().log_event(
            event_type=AuditEventType.STARTUP_MODE_SET,
            actor="operator",
            action=f"Bot started in {config.mode} mode",
            details=config.to_dict(),
        )
    except Exception as exc:
        logger.warning("[Startup] Failed to write audit log: %s", exc)
        if config.mode == TradingMode.REAL:
            logger.critical("[Startup] Audit log required for REAL mode. Aborting.")
            sys.exit(1)


def _log_startup_banner(config: TradingModeConfig) -> None:
    border = "=" * 60
    if config.is_real:
        logger.warning(border)
        logger.warning("  *** REAL TRADING MODE ACTIVE — REAL CAPITAL AT RISK ***")
        logger.warning("  Kill switch: ARMED | Risk engine: ACTIVE WITH VETO POWER")
        logger.warning(border)
    else:
        logger.info(border)
        logger.info("  PAPER TRADING MODE — No real capital at risk")
        logger.info("  All orders are simulated.")
        logger.info(border)
