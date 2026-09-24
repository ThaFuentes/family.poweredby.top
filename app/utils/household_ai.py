"""Per-household BYOK. Encrypted at rest in households.settings_json.

A house can keep several keys. One is main. The others that are turned on
are tried, in order, when the one before them is down.
"""
from __future__ import annotations

import secrets
import time

from sqlalchemy.orm.attributes import flag_modified

from app.builddb.builddb import db
from app.utils.ai import (
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    MODELS_CACHE_SECS,
    PROVIDERS,
    _pack,
    fetch_provider_models,
    guess_job,
    menu_models,
    normalize_job,
    normalize_provider,
)


def normalize_ask_confirm(value: str | None) -> str:
    v = (value or "ask").strip().lower().replace("-", "_").replace(" ", "_")
    if v in ("allow", "free", "run", "run_free", "always_allow", "open", "go"):
        return "allow"
    return "ask"
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


def _stored_rows(blob: dict) -> tuple[list[dict], str]:
    """Key rows as stored. Old single-key houses become a list in memory."""
    raw = blob.get("keys")
    rows = []
    if isinstance(raw, list):
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            kid = str(item.get("id") or "").strip() or f"k{i}"
            provider = normalize_provider(item.get("provider") or DEFAULT_PROVIDER)
            spec = PROVIDERS.get(provider) or PROVIDERS[DEFAULT_PROVIDER]
            model = (item.get("model") or "").strip() or (spec["models"][0] if spec.get("models") else DEFAULT_MODEL)
            live = [str(x)[:120] for x in (item.get("models_live") or []) if x][:40]
            try:
                models_at = int(item.get("models_at") or 0)
            except (TypeError, ValueError):
                models_at = 0
            rows.append(
                {
                    "id": kid[:40],
                    "provider": provider,
                    "model": model[:120],
                    "api_key": item.get("api_key") or "",
                    "base_url": (item.get("base_url") or "").strip()[:300],
                    "on": item.get("on") is not False,
                    "order": int(item.get("order") or i),
                    "job": normalize_job(item.get("job") or guess_job(provider, model)),
                    "models_live": live,
                    "models_at": models_at,
                }
            )
    if rows:
        default_id = str(blob.get("default_id") or "").strip()
        if default_id not in {r["id"] for r in rows}:
            default_id = rows[0]["id"]
        return rows, default_id
    if (blob.get("api_key") or "").strip():
        provider = normalize_provider(blob.get("provider") or DEFAULT_PROVIDER)
        spec = PROVIDERS.get(provider) or PROVIDERS[DEFAULT_PROVIDER]
        model = (blob.get("model") or "").strip() or (spec["models"][0] if spec.get("models") else DEFAULT_MODEL)
        rows.append(
            {
                "id": "main",
                "provider": provider,
                "model": model[:120],
                "api_key": blob.get("api_key") or "",
                "base_url": (blob.get("base_url") or "").strip()[:300],
                "on": True,
                "order": 0,
                "job": normalize_job(blob.get("job") or guess_job(provider, model)),
                "models_live": [str(x)[:120] for x in (blob.get("models_live") or []) if x][:40],
                "models_at": int(blob.get("models_at") or 0) if str(blob.get("models_at") or "").isdigit() else 0,
            }
        )
    backup = blob.get("backup") if isinstance(blob.get("backup"), dict) else {}
    if (backup.get("api_key") or "").strip():
        provider = normalize_provider(backup.get("provider") or "groq")
        spec = PROVIDERS.get(provider) or PROVIDERS["groq"]
        model = (backup.get("model") or "").strip() or (spec["models"][0] if spec.get("models") else "")
        rows.append(
            {
                "id": "backup",
                "provider": provider,
                "model": model[:120],
                "api_key": backup.get("api_key") or "",
                "base_url": (backup.get("base_url") or "").strip()[:300],
                "on": True,
                "order": 1,
                "job": normalize_job(backup.get("job") or guess_job(provider, model)),
                "models_live": [str(x)[:120] for x in (backup.get("models_live") or []) if x][:40],
                "models_at": 0,
            }
        )
    default_id = ""
    if rows:
        default_id = "backup" if blob.get("try_order") == "backup" and any(r["id"] == "backup" for r in rows) else rows[0]["id"]
    return rows, default_id


def _try_rows(rows: list[dict], default_id: str) -> list[dict]:
    on = [r for r in rows if r.get("on")]
    main = next((r for r in on if r["id"] == default_id), None)
    rest = sorted((r for r in on if r is not main), key=lambda r: (r.get("order", 0), r["id"]))
    if main:
        return [main] + rest
    return rest


def _pack_row(row: dict) -> dict:
    packed = _pack(
        row["provider"],
        _decrypt_key(row.get("api_key") or ""),
        row.get("model") or "",
        row.get("base_url") or "",
        source="household",
        from_env=False,
    )
    packed["job"] = normalize_job(row.get("job") or guess_job(row.get("provider"), row.get("model")))
    packed["models"] = menu_models(row.get("provider") or "", row.get("models_live"), packed.get("model") or "")
    return packed


def household_config(household) -> dict:
    blob = _ai_blob(household)
    rows, default_id = _stored_rows(blob)
    chain_rows = _try_rows(rows, default_id)
    chain = []
    for row in chain_rows:
        packed = _pack_row(row)
        if not packed.get("api_key"):
            continue
        packed["key_id"] = row["id"]
        chain.append(packed)
    main_row = next((r for r in rows if r["id"] == default_id), rows[0] if rows else None)
    if chain:
        cfg = dict(chain[0])
    elif main_row:
        cfg = _pack_row(main_row)
    else:
        cfg = _pack(DEFAULT_PROVIDER, "", "", "", source="household", from_env=False)
    enabled = blob.get("enabled")
    chat = blob.get("chat")
    if enabled is False:
        cfg["ready"] = False
        cfg["enabled"] = False
    else:
        cfg["enabled"] = True
    cfg["chat"] = False if chat is False else True
    cfg["has_key"] = bool(chain)
    cfg["key_hint"] = mask_secret(cfg.get("api_key") or "")
    cfg["chain"] = chain
    cfg["vision"] = any(slot.get("vision") for slot in chain) if chain else bool(cfg.get("vision"))
    saved = []
    try_ids = [r["id"] for r in chain_rows]
    for row in sorted(rows, key=lambda r: (0 if r["id"] in try_ids else 1, try_ids.index(r["id"]) if r["id"] in try_ids else r.get("order", 0))):
        plain = _decrypt_key(row.get("api_key") or "")
        spec = PROVIDERS.get(row["provider"]) or PROVIDERS[DEFAULT_PROVIDER]
        saved.append(
            {
                "id": row["id"],
                "provider": row["provider"],
                "label": spec["label"],
                "model": row.get("model") or "",
                "models": menu_models(row["provider"], row.get("models_live"), row.get("model") or ""),
                "base_url": row.get("base_url") or "",
                "needs_base": row["provider"] == "custom",
                "key_hint": mask_secret(plain),
                "on": bool(row.get("on")),
                "default": row["id"] == default_id,
                "order": row.get("order", 0),
                "job": normalize_job(row.get("job") or guess_job(row["provider"], row.get("model"))),
            }
        )
    cfg["saved_keys"] = saved
    cfg["backup"] = chain[1] if len(chain) > 1 else None
    cfg["backup_has_key"] = len(rows) > 1
    cfg["backup_key_hint"] = ""
    cfg["try_order"] = "primary"
    cfg["ask_confirm"] = normalize_ask_confirm(blob.get("ask_confirm"))
    return cfg


def _write_rows(household, rows: list[dict], default_id: str, *, chat_on: bool, enabled: bool) -> dict:
    blob = _ai_blob(household)
    if default_id not in {r["id"] for r in rows}:
        default_id = next((r["id"] for r in rows if r.get("on")), rows[0]["id"] if rows else "")
    main = next((r for r in rows if r["id"] == default_id), None)
    settings = dict(household.settings_json or {})
    settings["ai"] = {
        "provider": main["provider"] if main else blob.get("provider") or DEFAULT_PROVIDER,
        "model": (main.get("model") if main else "") or "",
        "api_key": (main.get("api_key") if main else "") or "",
        "base_url": (main.get("base_url") if main else "") or "",
        "enabled": bool(enabled),
        "chat": bool(chat_on),
        "keys": rows,
        "default_id": default_id,
        "ask_confirm": normalize_ask_confirm(blob.get("ask_confirm")),
    }
    household.settings_json = settings
    flag_modified(household, "settings_json")
    db.session.commit()
    return household_config(household)


def _chat_enabled(blob: dict, chat, enabled: bool | None) -> tuple[bool, bool]:
    if chat is None:
        chat_on = False if blob.get("chat") is False else True
    else:
        chat_on = bool(chat)
    if enabled is None:
        enabled_on = blob.get("enabled") is not False
    else:
        enabled_on = bool(enabled)
    return chat_on, enabled_on


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
    try_order: str | None = None,
) -> dict:
    """Update the main key. Used by older callers. Adding a different provider goes through add_household_key."""
    blob = _ai_blob(household)
    rows, default_id = _stored_rows(blob)
    provider = normalize_provider(provider)
    spec = PROVIDERS.get(provider) or PROVIDERS[DEFAULT_PROVIDER]
    model = (model or "").strip() or (spec["models"][0] if spec.get("models") else DEFAULT_MODEL)
    base_url = (base_url or "").strip().rstrip("/")
    chat_on, enabled_on = _chat_enabled(blob, chat, enabled)
    if clear_backup:
        rows = [r for r in rows if r["id"] != "backup"]
        if default_id == "backup":
            default_id = rows[0]["id"] if rows else ""
    if clear_key:
        rows = [r for r in rows if r["id"] != default_id]
        default_id = next((r["id"] for r in rows if r.get("on")), rows[0]["id"] if rows else "")
    elif (api_key or "").strip():
        enc = encrypt_text((api_key or "").strip()) or ""
        found = next((r for r in rows if r["id"] == default_id and r["provider"] == provider), None)
        if found is None:
            found = next((r for r in rows if r["provider"] == provider), None)
        if found:
            found["api_key"] = enc
            found["model"] = model[:120]
            found["base_url"] = base_url[:300]
            found["provider"] = provider
            found["on"] = True
            default_id = found["id"]
        else:
            kid = secrets.token_hex(4)
            rows.append(
                {
                    "id": kid,
                    "provider": provider,
                    "model": model[:120],
                    "api_key": enc,
                    "base_url": base_url[:300],
                    "on": True,
                    "order": len(rows),
                }
            )
            if not default_id:
                default_id = kid
    elif default_id and model:
        for row in rows:
            if row["id"] == default_id:
                row["model"] = model[:120]
                if base_url:
                    row["base_url"] = base_url[:300]
                break
    if (backup_api_key or "").strip() and not clear_backup:
        bprov = normalize_provider(backup_provider or "groq")
        bspec = PROVIDERS.get(bprov) or PROVIDERS["groq"]
        bmodel = (backup_model or "").strip() or (bspec["models"][0] if bspec.get("models") else "")
        enc = encrypt_text(backup_api_key.strip()) or ""
        found = next((r for r in rows if r["provider"] == bprov and r["id"] != default_id), None)
        if found:
            found["api_key"] = enc
            found["model"] = bmodel[:120]
            found["on"] = True
        else:
            rows.append(
                {
                    "id": secrets.token_hex(4),
                    "provider": bprov,
                    "model": bmodel[:120],
                    "api_key": enc,
                    "base_url": "",
                    "on": True,
                    "order": len(rows),
                }
            )
        if try_order == "backup":
            backup_row = next((r for r in rows if r["provider"] == bprov), None)
            if backup_row:
                default_id = backup_row["id"]
    return _write_rows(household, rows, default_id, chat_on=chat_on, enabled=enabled_on)


def add_household_key(
    household,
    *,
    provider: str,
    model: str = "",
    api_key: str,
    base_url: str = "",
    use: bool = True,
) -> dict:
    """Append a key. Does not replace a key that is already saved."""
    blob = _ai_blob(household)
    rows, default_id = _stored_rows(blob)
    provider = normalize_provider(provider)
    spec = PROVIDERS.get(provider) or PROVIDERS[DEFAULT_PROVIDER]
    model = (model or "").strip() or (spec["models"][0] if spec.get("models") else DEFAULT_MODEL)
    kid = secrets.token_hex(4)
    rows.append(
        {
            "id": kid,
            "provider": provider,
            "model": model[:120],
            "api_key": encrypt_text((api_key or "").strip()) or "",
            "base_url": (base_url or "").strip().rstrip("/")[:300],
            "on": bool(use),
            "order": len(rows),
            "job": guess_job(provider, model),
        }
    )
    if not default_id:
        default_id = kid
    chat_on, enabled_on = _chat_enabled(blob, None, None)
    _write_rows(household, rows, default_id, chat_on=chat_on, enabled=enabled_on)
    refresh_key_models(household, key_id=kid, stale_only=False, force=True)
    return household_config(household)


def refresh_key_models(household, *, key_id: str | None = None, stale_only: bool = True, force: bool = False) -> dict:
    """Ask each saved key which chat models it can use. Keeps the last good list on a miss."""
    blob = _ai_blob(household)
    rows, default_id = _stored_rows(blob)
    now = int(time.time())
    changed = False
    want = (key_id or "").strip()
    for row in rows:
        if want and row["id"] != want:
            continue
        live = row.get("models_live") or []
        at = int(row.get("models_at") or 0)
        if stale_only and not force and live and now - at < MODELS_CACHE_SECS:
            continue
        plain = _decrypt_key(row.get("api_key") or "")
        if not plain:
            continue
        found = fetch_provider_models(row.get("provider") or "", plain, row.get("base_url") or "")
        if not found:
            continue
        row["models_live"] = found[:40]
        row["models_at"] = now
        if not (row.get("model") or "").strip():
            row["model"] = found[0]
        changed = True
    if not changed:
        return household_config(household)
    chat_on, enabled_on = _chat_enabled(blob, None, None)
    return _write_rows(household, rows, default_id, chat_on=chat_on, enabled=enabled_on)


def set_key_model(household, key_id: str, model: str) -> None:
    model = (model or "").strip()[:120]
    key_id = (key_id or "").strip()
    if not model or not key_id or household is None:
        return
    try:
        blob = _ai_blob(household)
        rows, default_id = _stored_rows(blob)
        hit = False
        for row in rows:
            if row["id"] == key_id:
                row["model"] = model
                hit = True
        if not hit:
            return
        chat_on, enabled_on = _chat_enabled(blob, None, None)
        _write_rows(household, rows, default_id, chat_on=chat_on, enabled=enabled_on)
    except Exception:
        return


def household_key_action(
    household,
    key_id: str,
    action: str,
    *,
    model: str = "",
    api_key: str = "",
    base_url: str = "",
    job: str = "",
) -> dict:
    blob = _ai_blob(household)
    rows, default_id = _stored_rows(blob)
    key_id = (key_id or "").strip()
    action = (action or "").strip().lower()
    row = next((r for r in rows if r["id"] == key_id), None)
    if action == "models" and row:
        refresh_key_models(household, key_id=key_id, stale_only=False, force=True)
        return household_config(household)
    if action == "update" and row:
        chosen = (model or "").strip()
        if chosen:
            row["model"] = chosen[:120]
        if row["provider"] == "custom" or (base_url or "").strip():
            row["base_url"] = (base_url or "").strip().rstrip("/")[:300]
        if (api_key or "").strip():
            row["api_key"] = encrypt_text(api_key.strip()) or row["api_key"]
            row["models_live"] = []
            row["models_at"] = 0
        if job:
            row["job"] = normalize_job(job)
    elif action == "remove" and row:
        rows = [r for r in rows if r["id"] != key_id]
        if default_id == key_id:
            default_id = next((r["id"] for r in _try_rows(rows, "")), rows[0]["id"] if rows else "")
    elif action == "default" and row:
        row["on"] = True
        default_id = row["id"]
    elif action == "on" and row:
        row["on"] = True
        if not default_id:
            default_id = row["id"]
    elif action == "off" and row:
        row["on"] = False
        if default_id == row["id"]:
            nxt = next((r["id"] for r in rows if r["id"] != row["id"] and r.get("on")), "")
            default_id = nxt or row["id"]
    elif action in ("up", "down") and row:
        seq = _try_rows(rows, default_id)
        ids = [r["id"] for r in seq]
        if key_id in ids:
            i = ids.index(key_id)
            j = i - 1 if action == "up" else i + 1
            if 0 <= j < len(ids):
                ids[i], ids[j] = ids[j], ids[i]
                rank = {kid: n for n, kid in enumerate(ids)}
                for item in rows:
                    if item["id"] in rank:
                        item["order"] = rank[item["id"]]
                default_id = ids[0]
    chat_on, enabled_on = _chat_enabled(blob, None, None)
    _write_rows(household, rows, default_id, chat_on=chat_on, enabled=enabled_on)
    if action == "update" and row and (api_key or "").strip():
        refresh_key_models(household, key_id=key_id, stale_only=False, force=True)
    return household_config(household)


def set_household_ask_confirm(household, mode: str) -> dict:
    settings = dict(household.settings_json or {})
    ai = dict(settings.get("ai") or {})
    ai["ask_confirm"] = normalize_ask_confirm(mode)
    settings["ai"] = ai
    household.settings_json = settings
    flag_modified(household, "settings_json")
    blob = _ai_blob(household)
    rows, default_id = _stored_rows(blob)
    chat_on, enabled_on = _chat_enabled(blob, None, None)
    return _write_rows(household, rows, default_id, chat_on=chat_on, enabled=enabled_on)


def set_household_chat(household, *, chat: bool) -> dict:
    blob = _ai_blob(household)
    rows, default_id = _stored_rows(blob)
    chat_on, enabled_on = _chat_enabled(blob, chat, None)
    return _write_rows(household, rows, default_id, chat_on=chat_on, enabled=enabled_on)


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
    if not (cfg.get("has_key") or cfg.get("backup_has_key")) or not cfg.get("enabled"):
        return False
    return chat_on(household)
