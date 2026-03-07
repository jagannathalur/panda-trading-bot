"""Dashboard authentication — session-based auth with in-memory session store."""

from __future__ import annotations

import os
import secrets
import threading
import time
from typing import Optional

from fastapi import Cookie, HTTPException, status

# In-memory session store: {token: expires_at_monotonic}
# Thread-safe via _sessions_lock.
_sessions: dict[str, float] = {}
_sessions_lock = threading.Lock()
_SESSION_TTL = 8 * 60 * 60  # 8 hours


def verify_session(session_token: Optional[str] = Cookie(default=None)) -> str:
    """Verify session token. Raises 401 if missing or invalid."""
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
    """Create a new session token and register it in the session store."""
    token = secrets.token_urlsafe(32)
    with _sessions_lock:
        _sessions[token] = time.monotonic() + _SESSION_TTL
    return token


def invalidate_session(token: str) -> None:
    """Invalidate a session token (logout)."""
    with _sessions_lock:
        _sessions.pop(token, None)


def _is_valid_session(token: str) -> bool:
    """Validate session token against the in-memory store with TTL check."""
    with _sessions_lock:
        expires_at = _sessions.get(token)
        if expires_at is None:
            return False
        if time.monotonic() > expires_at:
            _sessions.pop(token, None)
            return False
        return True


def _purge_expired_sessions() -> int:
    """Remove all expired sessions. Returns count removed."""
    now = time.monotonic()
    with _sessions_lock:
        expired = [t for t, exp in _sessions.items() if now > exp]
        for t in expired:
            del _sessions[t]
    return len(expired)
