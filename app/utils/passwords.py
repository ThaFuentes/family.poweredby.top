"""Household password reset. Token is bound to user + household. No cross-tenant lookup."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from flask import url_for

from app.builddb.builddb import db
from app.builddb.table_password_resets import PasswordReset
from app.builddb.table_users import User
from app.utils.mail import send_mail

TTL_HOURS = 2
SAME_MSG = "If that account exists in this household system, we sent a reset link."


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def issue_reset(user: User, requested_by: int | None = None) -> str | None:
    if user is None or not user.is_active:
        return None
    if not (user.email or "").strip():
        return None
    household = getattr(user, "household", None)
    if household is not None and not bool(getattr(household, "is_active", True)):
        return None
    PasswordReset.query.filter_by(user_id=int(user.id), used_at=None).update(
        {"used_at": _utcnow()}, synchronize_session=False
    )
    raw = secrets.token_urlsafe(32)
    db.session.add(
        PasswordReset(
            household_id=int(user.household_id),
            user_id=int(user.id),
            token_hash=_hash(raw),
            requested_by=requested_by,
            expires_at=_utcnow() + timedelta(hours=TTL_HOURS),
        )
    )
    db.session.commit()
    return raw


def send_reset_email(user: User, token: str) -> tuple[bool, str]:
    link = url_for("auth.reset_password", token=token, _external=True)
    body = (
        f"Hi {user.name or user.username},\n\n"
        "Someone asked to reset your Family OS password. This link is only for your account "
        "in your household — it will not work for anyone else.\n\n"
        f"{link}\n\n"
        f"It expires in {TTL_HOURS} hours. If you did not ask for this, ignore the email.\n"
    )
    return send_mail(user.email, "Reset your Family OS password", body)


def find_user_for_forgot(ident: str, household: str | None = None) -> User | None:
    from app.utils.identity import find_login

    user = find_login(ident, household)
    if user is None or not user.is_active:
        return None
    return user


def consume_token(token: str) -> PasswordReset | None:
    if not token:
        return None
    row = PasswordReset.query.filter_by(token_hash=_hash(token)).first()
    if row is None or row.used_at is not None:
        return None
    if row.expires_at and row.expires_at < _utcnow():
        return None
    user = User.query.filter_by(id=row.user_id, household_id=row.household_id, is_active=True).first()
    if user is None:
        return None
    household = getattr(user, "household", None)
    if household is not None and not bool(getattr(household, "is_active", True)):
        return None
    row._user = user
    return row


def mark_used(row: PasswordReset) -> None:
    row.used_at = _utcnow()
    db.session.commit()
