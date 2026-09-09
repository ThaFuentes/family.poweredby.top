"""Per-household BYOK. Encrypted at rest in households.settings_json."""
from __future__ import annotations

from sqlalchemy.orm.attributes import flag_modified

from app.builddb.builddb import db
from app.utils.ai import (
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    PROVIDERS,
    _env_key_for,
    _pack,
    normalize_provider,
)
from app.utils.crypto import decrypt_text, encrypt_text, looks_encrypted
from app.utils.platform_settings import mask_secret


def _ai_blob(household) -> dict:
    settings = household.settings_json if isinstance(getattr(household, "settings_json", None), dict) else {}
    blob = settings.get("ai") if isinstance(settings, dict) else None
    return dict(blob) if isinstance(blob, dict) else {}


def _decrypt_key(stored: str) -> str:
    raw = (stored or "").strip()
    if not raw:
        return ""
    if looks_encrypted(raw):
        return (decrypt_text(raw) or "").strip()
    return raw


def household_config(household) -> dict:
    blob = _ai_blob(household)
    provider = normalize_provider(blob.get("provider") or DEFAULT_PROVIDER)
    key = _decrypt_key(blob.get("api_key") or "")
    from_env = False
    if not key:
        key = _env_key_for(provider)
        from_env = bool(key)
    model = (blob.get("model") or "").strip()
    base = (blob.get("base_url") or "").strip()
    enabled = blob.get("enabled")
    cfg = _pack(
        provider,
        key,
        model,
        base,
        source="household",
        from_env=from_env,
    )
    if enabled is False:
        cfg["ready"] = False
        cfg["enabled"] = False
    else:
        cfg["enabled"] = True
    cfg["key_hint"] = mask_secret(key)
    return cfg


def save_household_ai(
    household,
    *,
    provider: str,
    model: str = "",
    api_key: str = "",
    base_url: str = "",
    enabled: bool = True,
    clear_key: bool = False,
) -> dict:
    settings = dict(household.settings_json or {})
    prev = dict(settings.get("ai") or {}) if isinstance(settings.get("ai"), dict) else {}
    provider = normalize_provider(provider)
    spec = PROVIDERS.get(provider) or PROVIDERS[DEFAULT_PROVIDER]
    model = (model or "").strip() or (spec["models"][0] if spec["models"] else DEFAULT_MODEL)
    base_url = (base_url or "").strip().rstrip("/")
    stored_key = prev.get("api_key") or ""
    if clear_key:
        stored_key = ""
    elif (api_key or "").strip():
        stored_key = encrypt_text((api_key or "").strip()) or ""
    settings["ai"] = {
        "provider": provider,
        "model": model[:120],
        "api_key": stored_key,
        "base_url": base_url[:300],
        "enabled": bool(enabled),
    }
    household.settings_json = settings
    flag_modified(household, "settings_json")
    db.session.commit()
    return household_config(household)
