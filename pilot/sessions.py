"""Per-user session management for multi-user server deployment.

Each teacher gets an isolated session stored in:
  <ROOT>/sessions/<session_id>/
    notebooklm_profile/   ← NOTEBOOKLM_HOME for that user's Playwright/auth state
    outputs/              ← that user's generated reports
    uploads/              ← that user's temporary uploads
    work/                 ← that user's temp subject downloads

Sessions expire after IDLE_TTL seconds of inactivity and are cleaned up by a
background daemon thread so the server never accumulates stale data.
"""
from __future__ import annotations

import os
import secrets
import shutil
import threading
import time
from pathlib import Path

# How long (seconds) a session can be idle before it is cleaned up.
# Default 8 hours; overridable via PILOT_SESSION_TTL_SECONDS env var.
_DEFAULT_TTL = 8 * 3600

COOKIE_NAME = "pilot_session"

_sessions: dict[str, "_Session"] = {}
_lock = threading.Lock()


class _Session:
    def __init__(self, session_id: str, root: Path) -> None:
        self.session_id = session_id
        self.base = root / "sessions" / session_id
        self.notebooklm_home = self.base / "notebooklm_profile"
        self.outputs_dir = self.base / "outputs"
        self.uploads_dir = self.base / "uploads"
        self.work_dir = self.base / "work"
        self.connected: bool = False
        self._last_activity: float = time.monotonic()
        # Each session tracks its own in-progress jobs
        self.jobs: dict[str, dict] = {}
        self.jobs_lock = threading.Lock()
        # Create directories eagerly so nothing fails on first use
        for d in (
            self.notebooklm_home,
            self.outputs_dir,
            self.uploads_dir,
            self.work_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    def touch(self) -> None:
        self._last_activity = time.monotonic()

    def idle_seconds(self) -> float:
        return time.monotonic() - self._last_activity

    def destroy(self) -> None:
        """Remove all session data from disk."""
        try:
            shutil.rmtree(self.base, ignore_errors=True)
        except Exception:
            pass


def _ttl() -> int:
    try:
        return max(60, int(os.environ.get("PILOT_SESSION_TTL_SECONDS", _DEFAULT_TTL)))
    except (TypeError, ValueError):
        return _DEFAULT_TTL


def _generate_id() -> str:
    return secrets.token_urlsafe(32)


def get_or_create(session_id: str | None, root: Path) -> "_Session":
    """Return an existing session or create a new one."""
    with _lock:
        if session_id and session_id in _sessions:
            sess = _sessions[session_id]
            sess.touch()
            return sess
        new_id = _generate_id()
        sess = _Session(new_id, root)
        _sessions[new_id] = sess
        return sess


def get(session_id: str | None) -> "_Session | None":
    """Return an existing session without creating a new one."""
    if not session_id:
        return None
    with _lock:
        sess = _sessions.get(session_id)
        if sess:
            sess.touch()
        return sess


def remove(session_id: str) -> None:
    with _lock:
        sess = _sessions.pop(session_id, None)
    if sess:
        sess.destroy()


def _cleanup_loop() -> None:
    """Daemon thread: evict sessions idle longer than TTL."""
    while True:
        time.sleep(300)  # check every 5 minutes
        ttl = _ttl()
        with _lock:
            stale = [sid for sid, s in _sessions.items() if s.idle_seconds() > ttl]
        for sid in stale:
            remove(sid)


def start_cleanup_daemon() -> None:
    """Start the background session-cleanup thread (call once at startup)."""
    t = threading.Thread(target=_cleanup_loop, daemon=True)
    t.start()
