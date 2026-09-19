"""Per-household password vault.

Every secret field is Fernet-encrypted at rest (title, login, password, URL,
purpose, details). Ciphertext stays in the model; we only decrypt after the
person re-enters their Family OS username and password. Access is household,
just the owner, or named people with an optional expiry.
"""
from __future__ import annotations

import base64
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

SECRET_FIELDS = ("title", "login", "secret", "url", "purpose", "details")
SHARE_MODES = ("household", "personal", "selected")
SESSION_UID = "family_pwvault_uid"
SESSION_TS = "family_pwvault_ts"
# Idle lock only. Using the vault (page load, typing, save) resets this.
REAUTH_SECONDS = 45 * 60
DURATIONS = (
    ("forever", "Forever"),
    ("1h", "1 hour"),
    ("4h", "4 hours"),
    ("12h", "12 hours"),
    ("1d", "1 day"),
    ("1w", "1 week"),
    ("30d", "30 days"),
)
DURATION_HOURS = {
    "forever": None,
    "1h": 1,
    "4h": 4,
    "12h": 12,
    "1d": 24,
    "1w": 168,
    "30d": 720,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _derived_fernet(household_id: int) -> Fernet | None:
    from app.utils.crypto import _read_shared_key, get_platform_fernet

    hid = int(household_id or 0)
    secret = (os.getenv("FAMILY_DATA_KEY") or "").strip() or _read_shared_key()
    if not secret:
        get_platform_fernet()
        secret = (os.getenv("FAMILY_DATA_KEY") or "").strip() or _read_shared_key()
    if not secret:
        return None
    material = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=f"family-os-pwvault-h{hid}".encode("utf-8"),
        info=b"family.poweredby.top.password-vault.v1",
    ).derive(secret.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(material))


def _encrypt_keys(household_id: int) -> list[Fernet]:
    out: list[Fernet] = []
    try:
        from app.utils.household_vault import session_fernet

        house = session_fernet()
        if house is not None:
            out.append(house)
    except Exception:
        pass
    derived = _derived_fernet(household_id)
    if derived is not None and derived not in out:
        out.append(derived)
    return out


def _decrypt_keys(household_id: int) -> list[Fernet]:
    keys = _encrypt_keys(household_id)
    try:
        from app.utils.crypto import get_platform_fernet

        platform = get_platform_fernet()
        if platform is not None and platform not in keys:
            keys.append(platform)
    except Exception:
        pass
    return keys


def encrypt_vault_text(value: str | None, household_id: int) -> str:
    text = "" if value is None else str(value)
    keys = _encrypt_keys(household_id)
    if not keys:
        from app.utils.crypto import get_platform_fernet

        extra = get_platform_fernet()
        if extra is not None:
            keys = [extra]
    if not keys:
        raise RuntimeError("Cannot encrypt vault data.")
    return keys[0].encrypt(text.encode("utf-8")).decode("ascii")


def decrypt_vault_text(value: str | None, household_id: int) -> str:
    if value is None:
        return ""
    text = str(value)
    if text == "":
        return ""
    from app.utils.crypto import looks_encrypted

    if not looks_encrypted(text):
        return text
    raw = text.encode("ascii")
    for f in _decrypt_keys(household_id):
        try:
            return f.decrypt(raw).decode("utf-8")
        except (InvalidToken, Exception):
            continue
    return ""


def seal_fields(fields: dict, household_id: int) -> dict:
    out = {}
    for key in SECRET_FIELDS:
        raw = fields.get(key)
        out[key] = encrypt_vault_text("" if raw is None else str(raw), household_id)
    return out


def open_fields(row, household_id: int | None = None) -> dict:
    hid = int(household_id or getattr(row, "household_id", 0) or 0)
    return {key: decrypt_vault_text(getattr(row, key, None), hid) for key in SECRET_FIELDS}


def is_child(user=None) -> bool:
    from flask_login import current_user
    from app.utils.permissions import role_of

    return role_of(user if user is not None else current_user) == "child"


def can_use_vault(user=None) -> bool:
    from flask_login import current_user
    from app.utils.permissions import can

    u = user if user is not None else current_user
    if not getattr(u, "is_authenticated", False):
        return False
    if is_child(u):
        return False
    return can("vault", u)


def _is_leader(user) -> bool:
    if bool(getattr(user, "is_leader", False)):
        return True
    return bool(getattr(user, "is_admin", False))


def grant_is_live(grant, now: datetime | None = None) -> bool:
    if grant is None:
        return False
    when = now or _utcnow()
    exp = getattr(grant, "expires_at", None)
    if exp is None:
        return True
    if getattr(exp, "tzinfo", None) is not None:
        exp = exp.replace(tzinfo=None)
    return exp > when


def can_view_entry(entry, user, grants: Iterable | None = None, now: datetime | None = None) -> bool:
    if entry is None or user is None:
        return False
    if int(getattr(user, "household_id", 0) or 0) != int(getattr(entry, "household_id", 0) or 0):
        return False
    if is_child(user):
        return False
    uid = int(getattr(user, "id", 0) or 0)
    created = int(getattr(entry, "created_by", 0) or 0)
    if uid and created and uid == created:
        return True
    mode = (getattr(entry, "share_mode", None) or "personal").strip().lower()
    if mode == "household":
        return True
    if mode == "personal":
        return False
    rows = grants if grants is not None else getattr(entry, "grants", None) or []
    when = now or _utcnow()
    for g in rows:
        if int(getattr(g, "user_id", 0) or 0) != uid:
            continue
        if grant_is_live(g, when):
            return True
    return False


def can_manage_entry(entry, user) -> bool:
    if entry is None or user is None:
        return False
    if int(getattr(user, "household_id", 0) or 0) != int(getattr(entry, "household_id", 0) or 0):
        return False
    if is_child(user):
        return False
    uid = int(getattr(user, "id", 0) or 0)
    created = int(getattr(entry, "created_by", 0) or 0)
    if uid and created and uid == created:
        return True
    return _is_leader(user)


def _username_login_match(user, typed: str) -> bool:
    from app.utils.identity import norm_username

    ident = (typed or "").strip()
    if not ident:
        return False
    if "@" in ident:
        email = (getattr(user, "email", None) or "").strip()
        return bool(email) and email.lower() == ident.lower()
    return norm_username(ident) == norm_username(getattr(user, "username", None) or "")


def confirm_app_login(user, *, username: str, password: str) -> bool:
    """True only if this is the signed-in person's username and password.

    Not the family lock. Not password alone.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if not _username_login_match(user, username):
        return False
    check = getattr(user, "check_password", None)
    if not callable(check):
        return False
    try:
        return bool(check(password or ""))
    except Exception:
        return False


def reauth_ok(user=None) -> bool:
    from flask import has_request_context, session
    from flask_login import current_user

    u = user if user is not None else current_user
    if not has_request_context():
        return False
    try:
        uid = int(session.get(SESSION_UID) or 0)
        ts = int(session.get(SESSION_TS) or 0)
    except Exception:
        return False
    if not uid or uid != int(getattr(u, "id", 0) or 0):
        return False
    if ts <= 0 or (int(time.time()) - ts) > REAUTH_SECONDS:
        return False
    return True


def mark_reauth(user=None) -> None:
    from flask import session
    from flask_login import current_user

    u = user if user is not None else current_user
    session[SESSION_UID] = int(getattr(u, "id", 0) or 0)
    session[SESSION_TS] = int(time.time())


def touch_reauth(user=None) -> bool:
    """Reset the idle clock if the vault is already open."""
    if not reauth_ok(user):
        return False
    mark_reauth(user)
    return True


def lock_reauth() -> None:
    from flask import has_request_context, session

    if not has_request_context():
        return
    session.pop(SESSION_UID, None)
    session.pop(SESSION_TS, None)


def reauth_remaining() -> int:
    from flask import has_request_context, session

    if not has_request_context():
        return 0
    try:
        ts = int(session.get(SESSION_TS) or 0)
    except Exception:
        return 0
    left = REAUTH_SECONDS - (int(time.time()) - ts)
    return max(0, left)


def parse_duration(raw: str | None) -> datetime | None:
    key = (raw or "forever").strip().lower()
    hours = DURATION_HOURS.get(key)
    if hours is None:
        return None
    return _utcnow() + timedelta(hours=int(hours))


def duration_key_for(expires_at) -> str:
    if expires_at is None:
        return "forever"
    when = expires_at
    if getattr(when, "tzinfo", None) is not None:
        when = when.replace(tzinfo=None)
    delta = when - _utcnow()
    hours = max(0, int(delta.total_seconds() // 3600))
    best = "forever"
    best_h = None
    for key, h in DURATION_HOURS.items():
        if h is None:
            continue
        if hours <= h and (best_h is None or h < best_h):
            best = key
            best_h = h
    if best_h is None:
        return "30d"
    return best


def grant_label(grant, people: dict | None = None) -> str:
    name = "someone"
    uid = int(getattr(grant, "user_id", 0) or 0)
    if people and uid in people:
        person = people[uid]
        name = (getattr(person, "name", None) or getattr(person, "username", None) or name).strip()
    if not grant_is_live(grant):
        return f"{name} · ended"
    exp = getattr(grant, "expires_at", None)
    if exp is None:
        return f"{name} · stays"
    when = exp
    if getattr(when, "tzinfo", None) is not None:
        when = when.replace(tzinfo=None)
    left = when - _utcnow()
    secs = int(left.total_seconds())
    if secs <= 0:
        return f"{name} · ended"
    if secs < 3600:
        return f"{name} · {max(1, secs // 60)} min left"
    if secs < 86400:
        return f"{name} · {secs // 3600} hr left"
    days = secs // 86400
    return f"{name} · {days} day{'s' if days != 1 else ''} left"


def share_label(mode: str) -> str:
    return {
        "household": "Whole household",
        "personal": "Just me",
        "selected": "These people",
    }.get((mode or "").strip().lower(), "Just me")


def href_for(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    lower = raw.lower()
    if lower.startswith("http://") or lower.startswith("https://"):
        return raw
    if lower.startswith("mailto:"):
        return raw
    return "https://" + raw
