"""Per-household BYOK. Encrypted at rest in households.settings_json."""
from __future__ import annotations

from sqlalchemy.orm.attributes import flag_modified

from app.builddb.builddb import db
from app.utils.ai import (
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    PROVIDERS,
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
    model = (blob.get("model") or "").strip()
    base = (blob.get("base_url") or "").strip()
    enabled = blob.get("enabled")
    chat = blob.get("chat")
    cfg = _pack(
        provider,
        key,
        model,
        base,
        source="household",
        from_env=False,
    )
    if enabled is False:
        cfg["ready"] = False
        cfg["enabled"] = False
    else:
        cfg["enabled"] = True
    cfg["chat"] = False if chat is False else True
    cfg["key_hint"] = mask_secret(key)
    raw_backup = blob.get("backup") if isinstance(blob.get("backup"), dict) else {}
    bkey = _decrypt_key(raw_backup.get("api_key") or "")
    cfg["backup_has_key"] = bool(bkey)
    cfg["backup_key_hint"] = mask_secret(bkey) if bkey else ""
    cfg["backup"] = None
    if bkey:
        bprov = normalize_provider(raw_backup.get("provider") or "groq")
        cfg["backup"] = _pack(
            bprov,
            bkey,
            (raw_backup.get("model") or "").strip(),
            (raw_backup.get("base_url") or "").strip(),
            source="household",
            from_env=False,
        )
    return cfg


def save_household_ai(
    household,
    *,
    provider: str,
    model: str = "",
    api_key: str = "",
    base_url: str = "",
    enabled: bool = True,
    chat=None,
    clear_key: bool = False,
    backup_provider: str = "",
    backup_model: str = "",
    backup_api_key: str = "",
    clear_backup: bool = False,
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
    if chat is None:
        chat_on = False if prev.get("chat") is False else True
    else:
        chat_on = bool(chat)
    prev_backup = prev.get("backup") if isinstance(prev.get("backup"), dict) else {}
    if clear_backup:
        backup = {}
    else:
        stored_backup = prev_backup.get("api_key") or ""
        if (backup_api_key or "").strip():
            stored_backup = encrypt_text((backup_api_key or "").strip()) or ""
        if stored_backup:
            bprov = normalize_provider(backup_provider or prev_backup.get("provider") or "groq")
            bspec = PROVIDERS.get(bprov) or PROVIDERS["groq"]
            bmodel = (backup_model or prev_backup.get("model") or "").strip()
            if not bmodel:
                bmodel = bspec["models"][0] if bspec.get("models") else ""
            backup = {
                "provider": bprov,
                "model": bmodel[:120],
                "api_key": stored_backup,
            }
        else:
            backup = {}
    settings["ai"] = {
        "provider": provider,
        "model": model[:120],
        "api_key": stored_key,
        "base_url": base_url[:300],
        "enabled": bool(enabled),
        "chat": chat_on,
        "backup": backup,
    }
    household.settings_json = settings
    flag_modified(household, "settings_json")
    db.session.commit()
    return household_config(household)


def chat_on(household) -> bool:
    """Ask window defaults on. Only off if they turned it off."""
    blob = _ai_blob(household)
    return False if blob.get("chat") is False else True


def ask_available(household, user=None) -> bool:
    from app.utils.permissions import role_of

    if household is None:
        return False
    if user is not None and role_of(user) == "child":
        return False
    cfg = household_config(household)
    if not cfg.get("has_key") or not cfg.get("enabled"):
        return False
    return chat_on(household)
