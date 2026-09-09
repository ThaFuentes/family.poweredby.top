"""Platform owner identity. Separate from household Flask-Login users."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import redirect, request, session, url_for

from app.builddb.builddb import db
from app.builddb.table_platform_owners import PlatformOwner

SESSION_OWNER_ID = "family_platform_owner_id"
SESSION_OWNER_NAME = "family_platform_owner_name"
LOCK_AFTER = 5
LOCK_MINUTES = 15


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def owner_count() -> int:
    return int(PlatformOwner.query.count())


def needs_setup() -> bool:
    return owner_count() == 0


def bootstrap_token_required() -> bool:
    token = (os.getenv("PLATFORM_BOOTSTRAP_TOKEN") or "").strip()
    if token:
        return True
    debug = (os.getenv("DEBUG_MODE") or "").strip().lower() in ("1", "true", "yes", "on")
    return not debug


def bootstrap_token_ok(given: str) -> bool:
    expected = (os.getenv("PLATFORM_BOOTSTRAP_TOKEN") or "").strip()
    if expected:
        return bool(given) and given == expected
    if bootstrap_token_required():
        return False
    return True


def current_owner() -> PlatformOwner | None:
    oid = session.get(SESSION_OWNER_ID)
    if not oid:
        return None
    try:
        row = PlatformOwner.query.filter_by(id=int(oid), is_active=True).first()
    except Exception:
        return None
    return row


def is_owner() -> bool:
    return current_owner() is not None


def login_owner(owner: PlatformOwner) -> None:
    session[SESSION_OWNER_ID] = int(owner.id)
    session[SESSION_OWNER_NAME] = owner.name or owner.username
    session.permanent = True
    try:
        from poweredbytop.security.csrf import rotate_csrf_token

        rotate_csrf_token()
    except Exception:
        pass


def logout_owner() -> None:
    session.pop(SESSION_OWNER_ID, None)
    session.pop(SESSION_OWNER_NAME, None)


def require_owner(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not is_owner():
            return redirect(url_for("platform.login", next=request.path))
        return fn(*args, **kwargs)

    return wrapped


def owner_is_locked(owner: PlatformOwner) -> bool:
    lock = owner.account_locked_until
    if not lock:
        return False
    if lock.tzinfo is None:
        lock = lock.replace(tzinfo=timezone.utc)
    return lock > datetime.now(timezone.utc)


def mark_login_failure(owner: PlatformOwner | None) -> None:
    if owner is None:
        return
    owner.failed_login_attempts = (owner.failed_login_attempts or 0) + 1
    if owner.failed_login_attempts >= LOCK_AFTER:
        owner.account_locked_until = _utcnow() + timedelta(minutes=LOCK_MINUTES)
    db.session.commit()


def mark_login_success(owner: PlatformOwner) -> None:
    owner.failed_login_attempts = 0
    owner.account_locked_until = None
    owner.last_login_at = _utcnow()
    db.session.commit()


def find_owner(ident: str) -> PlatformOwner | None:
    ident = (ident or "").strip()
    if not ident:
        return None
    return PlatformOwner.query.filter(
        (PlatformOwner.username == ident) | (PlatformOwner.email == ident)
    ).first()
