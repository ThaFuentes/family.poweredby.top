"""Owner-console settings. Secrets are Fernet-encrypted at rest."""
from __future__ import annotations

from app.builddb.builddb import db
from app.builddb.table_platform_audit import PlatformAudit
from app.builddb.table_platform_settings import PlatformSetting
from app.utils.crypto import decrypt_text, encrypt_text, looks_encrypted

SECRET_KEYS = frozenset({"smtp_password", "ai_api_key"})
_SETTING_TTL = 300


def get_setting(key: str, default: str = "") -> str:
    from app.utils.hot_cache import get as cache_get, put as cache_put

    ck = f"setting:{key}"
    wrapped = cache_get(ck)
    if isinstance(wrapped, dict) and "ok" in wrapped:
        if not wrapped.get("ok"):
            return default
        return wrapped.get("v") if wrapped.get("v") is not None else default
    row = PlatformSetting.query.filter_by(key=key).first()
    if row is None or row.value is None:
        cache_put(ck, {"ok": False}, _SETTING_TTL)
        return default
    val = str(row.value)
    if row.is_secret or looks_encrypted(val):
        val = decrypt_text(val) or default
    cache_put(ck, {"ok": True, "v": val}, _SETTING_TTL)
    return val


def set_setting(key: str, value: str | None, secret: bool | None = None) -> None:
    is_secret = bool(SECRET_KEYS.__contains__(key) if secret is None else secret)
    raw = "" if value is None else str(value)
    stored = encrypt_text(raw) if is_secret and raw else raw
    row = PlatformSetting.query.filter_by(key=key).first()
    if row is None:
        row = PlatformSetting(key=key, value=stored, is_secret=is_secret)
        db.session.add(row)
    else:
        row.value = stored
        row.is_secret = is_secret
    db.session.commit()
    try:
        from app.utils.hot_cache import delete as cache_delete

        cache_delete(f"setting:{key}")
    except Exception:
        pass


def mask_secret(value: str) -> str:
    k = (value or "").strip()
    if not k:
        return ""
    if len(k) < 8:
        return "set"
    return k[:4] + "…" + k[-4:]


def audit(action: str, owner_id=None, household_id=None, detail=None, ip=None) -> None:
    db.session.add(
        PlatformAudit(
            owner_id=owner_id,
            action=action,
            household_id=household_id,
            detail_json=detail if isinstance(detail, dict) else None,
            ip=(ip or "")[:64] or None,
        )
    )
    db.session.commit()
