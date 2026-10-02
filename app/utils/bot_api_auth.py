"""Bearer auth for the bot API.

Normal traffic sends one header:

    Authorization: Bearer fos_s1_<session token>

The token came from one exchange call that spent both halves of a key pair,
so the emailed second factor is not on the wire afterwards.

Every route is gated by three checks, in this order, all of them before the
view runs: HTTPS, a live non-revoked session for an active bot in an active
household, then a per-route scope match. Rate limits are DB-backed because
Passenger runs several workers and an in-memory counter resets per process.

Denials are deliberately vague (401 for "no/!bad token", 403 for "your key
cannot do this") so a probe cannot use the API to map which keys exist.
"""
from __future__ import annotations

import functools
import os
from datetime import datetime, timedelta, timezone

from flask import current_app, g, jsonify, request

from app.builddb.builddb import db
from app.utils import bot_api_keys as keys

SESSION_TTL_SECONDS = 3600
SESSION_TTL_MAX_SECONDS = 24 * 3600
RATE_WINDOW_SECONDS = 60
DEFAULT_RATE_PER_WINDOW = 240
WRITE_RATE_PER_WINDOW = 60
EXCHANGE_RATE_PER_WINDOW = 20
AUDIT_KEEP_DAYS = 90

AUTH_HEADER = "Authorization"
TWOFA_HEADER = "X-FOS-2FA"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utcnow() -> datetime:
    """Naive UTC, same convention as the rest of the schema."""
    return _utcnow()


def _naive(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if getattr(dt, "tzinfo", None) is not None else dt


# ------------------------------------------------------------ responses


def api_error(message: str, status: int = 400, code: str = "", **extra):
    body = {"error": message, "status": status}
    if code:
        body["code"] = code
    if extra:
        body.update(extra)
    resp = jsonify(body)
    resp.status_code = status
    # Credentials must never sit in a shared cache.
    resp.headers["Cache-Control"] = "no-store"
    return resp





# --------------------------------------------------------------- client


def client_ip() -> str:
    try:
        from poweredbytop.utils.helpers import get_real_ip

        return (get_real_ip(request) or "")[:64]
    except Exception:
        return (request.remote_addr or "")[:64]


def user_agent() -> str:
    return (request.headers.get("User-Agent") or "")[:200]


# ---------------------------------------------------------------- audit


def audit(
    *,
    event: str = "call",
    status: int | None = None,
    outcome: str = "",
    user_id=None,
    key_id=None,
    session_id=None,
    scope: str | None = None,
    detail=None,
    household_id=None,
):
    """One machine-traffic row. Never raises into the request."""
    try:
        from app.builddb.table_bot_api_audit import BotApiAudit

        hid = household_id
        if hid is None:
            actor = getattr(g, "bot_user", None)
            hid = getattr(actor, "household_id", None)
        row = BotApiAudit(
            household_id=int(hid) if hid else None,
            user_id=int(user_id) if user_id else None,
            key_id=int(key_id) if key_id else None,
            session_id=int(session_id) if session_id else None,
            scope=(scope or None),
            event=(event or "call")[:40],
            method=(request.method or "")[:10] if request else None,
            path=(request.path or "")[:160] if request else None,
            status=int(status) if status else None,
            outcome=(outcome or None) if outcome else None,
            ip=client_ip() if request else None,
            user_agent=user_agent() if request else None,
            detail_json=detail if isinstance(detail, dict) else None,
        )
        db.session.add(row)
        db.session.commit()
        return row
    except Exception as exc:
        try:
            db.session.rollback()
        except Exception:
            pass
        try:
            print(f"[bot-api] audit write failed: {exc}", flush=True)
        except Exception:
            pass
        return None


# ----------------------------------------------------------- rate limits


def _window_start() -> datetime:
    now = _utcnow()
    return now.replace(second=0, microsecond=0)


def bump_rate(subject: str, limit: int, window_seconds: int = RATE_WINDOW_SECONDS) -> tuple[bool, int]:
    """Fixed window. (allowed, seconds_to_retry)."""
    from app.builddb.table_bot_api_rate import BotApiRate

    now = _utcnow()
    start = now.replace(second=0, microsecond=0) if window_seconds == RATE_WINDOW_SECONDS else now
    try:
        row = (
            BotApiRate.query.filter_by(subject=subject, window_start=start)
            .with_for_update()
            .first()
        )
        if row is None:
            row = BotApiRate(subject=subject, window_start=start, count=1)
            db.session.add(row)
        else:
            row.count = int(row.count or 0) + 1
        db.session.commit()
        count = int(row.count or 0)
    except Exception:
        db.session.rollback()
        # A rate-limit table outage must not take the API down.
        return True, 0
    if count > max(1, int(limit or 1)):
        retry = max(1, int((start + timedelta(seconds=window_seconds) - now).total_seconds()))
        return False, retry
    return True, 0


def _cfg_int(name: str, fallback: int) -> int:
    """Tolerant config read: an unset or None value falls back."""
    try:
        value = current_app.config.get(name)
    except Exception:
        return fallback
    if value is None or value == "":
        return fallback
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def limit_for(scope: str, *, write: bool = False, exchange: bool = False) -> int:
    if exchange:
        return _cfg_int("BOT_API_EXCHANGE_RATE", EXCHANGE_RATE_PER_WINDOW)
    if write:
        return _cfg_int("BOT_API_WRITE_RATE", WRITE_RATE_PER_WINDOW)
    return _cfg_int("BOT_API_READ_RATE", DEFAULT_RATE_PER_WINDOW)


def ip_limit() -> int:
    return _cfg_int("BOT_API_IP_RATE", 1200)


def enforce_rate(*, subject: str, limit: int, scope: str, event: str = "rate") -> tuple[bool, object]:
    """(allowed, response_to_return_when_not)."""
    allowed, retry = bump_rate(subject, limit)
    if allowed:
        return True, None
    audit(
        event="rate_limit",
        status=429,
        outcome=event,
        scope=scope,
        detail={"subject": subject, "limit": limit},
    )
    resp = api_error("Too many requests. Slow down.", 429, "rate_limited")
    resp.headers["Retry-After"] = str(max(1, int(retry or 1)))
    return False, resp


# ----------------------------------------------------------------- https


def https_required() -> bool:
    """Off only when the deployment explicitly opts in (local tests)."""
    try:
        if current_app.config.get("BOT_API_ALLOW_INSECURE"):
            return False
    except Exception:
        pass
    if (os.getenv("BOT_API_ALLOW_INSECURE") or "").strip().lower() in ("1", "true", "yes", "on"):
        return False
    try:
        return bool(request.is_secure)
    except Exception:
        return False


# --------------------------------------------------------------- tokens


def bearer_token() -> str:
    raw = (request.headers.get(AUTH_HEADER) or "").strip()
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return ""


def twofa_token() -> str:
    return (request.headers.get(TWOFA_HEADER) or "").strip()


def new_session_token() -> str:
    import secrets

    body = secrets.token_urlsafe(32).replace("-", "").replace("_", "")
    return f"{keys.SESSION_PREFIX}{body}"


def session_ttl() -> int:
    try:
        want = int(current_app.config.get("BOT_API_SESSION_TTL", SESSION_TTL_SECONDS))
    except Exception:
        want = SESSION_TTL_SECONDS
    return max(300, min(want, SESSION_TTL_MAX_SECONDS))


# ---------------------------------------------------------------- lookup


def _household_ok(user) -> bool:
    hh = getattr(user, "household", None)
    if hh is None:
        from app.builddb.table_households import Household

        hh = Household.query.get(int(getattr(user, "household_id", 0) or 0))
    if hh is None:
        return False
    return bool(getattr(hh, "is_active", True))


def resolve_session(token: str):
    """(session, user, why-not). Token hash only — nothing else is trusted."""
    from app.builddb.table_bot_api_sessions import BotApiSession
    from app.builddb.table_users import User

    if not token or not token.startswith(keys.SESSION_PREFIX):
        return None, None, "bad_token"
    row = (
        BotApiSession.query.filter_by(token_hash=keys.hash_key(token))
        .order_by(BotApiSession.id.desc())
        .first()
    )
    if row is None:
        return None, None, "bad_token"
    if row.revoked_at:
        return None, None, "revoked"
    exp = _naive(row.expires_at)
    if exp and exp < _utcnow():
        return None, None, "expired"
    user = User.query.get(int(row.user_id or 0))
    if user is None or not bool(getattr(user, "is_active", True)):
        return None, None, "inactive_user"
    if not bool(getattr(user, "is_bot", False)):
        return None, None, "not_bot"
    if not _household_ok(user):
        return None, None, "house_paused"
    return row, user, ""


def touch_session(row) -> None:
    try:
        row.last_used_at = _utcnow()
        row.request_count = int(row.request_count or 0) + 1
        db.session.add(row)
        db.session.commit()
    except Exception:
        db.session.rollback()


# ------------------------------------------------------------ decorators


def bot_api(scope: str, *, write: bool = False, exchange: bool = False):
    """Gate a route: HTTPS -> session -> scope -> rate limit."""
    return _gate((keys.normalize_scope(scope),), write=write, exchange=exchange)


def bot_api_any(*scopes: str, write: bool = False):
    """Gate a route that is valid for any of several scopes.

    Used only for the scope-agnostic endpoints (whoami / meta / revoke).
    Registering the same path twice with different scopes does not work —
    Werkzeug matches one rule per path, so one scope would always win.
    """
    wanted = tuple(keys.normalize_scope(s) for s in scopes) or (keys.normalize_scope(BOT),)
    return _gate(wanted, write=write, exchange=False)


def _gate(wanted: tuple[str, ...], *, write: bool = False, exchange: bool = False):
    label = ",".join(wanted)

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            # https_required() is True when HTTPS is mandatory.
            if https_required():
                audit(event="denied", status=403, outcome="https_required", scope=label)
                return api_error(
                    "The bot API is HTTPS only.", 403, "https_required"
                )
            token = bearer_token()
            if exchange:
                return fn(*args, **kwargs)
            if not token:
                audit(event="denied", status=401, outcome="missing_token", scope=label)
                return api_error("Send Authorization: Bearer <token>.", 401, "missing_token")

            row, user, why = resolve_session(token)
            if row is None:
                audit(event="denied", status=401, outcome=why, scope=label)
                return api_error("That token is not valid.", 401, "invalid_token")

            # The scope is read off the session, then matched per route.
            if keys.normalize_scope(row.scope) not in wanted:
                audit(
                    event="denied",
                    status=403,
                    outcome="scope_mismatch",
                    user_id=user.id,
                    key_id=row.key_id,
                    session_id=row.id,
                    scope=row.scope,
                    detail={"wanted": label},
                )
                return api_error(
                    "This key cannot use that route.", 403, "scope_denied"
                )

            allowed, too_many = enforce_rate(
                subject=f"k:{row.id}",
                limit=limit_for(row.scope, write=write),
                scope=row.scope,
            )
            if not allowed:
                return too_many
            allowed, too_many = enforce_rate(
                subject=f"ip:{client_ip()}",
                limit=ip_limit(),
                scope=row.scope,
            )
            if not allowed:
                return too_many

            g.bot_user = user
            g.bot_session = row
            g.bot_key_id = row.key_id
            touch_session(row)
            return fn(*args, **kwargs)

        return wrapper

    return deco


# ------------------------------------------------------------- helpers


def api_user():
    return getattr(g, "bot_user", None)


def api_session():
    return getattr(g, "bot_session", None)


def api_household_id() -> int:
    user = api_user()
    return int(getattr(user, "household_id", 0) or 0) if user else 0


def api_scope(model, include_removed: bool = False):
    """Household-scoped query for a Bearer request.

    `app.utils.household.scoped` reads flask_login's current_user, which is
    anonymous here, so the API filters on the session's household directly.
    """
    hid = api_household_id()
    q = model.query.filter_by(household_id=hid)
    if not include_removed and getattr(model, "removed_at", None) is not None:
        q = q.filter(model.removed_at.is_(None))
    return q


def iso(dt) -> str:
    when = _naive(dt)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ") if when else None


def iso_date(dt) -> str:
    when = _naive(dt)
    return when.strftime("%Y-%m-%d") if when else None


def body() -> dict:
    """JSON body, or an empty dict rather than an exception."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


# ------------------------------------------------------------- exchange


def _exchange_denied(outcome: str, *, status: int = 401, code: str = "invalid_key_pair", **detail):
    audit(event="exchange", status=status, outcome=outcome, detail=detail or None)
    return api_error(
        "That key pair is not valid.", status, code
    )


def exchange_keys():
    """Spend one (primary, twofa) pair and hand back a session token.

    The pair stays usable until it is reset — it is a long-lived second
    factor, not a one-shot code — but every exchange is audited and a reset
    kills the pair and all its sessions.
    """
    primary = bearer_token()
    second = twofa_token()

    ip = client_ip()
    allowed, _retry = bump_rate(f"x:{ip}", limit_for("", exchange=True))
    if not allowed:
        audit(event="rate_limit", status=429, outcome="exchange_ip", detail={"ip": ip})
        resp = api_error("Too many exchange attempts. Wait a minute.", 429, "rate_limited")
        resp.headers["Retry-After"] = "60"
        return resp

    if not primary or not second:
        audit(event="exchange", status=400, outcome="missing_pair")
        return api_error(
            "Send the login key as Authorization: Bearer and the emailed key as X-FOS-2FA.",
            400,
            "missing_key",
        )
    if not keys.scope_of(primary):
        audit(event="exchange", status=400, outcome="bad_prefix")
        return api_error("That login key is not a Family OS bot key.", 400, "bad_prefix")

    # Brute-force guard on the second factor specifically.
    allowed, _retry = bump_rate(f"x2:{keys.hash_key(second)}", limit_for("", exchange=True))
    if not allowed:
        audit(event="rate_limit", status=429, outcome="exchange_twofa")
        resp = api_error("Too many attempts on that key.", 429, "rate_limited")
        resp.headers["Retry-After"] = "60"
        return resp

    prow = keys.find_key(primary)
    srow = keys.find_key(second)
    if prow is None or srow is None:
        return _exchange_denied("unknown_key")
    if prow.id == srow.id:
        return _exchange_denied("same_key_twice")
    if keys.normalize_scope(prow.scope) != keys.normalize_scope(srow.scope):
        return _exchange_denied("scope_mismatch", detail={"claimed": prow.scope})
    if prow.key_role != "primary" or srow.key_role != "twofa":
        return _exchange_denied("roles_swapped")
    if int(prow.user_id or 0) != int(srow.user_id or 0):
        return _exchange_denied("different_bots")
    if int(prow.household_id or 0) != int(srow.household_id or 0):
        return _exchange_denied("different_households")
    if prow.pair_id != srow.pair_id:
        return _exchange_denied("different_pairs")

    ok, why = keys.key_state(prow)
    if not ok:
        return _exchange_denied(why, detail={"role": "primary"})
    ok, why = keys.key_state(srow)
    if not ok:
        return _exchange_denied(why, detail={"role": "twofa"})

    from app.builddb.table_users import User

    user = User.query.get(int(prow.user_id or 0))
    if user is None or not bool(getattr(user, "is_active", True)):
        return _exchange_denied("inactive_user", status=403, code="inactive_user")
    if not bool(getattr(user, "is_bot", False)):
        return _exchange_denied("not_bot", status=403, code="not_bot")
    if not _household_ok(user):
        return _exchange_denied("house_paused", status=403, code="house_paused")

    # A bot whose security setup regressed loses API access with it.
    gaps = keys.bot_api_blockers(user)
    if gaps:
        audit(
            event="exchange",
            status=403,
            outcome="setup_incomplete",
            user_id=user.id,
            key_id=prow.id,
            scope=prow.scope,
            detail={"gaps": gaps},
        )
        return api_error(
            keys.blocker_message(user), 403, "setup_incomplete"
        )

    token = new_session_token()
    ttl = session_ttl()
    from app.builddb.table_bot_api_sessions import BotApiSession

    row = BotApiSession(
        household_id=int(prow.household_id or 0),
        user_id=int(user.id),
        key_id=int(prow.id or 0),
        scope=prow.scope,
        pair_id=prow.pair_id,
        token_hash=keys.hash_key(token),
        token_tail=keys.key_tail(token, 10),
        issued_at=_utcnow(),
        expires_at=_utcnow() + timedelta(seconds=ttl),
        request_count=0,
        created_ip=client_ip(),
    )
    db.session.add(row)
    keys.mark_used(prow)
    keys.mark_used(srow)
    db.session.commit()

    audit(
        event="exchange",
        status=200,
        outcome="granted",
        user_id=user.id,
        key_id=prow.id,
        session_id=row.id,
        scope=prow.scope,
        detail={"expires_in": ttl},
    )

    return jsonify(
        {
            "token": token,
            "token_type": "Bearer",
            "expires_in": ttl,
            "expires_at": iso(row.expires_at),
            "scope": prow.scope,
            "scope_label": keys.scope_label(prow.scope),
            "bot": (getattr(user, "username", None) or ""),
            "household": (getattr(getattr(user, "household", None), "handle", None) or ""),
        }
    )