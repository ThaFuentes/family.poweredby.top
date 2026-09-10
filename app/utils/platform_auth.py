"""Platform owner identity. Separate from household Flask-Login users."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import redirect, request, session, url_for

from app.builddb.builddb import db
from app.builddb.table_platform_invites import PlatformInvite
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


def normalize_owner_code(raw: str | None) -> str:
    return (raw or "").strip().upper().replace(" ", "").replace("—", "-")


def find_owner_invite(code: str) -> PlatformInvite | None:
    c = normalize_owner_code(code)
    if not c:
        return None
    variants = [c]
    if c.startswith("OWN-"):
        pass
    elif not c.startswith(("SRV-", "FAM-")):
        variants.append("OWN-" + c)
    for variant in variants:
        row = PlatformInvite.query.filter_by(code=variant).first()
        if row:
            return row
    return None


def owner_invite_ok(invite: PlatformInvite | None) -> tuple[bool, str]:
    if invite is None:
        return False, "Need an owner key from the first owner."
    if invite.revoked_at:
        return False, "That owner key was revoked."
    if invite.expires_at and invite.expires_at < _utcnow():
        return False, "That owner key expired."
    if invite.use_count >= (invite.max_uses or 1):
        return False, "That owner key is used up."
    return True, ""


def consume_owner_invite(invite: PlatformInvite) -> None:
    invite.use_count = int(invite.use_count or 0) + 1
    invite.last_used_at = _utcnow()
    db.session.add(invite)


def mint_owner_invite(*, created_by=None, label: str = "", max_uses=1, days=30) -> PlatformInvite:
    try:
        uses = max(1, int(max_uses or 1))
    except Exception:
        uses = 1
    try:
        life = max(1, int(days or 30))
    except Exception:
        life = 30
    row = PlatformInvite(
        code=PlatformInvite.new_code(),
        created_by=created_by,
        label=(label or "").strip() or None,
        max_uses=uses,
        expires_at=_utcnow() + timedelta(days=life),
    )
    db.session.add(row)
    db.session.commit()
    return row


def revoke_owner_invite(row: PlatformInvite) -> None:
    row.revoked_at = _utcnow()
    db.session.commit()


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
