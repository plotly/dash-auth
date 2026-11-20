"""Revoke a logged-out session's protected streams.

A stream's caller is captured at dispatch; a cleared session cookie can't reach
that snapshot, so a page left open after logout kept receiving frames. Each
logged-in session carries a random id; logout marks it revoked, and the
protected stream wrapper checks the mark between frames.

The mark lives in the app's Dash shared storage, so every worker sees it. Dash
only serves HTTP streams with shared storage; without it the only streams are
WebSocket ones, which capture no session id (logout closes their socket
instead), so there is nothing to mark.
"""

import logging
import secrets
from typing import Any

logger = logging.getLogger(__name__)

SESSION_ID_KEY = "_sid"
# shortcut: a fixed TTL, so a protected stream still running a day after its
# session logged out is no longer stopped; derive it from the session lifetime
# once sessions have an absolute one (Issue 13).
REVOKED_TTL = 24 * 60 * 60
# Seconds between store lookups for one stream: bounds the cost of fast
# streams, and the delay before a logout stops them.
CHECK_INTERVAL = 1.0

_KEY_PREFIX = "dash_auth_async:revoked:"


def ensure_session_id(session: Any) -> str:
    """Give ``session`` a revocable id if it has none.

    Returns:
        The session's id.
    """
    if SESSION_ID_KEY not in session:
        session[SESSION_ID_KEY] = secrets.token_urlsafe(16)
    return session[SESSION_ID_KEY]


def revoke_session_streams(app: Any, sid: str | None) -> None:
    """Mark ``sid`` revoked. Never raises: logout must go through regardless."""
    if not sid:
        return
    try:
        _write_revoked(app, sid)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("Could not revoke the streams of a logged-out session.")


def is_session_revoked(app: Any, sid: str | None) -> bool:
    """Whether ``sid`` was logged out. Store errors count as revoked (fail closed).

    Returns:
        True when the session's streams must stop.
    """
    if not sid:
        return False
    try:
        return _read_revoked(app, sid)
    except Exception as err:  # pylint: disable=broad-exception-caught
        logger.warning("Stopping a protected stream: revocation check failed: %s", err)
        return True


def _write_revoked(app: Any, sid: str) -> None:
    if getattr(app, "shared_storage_enabled", False):  # dash<4.5: no attribute
        app.shared_storage.set(_KEY_PREFIX + sid, True, ttl=REVOKED_TTL)


def _read_revoked(app: Any, sid: str) -> bool:
    if not getattr(app, "shared_storage_enabled", False):
        return False
    return bool(app.shared_storage.get(_KEY_PREFIX + sid))
