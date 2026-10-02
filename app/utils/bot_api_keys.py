"""Bot API keys: mint a pair, mail each half to a different inbox, revoke.

A scope lives in the key prefix, so a `fos_vault_` key can never pass a
`fos_bot_` check by accident:

    fos_bot_<secret>     read + write vehicles / notes / files / inventory / records
    fos_vault_<secret>   read-only vault

Every scope is issued as a **pair**:

    primary  -> the bot's login inbox          (the key you sign in with)
    twofa    -> the bot's 2FA inbox            (the key emailed as the second factor)

The bot posts both once to `/api/v1/auth/exchange` and gets a short-lived
session token back. The emailed half is spent at that moment and is never
sent on a later request.

Only the hash is stored. That is why a "resend" cannot repeat the old key: it
issues a fresh pair and revokes the previous one, so exactly one pair per
scope is ever live.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from app.builddb.builddb import db
from app.builddb.table_bot_api_keys import BotApiKey, SCOPES, KEY_ROLES

SESSION_PREFIX = "fos_s1_"
SCOPE_ALL = "fos_bot_"
SCOPE_VAULT = "fos_vault_"
DEFAULT_DAYS = 90
MAX_DAYS = 365
KEY_BODY_BYTES = 30

REASONS = ("issued", "reset", "resent")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive(dt) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if getattr(dt, "tzinfo", None) is not None else dt


# ----------------------------------------------------------------- keys


def hash_key(raw: str) -> str:
    """SHA-256 of the whole key. Only this ever reaches the database."""
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()


def key_matches(row: BotApiKey, raw: str) -> bool:
    if row is None or not row.key_hash:
        return False
    return hmac.compare_digest(str(row.key_hash), hash_key(raw))


def new_key(scope: str) -> str:
    """`fos_bot_`/`fos_vault_` + enough entropy that guessing is hopeless."""
    scope = normalize_scope(scope)
    body = secrets.token_urlsafe(KEY_BODY_BYTES).replace("-", "").replace("_", "")
    return f"{scope}{body}"


def normalize_scope(scope: str) -> str:
    raw = (scope or "").strip().lower()
    if raw in SCOPES:
        return raw
    for known in SCOPES:
        if raw.rstrip(":_") in (known.rstrip("_"), known):
            return known
    if raw in ("vault", "vault_", "fos_vault"):
        return "fos_vault_"
    if raw in ("bot", "bots", "fos_bot"):
        return "fos_bot_"
    return "fos_bot_"


def scope_label(scope: str) -> str:
    return "Vault (read-only)" if normalize_scope(scope) == "fos_vault_" else "House (read + write)"


def scope_of(raw: str) -> str:
    """Which scope a presented key claims, by prefix. '' when unknown."""
    token = (raw or "").strip()
    for known in SCOPES:
        if token.startswith(known):
            return known
    return ""


def key_tail(raw: str, size: int = 12) -> str:
    return (raw or "").strip()[-size:]


# ------------------------------------------------------------- inboxes


def login_inbox(user) -> str:
    """Where the origin/login half of the pair goes."""
    return (getattr(user, "email", None) or "").strip()


def twofa_inbox(user) -> str:
    """Where the emailed second factor goes. Must differ from the login inbox."""
    for attr in ("security_email", "email"):
        addr = (getattr(user, attr, None) or "").strip()
        if addr:
            return addr
    return ""


def api_inboxes(user) -> dict:
    login = login_inbox(user).lower()
    second = twofa_inbox(user).lower()
    reset = ""
    try:
        from app.utils.twofa import reset_inbox_for

        reset = (reset_inbox_for(user) or "").strip().lower()
    except Exception:
        reset = (getattr(user, "reset_email", None) or "").strip().lower()
    return {
        "login": login,
        "twofa": second,
        "reset": reset,
        "second_is_separate": bool(second) and second != login,
        "reset_is_separate": bool(reset) and reset != login,
    }


def bot_api_blockers(user) -> list[str]:
    """What still stands between this account and an API key. Empty = ready."""
    if user is None or not getattr(user, "is_active", True):
        return ["account"]
    if not bool(getattr(user, "is_bot", False)):
        return ["not_bot"]
    boxes = api_inboxes(user)
    gaps: list[str] = []
    if not boxes["login"]:
        gaps.append("login_email")
    if not boxes["twofa"]:
        gaps.append("twofa_email")
    elif not boxes["second_is_separate"]:
        gaps.append("twofa_email_same_as_login")
    if not boxes["reset_is_separate"]:
        gaps.append("reset_email")
    try:
        from app.utils.twofa import twofa_enabled

        if not twofa_enabled(user):
            gaps.append("twofa")
    except Exception:
        gaps.append("twofa")
    return gaps


def bot_api_ready(user) -> bool:
    return not bot_api_blockers(user)


BLOCKER_COPY = {
    "account": "That account is not active.",
    "not_bot": "Mark this person as a BOT account first (People -> Mark as BOT).",
    "login_email": "This bot has no login email. That is where the first key goes.",
    "twofa_email": "Name a 2FA email. The second factor is emailed there.",
    "twofa_email_same_as_login": "The 2FA email must not be the login email — the two keys go to different inboxes.",
    "reset_email": "A bot also needs a reset inbox that is not the login email.",
    "twofa": "Turn on 2FA for this bot first (its own Look page or the setup wall).",
}


def blocker_message(user) -> str:
    gaps = bot_api_blockers(user)
    if not gaps:
        return ""
    lines = [BLOCKER_COPY.get(g, g) for g in gaps]
    return " ".join(lines)


# --------------------------------------------------------------- lookup


def find_key(raw: str) -> BotApiKey | None:
    if not raw or not scope_of(raw):
        return None
    try:
        return BotApiKey.query.filter_by(key_hash=hash_key(raw)).first()
    except Exception:
        return None


def key_state(row: BotApiKey) -> tuple[bool, str]:
    """(usable, why-not). Mirrors access.service_pass_ok for the API keys."""
    if row is None:
        return False, "That key is not valid."
    if row.revoked_at:
        return False, "That key was revoked."
    exp = _naive(row.expires_at)
    if exp and exp < _utcnow():
        return False, "That key has expired. Ask the household for a new one."
    return True, ""


def mark_used(row: BotApiKey) -> None:
    row.last_used_at = _utcnow()
    row.use_count = int(row.use_count or 0) + 1
    db.session.add(row)


# ------------------------------------------------------------ minting


def mint_pair(
    user,
    scope: str,
    *,
    label: str = "",
    created_by=None,
    days: int = DEFAULT_DAYS,
) -> tuple[bool, str, dict]:
    """Revoke any live pair on this scope, then issue a fresh one.

    Returns the raw keys. They exist only in this return value — the caller
    mails or displays them and the database keeps hashes.
    """
    blockers = bot_api_blockers(user)
    if blockers:
        return False, blocker_message(user), {}
    scope = normalize_scope(scope)
    try:
        life = max(1, min(int(days or DEFAULT_DAYS), MAX_DAYS))
    except Exception:
        life = DEFAULT_DAYS

    pair_id = secrets.token_hex(16)
    expires = _utcnow() + timedelta(days=life)
    raw = {"primary": new_key(scope), "twofa": new_key(scope)}
    issued = _utcnow()
    # Revoke the outgoing pair FIRST. Doing it after adding the new rows
    # would autoflush them into the query and revoke the pair we just made.
    revoked = revoke_live_pair(user, scope, revoked_by=created_by)
    rows = []
    for role in KEY_ROLES:
        row = BotApiKey(
            household_id=int(getattr(user, "household_id", 0) or 0),
            user_id=int(getattr(user, "id", 0) or 0),
            scope=scope,
            key_role=role,
            key_hash=hash_key(raw[role]),
            key_tail=key_tail(raw[role]),
            pair_id=pair_id,
            label=(label or "").strip()[:120] or None,
            created_by=int(created_by or getattr(user, "id", 0) or 0) or None,
            issued_at=issued,
            expires_at=expires,
            use_count=0,
        )
        db.session.add(row)
        rows.append(row)
    db.session.flush()
    return True, "", {
        "pair_id": pair_id,
        "scope": scope,
        "expires_at": expires,
        "days": life,
        "primary": raw["primary"],
        "twofa": raw["twofa"],
        "rows": rows,
        "revoked_count": revoked,
    }


def revoke_live_pair(user, scope: str | None = None, *, revoked_by=None) -> int:
    """Revoke every open key for this bot (optionally just one scope)."""
    now = _utcnow()
    q = BotApiKey.query.filter_by(
        household_id=int(getattr(user, "household_id", 0) or 0),
        user_id=int(getattr(user, "id", 0) or 0),
        revoked_at=None,
    )
    if scope:
        q = q.filter_by(scope=normalize_scope(scope))
    rows = q.all()
    for row in rows:
        row.revoked_at = now
        row.revoked_by = int(revoked_by or 0) or None
        db.session.add(row)
        _kill_sessions_for_pair(row.pair_id)
    return len(rows)


def _kill_sessions_for_pair(pair_id: str | None) -> None:
    if not pair_id:
        return
    from app.builddb.table_bot_api_sessions import BotApiSession

    try:
        now = _utcnow()
        for s in BotApiSession.query.filter_by(pair_id=pair_id, revoked_at=None).all():
            s.revoked_at = now
            db.session.add(s)
    except Exception:
        pass


def revoke_pair(pair_id: str, *, revoked_by=None) -> int:
    now = _utcnow()
    rows = BotApiKey.query.filter_by(pair_id=pair_id, revoked_at=None).all()
    for row in rows:
        row.revoked_at = now
        row.revoked_by = int(revoked_by or 0) or None
        db.session.add(row)
    _kill_sessions_for_pair(pair_id)
    return len(rows)


# --------------------------------------------------------------- status


def key_status(user) -> list[dict]:
    """One row per issued pair, newest first, for the People panel."""
    rows = (
        BotApiKey.query.filter_by(
            household_id=int(getattr(user, "household_id", 0) or 0),
            user_id=int(getattr(user, "id", 0) or 0),
        )
        .order_by(BotApiKey.id.desc())
        .all()
    )
    pairs: dict[str, dict] = {}
    for row in rows:
        entry = pairs.get(row.pair_id)
        if entry is None:
            entry = {
                "pair_id": row.pair_id,
                "scope": row.scope,
                "scope_label": scope_label(row.scope),
                "label": row.label,
                "created_at": row.created_at,
                "expires_at": row.expires_at,
                "issued_at": row.issued_at,
                "live": False,
                "revoked_at": None,
                "tails": {},
            }
            pairs[row.pair_id] = entry
        entry["tails"][row.key_role] = row.key_tail
        if row.revoked_at:
            if entry["revoked_at"] is None or row.revoked_at < entry["revoked_at"]:
                entry["revoked_at"] = row.revoked_at
        elif entry["revoked_at"] is None:
            exp = _naive(row.expires_at)
            if exp is None or exp > _utcnow():
                entry["live"] = True
    out = list(pairs.values())
    out.sort(key=lambda p: (p["issued_at"] or p["created_at"] or datetime.min), reverse=True)
    return out


def live_pair(user, scope: str) -> BotApiKey | None:
    return (
        BotApiKey.query.filter_by(
            household_id=int(getattr(user, "household_id", 0) or 0),
            user_id=int(getattr(user, "id", 0) or 0),
            scope=normalize_scope(scope),
            revoked_at=None,
        )
        .order_by(BotApiKey.id.desc())
        .first()
    )


def summary(user) -> dict:
    """Everything a key panel needs for one account, with no secrets."""
    boxes = api_inboxes(user)
    gaps = bot_api_blockers(user)
    ready = not gaps
    return {
        "is_bot": bool(getattr(user, "is_bot", False)),
        "ready": ready,
        "gaps": gaps,
        "message": blocker_message(user),
        "inboxes": boxes,
        "pairs": key_status(user) if ready else [],
        "scopes": [SCOPE_ALL, SCOPE_VAULT],
    }


# ---------------------------------------------------------------- mail

REASON_SUBJECT = {
    "issued": "Your Family OS bot API key",
    "reset": "Your Family OS bot API key was reset",
    "resent": "Your Family OS bot API keys (new pair)",
}

REASON_LEAD = {
    "issued": "These keys were just issued for your bot account.",
    "reset": "Your old bot API keys are dead. These replace them.",
    "resent": "Here is a fresh pair of bot API keys. The previous pair was revoked when this was sent.",
}


def exchange_example(base_url: str, scope: str) -> str:
    return (
        f"curl -X POST {base_url.rstrip('/')}/api/v1/auth/exchange \\\n"
        f'  -H "Authorization: Bearer <primary key>" \\\n'
        f'  -H "X-FOS-2FA: <emailed key>"\n\n'
        f"That returns a short-lived token. Send it as:\n"
        f'  Authorization: Bearer fos_s1_...'
    )


def primary_email_body(*, user, household, scope: str, raw_key: str, base_url: str, reason: str) -> str:
    who = (getattr(user, "name", None) or getattr(user, "username", None) or "there").strip()
    house = (getattr(household, "name", None) or "your household").strip()
    box = login_inbox(user)
    return "\n".join(
        [
            f"Hi {who},",
            "",
            REASON_LEAD.get(reason, "These keys were issued for your bot account."),
            "",
            f"Scope: {scope_label(scope)}",
            f"Household: {house}",
            "",
            f"LOGIN KEY (one half of the pair):",
            f"  {raw_key}",
            "",
            "The other half went to your 2FA inbox, not this address. You need both.",
            "",
            "Trade them for a session token:",
            "",
            exchange_example(base_url, scope),
            "",
            f"Sent to {box}. If this is not your bot, ignore this email and tell a leader.",
        ]
    )


def twofa_email_body(*, user, household, scope: str, raw_key: str, base_url: str, reason: str) -> str:
    who = (getattr(user, "name", None) or getattr(user, "username", None) or "there").strip()
    house = (getattr(household, "name", None) or "your household").strip()
    box = twofa_inbox(user)
    return "\n".join(
        [
            f"Hi {who},",
            "",
            REASON_LEAD.get(reason, "These keys were just issued for your bot account."),
            "",
            f"Scope: {scope_label(scope)}",
            f"Household: {house}",
            "",
            "SECOND FACTOR KEY (the half that is NOT the login key):",
            f"  {raw_key}",
            "",
            "Send it once, as X-FOS-2FA, when trading keys for a session token.",
            "",
            exchange_example(base_url, scope),
            "",
            f"Sent to {box}. Nobody else should be reading this inbox.",
        ]
    )


def deliver_pair(*, user, household, scope: str, pair: dict, base_url: str, reason: str = "issued") -> tuple[bool, str]:
    """Mail each half of the pair to its own inbox. Returns (all_ok, detail)."""
    from app.utils.mail import send_mail

    reason = reason if reason in REASONS else "issued"
    scope = normalize_scope(scope)
    lines: list[str] = []
    all_ok = True
    for role, inbox, builder, subject in (
        ("primary", login_inbox(user), primary_email_body, REASON_SUBJECT[reason]),
        ("twofa", twofa_inbox(user), twofa_email_body, REASON_SUBJECT[reason] + " — second factor"),
    ):
        if not inbox:
            all_ok = False
            lines.append(f"{role}: no inbox on file")
            continue
        ok, msg = send_mail(
            inbox,
            f"{subject} ({scope_label(scope)})",
            builder(
                user=user,
                household=household,
                scope=scope,
                raw_key=pair[role],
                base_url=base_url,
                reason=reason,
            ),
            household=getattr(user, "household", None) or household,
        )
        if not ok:
            all_ok = False
        lines.append(f"{role} -> {inbox}: {'sent' if ok else msg}")
    return all_ok, "; ".join(lines)


def issue_keys(
    user,
    scope: str,
    *,
    household=None,
    base_url: str = "",
    label: str = "",
    created_by=None,
    days: int = DEFAULT_DAYS,
    reason: str = "issued",
) -> tuple[bool, str, dict]:
    """Rotate the pair on this scope and mail both halves out. The one call."""
    from app.builddb.table_households import Household

    hh = household or getattr(user, "household", None) or Household.query.get(
        int(getattr(user, "household_id", 0) or 0)
    )
    ok, msg, pair = mint_pair(
        user, scope, label=label, created_by=created_by, days=days
    )
    if not ok:
        return False, msg, {}
    mailed, detail = deliver_pair(
        user=user,
        household=hh,
        scope=normalize_scope(scope),
        pair=pair,
        base_url=base_url,
        reason=reason,
    )
    db.session.commit()
    pair["mailed"] = mailed
    pair["mail_detail"] = detail
    return True, detail, pair