"""Family OS bot API — /api/v1 blueprint, plumbing, and the auth surface.

Two scopes, both carried by the key prefix:

    fos_bot_    read + write vehicles / notes / attachments / inventory / records
    fos_vault_  read-only vault

The resource views live beside this file:
`bot_api_house` (fos_bot_) and `bot_api_vault` (fos_vault_).

No delete in v1. Every call is audited to `bot_api_audit`, and a write also
lands in the household's What-happened log so the family can see the bot
working in the same place they see a kid's tap.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, g, jsonify, request

from app.builddb.builddb import db
from app.utils.bot_api_keys import SCOPE_ALL, SCOPE_VAULT
from app.utils.bot_api_auth import (
    api_error,
    api_household_id,
    api_user,
    audit,
    bot_api,
    bot_api_any,
    exchange_keys,
    iso,
    utcnow,
)

bot_api_bp = Blueprint("bot_api", __name__, url_prefix="/api/v1")

# The scope literals live in bot_api_keys so the mint path and the routes can
# never drift apart.
BOT = SCOPE_ALL
VAULT = SCOPE_VAULT

SCOPE_SURFACE = {
    BOT: {
        "label": "House (read + write)",
        "read": [
            "GET /api/v1/helper",
            "GET /api/v1/me",
            "GET /api/v1/whoami",
            "GET /api/v1/vehicles",
            "GET /api/v1/vehicles/<id>",
            "GET /api/v1/notes",
            "GET /api/v1/notes/<id>",
            "GET /api/v1/notes/<id>/files",
            "GET /api/v1/files/<id>",
            "GET /api/v1/inventory",
            "GET /api/v1/inventory/<id>",
            "GET /api/v1/records",
            "GET /api/v1/records/<id>",
            "GET /api/v1/cases",
            "GET /api/v1/basket",
            "GET /api/v1/reminders",
            "GET /api/v1/tools",
            "GET /api/v1/house",
            "GET /api/v1/items/<id>/logs",
            "GET /api/v1/photos",
            "GET /api/v1/photos/<id>",
            "GET /api/v1/find?q=",
            "GET /api/v1/people",
            "GET /api/v1/ask",
            "GET /api/v1/activity",
            "GET /api/v1/vault",
        ],
        "write": [
            "POST /api/v1/vehicles",
            "PATCH /api/v1/vehicles/<id>",
            "POST /api/v1/notes",
            "PATCH /api/v1/notes/<id>",
            "POST /api/v1/notes/<id>/files",
            "POST /api/v1/inventory",
            "PATCH /api/v1/inventory/<id>",
            "POST /api/v1/records",
            "PATCH /api/v1/records/<id>",
            "POST /api/v1/basket",
            "POST /api/v1/basket/<id>/done",
            "POST /api/v1/reminders",
            "POST /api/v1/reminders/<id>/done",
            "POST /api/v1/items/<id>/logs",
        ],
        "delete": "not in v1",
    },
    VAULT: {
        "label": "Vault (read-only)",
        "read": [
            "GET /api/v1/helper",
            "GET /api/v1/me",
            "GET /api/v1/whoami",
            "GET /api/v1/vault",
            "GET /api/v1/vault/<id>",
        ],
        "write": [],
        "delete": "not in v1",
    },
}


# ------------------------------------------------------------- plumbing


@bot_api_bp.after_request
def _audit_call(response):
    """One audit row per API call, written with the final status code."""
    if getattr(g, "bot_api_audited", False):
        return response
    try:
        g.bot_api_audited = True
        user = api_user()
        session = getattr(g, "bot_session", None)
        audit(
            event="call",
            status=response.status_code,
            outcome="ok" if response.status_code < 400 else "error",
            user_id=getattr(user, "id", None),
            key_id=getattr(g, "bot_key_id", None),
            session_id=getattr(session, "id", None),
            scope=getattr(session, "scope", None),
            household_id=getattr(user, "household_id", None),
        )
    except Exception:
        pass
    return response


def ok(payload=None, status: int = 200):
    out = {"ok": True}
    if isinstance(payload, dict):
        out.update(payload)
    resp = jsonify(out)
    resp.status_code = status
    return resp


def limit_arg(default: int = 50, ceiling: int = 200) -> int:
    try:
        want = int(request.args.get("limit") or default)
    except (TypeError, ValueError):
        want = default
    return max(1, min(want, ceiling))


def offset_arg() -> int:
    try:
        want = int(request.args.get("offset") or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, want)


def page(rows, total: int | None = None) -> dict:
    """Standard list envelope so a caller can tell there is more to fetch."""
    out = {"count": len(rows)}
    if total is not None:
        out["total"] = total
        out["has_more"] = offset_arg() + len(rows) < total
    return out


def as_str(data: dict, key: str, maxlen: int = 500, default=None):
    raw = data.get(key)
    if raw is None:
        return default
    text = str(raw).strip()
    if not text:
        return default
    return text[:maxlen]


def as_int(data: dict, key: str, default=None):
    raw = data.get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def as_date(data: dict, key: str, default=None):
    raw = as_str(data, key, 10)
    if not raw:
        return default
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return default


def as_dec(data: dict, key: str, default=None):
    raw = data.get(key)
    if raw is None or raw == "":
        return default
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return default


def as_num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def note_activity(
    action: str,
    summary: str,
    *,
    target_table: str | None = None,
    target_id: int | None = None,
    item_id: int | None = None,
    detail=None,
    commit: bool = True,
):
    """Put the bot in the family's What-happened log.

    `app.utils.activity.record` reads flask_login's current_user, which is
    anonymous on a Bearer request, so the row is written here against the
    session's household instead.
    """
    try:
        from app.builddb.table_household_activity import HouseholdActivity

        user = api_user()
        db.session.add(
            HouseholdActivity(
                household_id=api_household_id(),
                user_id=getattr(user, "id", None),
                action=(action or "api.do")[:40],
                summary=(summary or "A bot made a change")[:240],
                target_table=target_table,
                target_id=target_id,
                item_id=item_id,
                new_json=detail if isinstance(detail, dict) else None,
                reversible=False,
            )
        )
        if commit:
            db.session.commit()
    except Exception:
        db.session.rollback()


# ----------------------------------------------------------------- auth


@bot_api_bp.route("/auth/present", methods=["POST"])
@bot_api(BOT, exchange=True)
def present():
    """Login key in. A one-hour 2FA key goes to the other inbox."""
    from app.utils.bot_api_auth import present_key

    g.bot_api_audited = True
    return present_key()


@bot_api_bp.route("/auth/exchange", methods=["POST"])
@bot_api(BOT, exchange=True)
def exchange():
    """Spend the one-hour 2FA key for a session token. The login key stays."""
    g.bot_api_audited = True
    return exchange_keys()


def _whoami_payload():
    from app.utils.bot_api_access import account_snapshot
    from app.utils.bot_api_keys import key_status

    user = api_user()
    session = g.bot_session
    return ok(
        {
            "scope": session.scope,
            "scope_label": SCOPE_SURFACE.get(session.scope, {}).get("label", ""),
            "bot": (getattr(user, "username", None) or ""),
            "household": (getattr(getattr(user, "household", None), "handle", None) or ""),
            "session_expires_at": iso(session.expires_at),
            "helper": "GET /api/v1/helper",
            "me": "GET /api/v1/me",
            "account": account_snapshot(),
            "available": SCOPE_SURFACE.get(session.scope, {}),
            "keys": [
                {
                    "scope": p["scope"],
                    "live": p["live"],
                    "expires_at": iso(p["expires_at"]),
                    "tails": p["tails"],
                }
                for p in key_status(user)
            ],
        }
    )


def _revoke_session():
    session = g.bot_session
    session.revoked_at = utcnow()
    db.session.add(session)
    db.session.commit()
    return ok({"revoked": True})


@bot_api_bp.route("/whoami")
@bot_api_bp.route("/me")
@bot_api_any(BOT, VAULT)
def whoami():
    return _whoami_payload()


@bot_api_bp.route("/helper")
@bot_api_bp.route("/help")
@bot_api_any(BOT, VAULT)
def helper():
    """The route map. Same shape as AEGIS /api/bot/help: lines live in data."""
    from app.utils.bot_api_help import help_for

    body = help_for(g.bot_session.scope)
    return ok({"greeting": body["greeting"], "data": body})


@bot_api_bp.route("/auth/revoke", methods=["POST"])
@bot_api_any(BOT, VAULT, write=True)
def revoke():
    return _revoke_session()


@bot_api_bp.route("/auth/reset", methods=["POST"])
@bot_api_any(BOT, VAULT, write=True)
def reset_login_key():
    """Session only. Mail a new login key to the login inbox and end this session."""
    from app.utils.bot_api_keys import reset_own_key

    g.bot_api_audited = True
    user = api_user()
    session = g.bot_session
    ok_reset, detail = reset_own_key(
        user,
        session.scope,
        base_url=request.host_url.rstrip("/"),
    )
    if not ok_reset:
        audit(
            event="reset",
            status=502,
            outcome="mail_failed",
            user_id=getattr(user, "id", None),
            key_id=getattr(session, "key_id", None),
            session_id=getattr(session, "id", None),
            scope=getattr(session, "scope", None),
        )
        return api_error(
            "The new login key could not be emailed, so this key and session still work.",
            502,
            "mail_failed",
        )
    audit(
        event="reset",
        status=200,
        outcome="mailed",
        user_id=getattr(user, "id", None),
        key_id=getattr(session, "key_id", None),
        session_id=getattr(session, "id", None),
        scope=getattr(session, "scope", None),
    )
    return ok(
        {
            "reset": True,
            "expires": "never",
            "detail": (
                "A new login key was emailed to the login inbox. It does not expire. "
                "This session and the previous login key are finished. "
                "Sign in again with the new key."
            ),
        }
    )


@bot_api_bp.route("/meta")
@bot_api_any(BOT, VAULT)
def meta():
    """The documented v1 surface, plus both scopes for reference."""
    scope = g.bot_session.scope
    return ok(
        {
            "version": "v1",
            "scope": scope,
            "available": SCOPE_SURFACE.get(scope, {}),
            "scopes": SCOPE_SURFACE,
        }
    )