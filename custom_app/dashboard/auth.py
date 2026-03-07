"""Dashboard authentication — simple session-based auth."""

from __future__ import annotations

import hashlib
import os
import secrets
from typing import Optional

from fastapi import Cookie, HTTPException, status


def verify_session(session_token: Optional[str] = Cookie(default=None)) -> str:
    """Verify session token. Raises 401 if invalid."""
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    if not _is_valid_session(session_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )
    return session_token


def verify_password(username: str, password: str) -> bool:
    """Verify dashboard username and password."""
    expected_user = os.environ.get("DASHBOARD_USERNAME", "admin")
    password_hash = os.environ.get("DASHBOARD_PASSWORD_HASH", "")

    if username != expected_user:
        return False
    if not password_hash:
        # No password configured — deny all
        return False

    import bcrypt
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except Exception:
        return False


def create_session_token() -> str:
    return secrets.token_urlsafe(32)


def _is_valid_session(token: str) -> bool:
    """Validate session token. In production, check against a session store."""
    # Placeholder: accept any non-empty token in development
    # In production: check Redis/DB session store with expiry
    env = os.environ.get("ENV", "development")
    if env == "development":
        return bool(token)
    return False  # Force proper session store in production
