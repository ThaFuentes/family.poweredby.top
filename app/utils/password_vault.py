"""Per-household vault.

Every secret field is Fernet-encrypted at rest. Ciphertext stays in the
model; we only decrypt after the person re-enters their Family OS username
and password. Access is household, just the owner, or named people with an
optional expiry. Grants keep history: remaining time, revoke, and who opened it.
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

SECRET_FIELDS = (
    "title",
    "login",
    "secret",
    "url",
    "purpose",
    "details",
    "phone",
    "phone_alt",
    "account_no",
    "two_factor",
    "two_factor_detail",
    "call_info",
)
SHARE_MODES = ("household", "personal", "selected")
KINDS = ("password", "billing", "info")
KIND_LABELS = {
    "password": "Passwords",
    "billing": "Billing",
    "info": "Shareable info",
}
KIND_ONE = {
    "password": "Login",
    "billing": "Bill",
    "info": "Shareable info",
}
KIND_ADD = {
    "password": "Add a login",
    "billing": "Add a bill",
    "info": "Add shareable info",
}
KIND_CHOICE = {
    "password": "Password / login",
    "billing": "Billing",
    "info": "Shareable information",
}
TWO_FACTOR = (
    ("", "Not set"),
    ("none", "No 2FA"),
    ("sms", "Text / SMS"),
    ("app", "Authenticator app"),
    ("email", "Email code"),
    ("hardware", "Hardware key"),
    ("other", "Yes — see details"),
)
TWO_FACTOR_LABELS = {key: lab for key, lab in TWO_FACTOR}
ACCESS_ACTIONS = (
    "view",
    "copy_login",
    "copy_secret",
    "copy_phone",
    "copy_account",
    "reveal",
    "open_site",
    "granted",
    "revoked",
    "extended",
)
ACCESS_ACTION_LABELS = {
    "view": "opened this",
    "copy_login": "copied the username",
    "copy_secret": "copied the password",
    "copy_phone": "copied the phone",
    "copy_account": "copied the account number",
    "reveal": "showed the password",
    "open_site": "opened the site",
    "granted": "got access",
    "revoked": "lost access",
    "extended": "got more time",
}
VIEW_DEDUPE_SECONDS = 120
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
DURATION_LABELS = {key: lab for key, lab in DURATIONS}


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


def _naive(dt):
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is not None:
        return dt.replace(tzinfo=None)
    return dt


def grant_is_live(grant, now: datetime | None = None) -> bool:
    if grant is None:
        return False
    if getattr(grant, "revoked_at", None):
        return False
    when = now or _utcnow()
    exp = _naive(getattr(grant, "expires_at", None))
    if exp is None:
        return True
    return exp > when


def grant_status(grant, now: datetime | None = None) -> str:
    if grant is None:
        return "none"
    if getattr(grant, "revoked_at", None):
        return "revoked"
    if grant_is_live(grant, now):
        return "live"
    return "ended"


def live_grants(grants: Iterable | None, now: datetime | None = None) -> list:
    return [g for g in (grants or []) if grant_is_live(g, now)]


def ended_grants(grants: Iterable | None, now: datetime | None = None) -> list:
    rows = [g for g in (grants or []) if not grant_is_live(g, now)]
    rows.sort(key=lambda g: _naive(getattr(g, "revoked_at", None) or getattr(g, "expires_at", None) or getattr(g, "created_at", None)) or datetime.min, reverse=True)
    return rows


def duration_label(key: str | None) -> str:
    return DURATION_LABELS.get((key or "").strip().lower(), "Forever")


def kind_of(entry_or_key) -> str:
    raw = entry_or_key
    if not isinstance(raw, str):
        raw = getattr(entry_or_key, "kind", None) or "password"
    key = (raw or "password").strip().lower()
    return key if key in KINDS else "password"


def kind_label(entry_or_key) -> str:
    return KIND_LABELS.get(kind_of(entry_or_key), "Passwords")


def kind_one(entry_or_key) -> str:
    return KIND_ONE.get(kind_of(entry_or_key), "Login")


def two_factor_label(key: str | None) -> str:
    raw = (key or "").strip().lower()
    if not raw:
        return ""
    return TWO_FACTOR_LABELS.get(raw, raw)


def remaining_seconds(grant, now: datetime | None = None) -> int | None:
    if not grant_is_live(grant, now):
        return 0
    exp = _naive(getattr(grant, "expires_at", None))
    if exp is None:
        return None
    when = now or _utcnow()
    return max(0, int((exp - when).total_seconds()))


def remaining_text(grant, now: datetime | None = None) -> str:
    status = grant_status(grant, now)
    if status == "revoked":
        return "taken back"
    if status == "ended":
        return "ended"
    secs = remaining_seconds(grant, now)
    if secs is None:
        return "stays · no end"
    if secs <= 0:
        return "ended"
    if secs < 60:
        return "under a minute left"
    if secs < 3600:
        mins = max(1, secs // 60)
        return f"{mins} min left"
    if secs < 86400:
        hours = secs // 3600
        mins = (secs % 3600) // 60
        if hours <= 0:
            return f"{max(1, mins)} min left"
        if mins:
            return f"{hours} hr {mins} min left"
        return f"{hours} hr left"
    days = secs // 86400
    hours = (secs % 86400) // 3600
    if hours:
        return f"{days} day{'s' if days != 1 else ''} {hours} hr left"
    return f"{days} day{'s' if days != 1 else ''} left"


def ago_text(dt, now: datetime | None = None) -> str:
    when = _naive(dt)
    if when is None:
        return "never"
    stamp = now or _utcnow()
    secs = int((stamp - when).total_seconds())
    if secs < 0:
        secs = 0
    if secs < 20:
        return "just now"
    if secs < 3600:
        return f"{max(1, secs // 60)} min ago"
    if secs < 86400:
        hours = secs // 3600
        return f"{hours} hr ago" if hours == 1 else f"{hours} hr ago"
    days = secs // 86400
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    return f"{when.strftime('%b')} {when.day}"


def clock_label(dt) -> str:
    when = _naive(dt)
    if when is None:
        return ""
    hour = when.hour % 12 or 12
    ampm = "AM" if when.hour < 12 else "PM"
    return f"{when.strftime('%b')} {when.day}, {hour}:{when.minute:02d} {ampm}"


def iso_utc(dt) -> str:
    when = _naive(dt)
    if when is None:
        return ""
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def seen_text(grant, now: datetime | None = None) -> str:
    count = int(getattr(grant, "seen_count", 0) or 0)
    last = getattr(grant, "last_seen_at", None)
    if count <= 0 and last is None:
        return "Never opened"
    ago = ago_text(last, now)
    if count <= 0:
        return f"Opened · last {ago}"
    times = "once" if count == 1 else f"{count} times"
    return f"Opened {times} · last {ago}"


def person_name(user_id, people: dict | None = None) -> str:
    uid = int(user_id or 0)
    if people and uid in people:
        person = people[uid]
        return (getattr(person, "name", None) or getattr(person, "username", None) or "someone").strip()
    return "someone"


def grant_view(grant, people: dict | None = None, now: datetime | None = None) -> dict:
    stamp = now or _utcnow()
    status = grant_status(grant, stamp)
    ended_at = _naive(getattr(grant, "revoked_at", None) or (None if status == "live" else getattr(grant, "expires_at", None)))
    return {
        "grant": grant,
        "user_id": int(getattr(grant, "user_id", 0) or 0),
        "name": person_name(getattr(grant, "user_id", 0), people),
        "live": status == "live",
        "status": status,
        "remaining": remaining_text(grant, stamp),
        "until": iso_utc(getattr(grant, "expires_at", None)),
        "until_label": "no end" if getattr(grant, "expires_at", None) is None else clock_label(getattr(grant, "expires_at", None)),
        "given_for": (
            duration_label(getattr(grant, "duration_key", None))
            if (getattr(grant, "duration_key", None) or "forever") != "forever"
            or getattr(grant, "expires_at", None) is None
            else "a set time"
        ),
        "seen": seen_text(grant, stamp),
        "seen_count": int(getattr(grant, "seen_count", 0) or 0),
        "last_seen_at": iso_utc(getattr(grant, "last_seen_at", None)),
        "last_seen_ago": ago_text(getattr(grant, "last_seen_at", None), stamp),
        "ended_at": iso_utc(ended_at),
        "ended_label": clock_label(ended_at),
        "started_label": clock_label(getattr(grant, "created_at", None)),
    }


def access_action_label(action: str) -> str:
    return ACCESS_ACTION_LABELS.get((action or "").strip().lower(), (action or "used this").replace("_", " "))


def log_vault_access(entry, user, action: str = "view", *, grant=None) -> None:
    from app.builddb.builddb import db
    from app.builddb.table_vault_access import VaultAccess

    hid = int(getattr(entry, "household_id", 0) or 0)
    eid = int(getattr(entry, "id", 0) or 0)
    uid = int(getattr(user, "id", 0) or 0)
    act = (action or "view").strip().lower()
    if act not in ACCESS_ACTIONS:
        act = "view"
    if not hid or not eid or not uid:
        return
    now = _utcnow()
    if act == "view":
        recent = (
            VaultAccess.query.filter_by(entry_id=eid, user_id=uid, action="view")
            .order_by(VaultAccess.id.desc())
            .first()
        )
        last = _naive(getattr(recent, "created_at", None)) if recent is not None else None
        if last is not None and (now - last).total_seconds() < VIEW_DEDUPE_SECONDS:
            return
    db.session.add(
        VaultAccess(
            household_id=hid,
            entry_id=eid,
            user_id=uid,
            action=act,
        )
    )
    target = grant
    if target is None:
        for g in getattr(entry, "grants", None) or []:
            if int(getattr(g, "user_id", 0) or 0) != uid:
                continue
            if grant_is_live(g, now):
                target = g
                break
    if target is not None and act in ("view", "copy_login", "copy_secret", "copy_phone", "copy_account", "reveal", "open_site"):
        if act == "view":
            target.seen_count = int(getattr(target, "seen_count", 0) or 0) + 1
        target.last_seen_at = now


def recent_access(entry, people: dict | None = None, limit: int = 12) -> list[dict]:
    rows = list(getattr(entry, "access", None) or [])
    rows.sort(key=lambda r: int(getattr(r, "id", 0) or 0), reverse=True)
    out = []
    for row in rows[:limit]:
        out.append(
            {
                "name": person_name(getattr(row, "user_id", 0), people),
                "action": access_action_label(getattr(row, "action", None) or "view"),
                "when": iso_utc(getattr(row, "created_at", None)),
                "ago": ago_text(getattr(row, "created_at", None)),
                "label": clock_label(getattr(row, "created_at", None)),
            }
        )
    return out


def household_opened(entry, adults, people: dict | None = None) -> list[dict]:
    counts: dict[int, dict] = {}
    for row in getattr(entry, "access", None) or []:
        uid = int(getattr(row, "user_id", 0) or 0)
        if not uid:
            continue
        act = (getattr(row, "action", None) or "").strip().lower()
        if act not in ("view", "copy_login", "copy_secret", "copy_phone", "copy_account", "reveal", "open_site"):
            continue
        rec = counts.setdefault(uid, {"count": 0, "last": None})
        if act == "view":
            rec["count"] += 1
        when = _naive(getattr(row, "created_at", None))
        if when is not None and (rec["last"] is None or when > rec["last"]):
            rec["last"] = when
    out = []
    for person in adults or []:
        uid = int(getattr(person, "id", 0) or 0)
        rec = counts.get(uid) or {"count": 0, "last": None}
        fake = type("G", (), {"seen_count": rec["count"], "last_seen_at": rec["last"]})()
        out.append(
            {
                "user_id": uid,
                "name": person_name(uid, people) if people else (getattr(person, "name", None) or getattr(person, "username", None) or "someone"),
                "seen_count": rec["count"],
                "last_seen_ago": ago_text(rec["last"]),
                "seen": seen_text(fake),
            }
        )
    return out


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
    name = person_name(getattr(grant, "user_id", 0), people)
    return f"{name} · {remaining_text(grant)}"


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


def site_label(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    from urllib.parse import urlparse

    parsed = urlparse(href_for(raw))
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host or raw
