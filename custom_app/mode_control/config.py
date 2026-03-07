"""Trading mode configuration and enums."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from enum import StrEnum


class TradingMode(StrEnum):
    """
    Operator-controlled trading mode.

    PAPER: dry-run mode, no real capital at risk (default).
    REAL:  live trading, requires all operator gates.
    """
    PAPER = "paper"
    REAL = "real"


@dataclass(frozen=True)
class TradingModeConfig:
    """
    Immutable snapshot of trading mode configuration.
    Resolved once at startup. Frozen to prevent mutation.
    """
    mode: TradingMode
    real_trading_acknowledged: bool
    operator_token_valid: bool
    dry_run: bool  # Freqtrade's dry_run flag — must match mode

    def __post_init__(self) -> None:
        if self.mode == TradingMode.REAL:
            if self.dry_run:
                raise ValueError(
                    "Inconsistent config: mode=real but dry_run=True. "
                    "Set dry_run=false in config for real trading."
                )
            if not self.real_trading_acknowledged:
                raise ValueError(
                    "Real trading requires REAL_TRADING_ACKNOWLEDGED=true"
                )
            if not self.operator_token_valid:
                raise ValueError(
                    "Real trading requires a valid OPERATOR_APPROVAL_TOKEN"
                )
        elif self.mode == TradingMode.PAPER:
            if not self.dry_run:
                raise ValueError(
                    "Inconsistent config: mode=paper but dry_run=False. "
                    "Set dry_run=true in config for paper trading."
                )

    @property
    def is_paper(self) -> bool:
        return self.mode == TradingMode.PAPER

    @property
    def is_real(self) -> bool:
        return self.mode == TradingMode.REAL

    def to_dict(self) -> dict:
        return {
            "mode": str(self.mode),
            "real_trading_acknowledged": self.real_trading_acknowledged,
            "operator_token_valid": self.operator_token_valid,
            "dry_run": self.dry_run,
        }


def resolve_trading_mode_from_env() -> TradingMode:
    """Read trading mode from environment. Defaults to PAPER (safe)."""
    raw = os.environ.get("TRADING_MODE", "paper").strip().lower()
    try:
        return TradingMode(raw)
    except ValueError:
        raise ValueError(
            f"Invalid TRADING_MODE='{raw}'. Must be 'paper' or 'real'."
        )


def check_real_trading_acknowledged() -> bool:
    """Check REAL_TRADING_ACKNOWLEDGED env var."""
    return os.environ.get("REAL_TRADING_ACKNOWLEDGED", "false").strip().lower() == "true"


def validate_operator_token() -> bool:
    """
    Validate OPERATOR_APPROVAL_TOKEN against OPERATOR_APPROVAL_TOKEN_HASH.
    Uses constant-time comparison to prevent timing attacks.
    """
    import hmac
    token = os.environ.get("OPERATOR_APPROVAL_TOKEN", "").strip()
    token_hash = os.environ.get("OPERATOR_APPROVAL_TOKEN_HASH", "").strip()
    if not token or not token_hash:
        return False
    computed = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return hmac.compare_digest(computed, token_hash)
