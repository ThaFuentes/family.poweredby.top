"""Bring-your-own-key AI. Households paste their own key. Never the owner's.

The site is not an AI product. Keys parse scans, photos, and UPC guesses
(car battery vs AA vs food). Never sent to the browser. Gemini has a free key.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from typing import Any

import requests

from app.utils.platform_settings import get_setting, mask_secret

# OpenAI-compatible unless kind says otherwise.
PROVIDERS: dict[str, dict[str, Any]] = {
    "gemini": {
        "label": "Google Gemini",
        "kind": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "models": (
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-2.5-flash",
        ),
        "hint": "aistudio.google.com/apikey — free Gemini key. Family OS never uses the owner's.",
        "env": "GEMINI_API_KEY",
        "placeholder": "AIza…",
        "vision": True,
    },
    "xai": {
        "label": "SpaceXAI (Grok)",
        "kind": "openai",
        "base_url": "https://api.x.ai/v1",
        "models": ("grok-4.6", "grok-4.5", "grok-4", "grok-3-mini"),
        "hint": "console.x.ai — your key, not the platform's.",
        "env": "XAI_API_KEY",
        "placeholder": "xai-…",
        "vision": True,
    },
    "openai": {
        "label": "OpenAI",
        "kind": "openai",
        "base_url": "https://api.openai.com/v1",
        "models": ("gpt-4.1-mini", "gpt-4o-mini", "gpt-4o", "gpt-4.1", "o4-mini"),
        "hint": "platform.openai.com",
        "env": "OPENAI_API_KEY",
        "placeholder": "sk-…",
        "vision": True,
    },
    "anthropic": {
        "label": "Anthropic Claude",
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "models": (
            "claude-sonnet-4-5",
            "claude-sonnet-4-0",
            "claude-3-5-haiku-latest",
        ),
        "hint": "console.anthropic.com",
        "env": "ANTHROPIC_API_KEY",
        "placeholder": "sk-ant-…",
        "vision": True,
    },
    "openrouter": {
        "label": "OpenRouter",
        "kind": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "models": (
            "openai/gpt-4o-mini",
            "google/gemini-2.0-flash-001",
            "x-ai/grok-4-fast",
        ),
        "hint": "openrouter.ai — one key, many models.",
        "env": "OPENROUTER_API_KEY",
        "placeholder": "sk-or-…",
        "vision": True,
    },
    "groq": {
        "label": "Groq",
        "kind": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "models": (
            "openai/gpt-oss-20b",
            "openai/gpt-oss-120b",
            "qwen/qwen3.8-27b",
        ),
        "hint": "console.groq.com/keys. Use gpt-oss-20b. The old Llama names are not on a normal key. Photos use qwen/qwen3.8-27b.",
        "env": "GROQ_API_KEY",
        "placeholder": "gsk_…",
        "vision": True,
    },
    "mistral": {
        "label": "Mistral",
        "kind": "openai",
        "base_url": "https://api.mistral.ai/v1",
        "models": ("mistral-small-latest", "mistral-large-latest"),
        "hint": "console.mistral.ai",
        "env": "MISTRAL_API_KEY",
        "placeholder": "…",
        "vision": False,
    },
    "custom": {
        "label": "Custom (OpenAI-compatible)",
        "kind": "openai",
        "base_url": "",
        "models": (),
        "hint": "Ollama, Together, Fireworks, LM Studio — paste base URL, key, model.",
        "env": None,
        "placeholder": "any key the endpoint expects",
        "vision": False,
    },
}

DEFAULT_PROVIDER = "gemini"
DEFAULT_MODEL = "gemini-3.8-flash"
MODELS_CACHE_SECS = 6 * 3600
# Google retires Flash ids. Map old household/platform picks so Test this key works.
_RETIRED_MODELS = {
    "gemini-2.5-flash": "gemini-3.8-flash",
    "gemini-2.5-pro": "gemini-3.8-flash",
    "gemini-2.5-flash-lite": "gemini-3.5-flash-lite",
    "gemini-2.0-flash": "gemini-3.8-flash",
    "gemini-2.0-flash-lite": "gemini-3.5-flash-lite",
    "gemini-1.5-flash": "gemini-3.8-flash",
    "gemini-1.5-pro": "gemini-3.8-flash",
    "gemini-pro": "gemini-3.8-flash",
}
_SUGGESTED_MODEL = re.compile(
    r"use models?/([a-z0-9._-]+)|update your code to use models?/([a-z0-9._-]+)",
    re.I,
)
# Back-compat for the old platform page.
MODELS = PROVIDERS["gemini"]["models"]
BASE_URL = PROVIDERS["gemini"]["base_url"]

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S | re.I)


def provider_ids() -> tuple[str, ...]:
    return tuple(PROVIDERS.keys())


def normalize_provider(value: str | None) -> str:
    p = (value or "").strip().lower()
    aliases = {
        "grok": "xai",
        "spacexai": "xai",
        "x.ai": "xai",
        "google": "gemini",
        "claude": "anthropic",
        "chatgpt": "openai",
        "gpt": "openai",
        "ollama": "custom",
        "together": "custom",
        "lmstudio": "custom",
        "lm studio": "custom",
    }
    p = aliases.get(p, p)
    return p if p in PROVIDERS else DEFAULT_PROVIDER


def _stored_platform_key() -> str:
    return (get_setting("ai_api_key") or "").strip()


def _stored_platform_provider() -> str:
    return normalize_provider(get_setting("ai_provider") or os.getenv("AI_PROVIDER") or DEFAULT_PROVIDER)


def _stored_platform_model() -> str:
    return (get_setting("ai_model") or os.getenv("AI_MODEL") or DEFAULT_MODEL).strip()


def _stored_platform_base() -> str:
    return (get_setting("ai_base_url") or os.getenv("AI_BASE_URL") or "").strip()


def _env_key_for(provider: str) -> str:
    spec = PROVIDERS.get(provider) or {}
    env_name = spec.get("env")
    if env_name:
        val = (os.getenv(env_name) or "").strip()
        if val:
            return val
    if provider == "xai":
        return (os.getenv("XAI_API_KEY") or "").strip()
    if provider == "gemini":
        return (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    return ""


def _spec(provider: str) -> dict:
    return PROVIDERS.get(provider) or PROVIDERS[DEFAULT_PROVIDER]


def _live_model(provider: str, model: str) -> str:
    spec = _spec(provider)
    raw = (model or "").strip()
    if raw.startswith("models/"):
        raw = raw[len("models/") :]
    raw = _RETIRED_MODELS.get(raw, raw)
    if not raw:
        return spec["models"][0] if spec["models"] else DEFAULT_MODEL
    return raw


def _suggested_model(err: str) -> str | None:
    m = _SUGGESTED_MODEL.search(err or "")
    if not m:
        return None
    name = (m.group(1) or m.group(2) or "").strip()
    if name.startswith("models/"):
        name = name[len("models/") :]
    return name or None


_SKIP_MODEL_BITS = (
    "embed",
    "tts",
    "transcribe",
    "whisper",
    "imagen",
    "veo",
    "dall-e",
    "dall_e",
    "moderation",
    "aqa",
    "native-audio",
    "live-translate",
    "computer-use",
    "image-preview",
    "sora",
    "-image",
    "robotics",
    "realtime",
    "playai",
    "guard",
    "safety",
    "babbage",
    "davinci",
    "ada-00",
)


def _chat_model_id(raw: str) -> str:
    name = (raw or "").strip()
    if name.startswith("models/"):
        name = name[len("models/") :]
    return name[:120]


def _skip_model(name: str) -> bool:
    n = (name or "").lower()
    if not n:
        return True
    if any(bit in n for bit in _SKIP_MODEL_BITS):
        return True
    if re.search(r"(^|[-_/])live($|[-_/])", n):
        return True
    return False


def _model_rank(name: str) -> tuple:
    n = (name or "").lower()
    nums = [int(x) for x in re.findall(r"\d+", n)]
    nums = (nums + [0, 0, 0, 0])[:4]
    latest = 1 if "latest" in n else 0
    preview = 1 if any(s in n for s in ("preview", "-exp", "experimental")) else 0
    return (-nums[0], -nums[1], -nums[2], -latest, preview, n)


def _can_generate(row: dict) -> bool:
    methods = (
        row.get("supportedGenerationMethods")
        or row.get("supported_generation_methods")
        or row.get("supportedActions")
        or row.get("supported_actions")
        or []
    )
    if not methods:
        return True
    blob = " ".join(str(m).lower() for m in methods)
    if "embed" in blob and "generatecontent" not in blob and "generate_content" not in blob:
        return False
    return True


def ids_from_gemini_payload(data) -> list[str]:
    rows = (data or {}).get("models") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not _can_generate(row):
            continue
        name = _chat_model_id(row.get("name") or row.get("displayName") or "")
        if name and not _skip_model(name) and name not in out:
            out.append(name)
    out.sort(key=_model_rank)
    return out[:40]


def ids_from_openai_payload(data) -> list[str]:
    rows = (data or {}).get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        if isinstance(row, dict):
            name = _chat_model_id(row.get("id") or row.get("name") or "")
        else:
            name = _chat_model_id(str(row or ""))
        if name and not _skip_model(name) and name not in out:
            out.append(name)
    out.sort(key=_model_rank)
    return out[:40]


def menu_models(provider: str, live=None, current: str = "") -> list[str]:
    """Newest live ids first, then the built-in list, then whatever they already saved."""
    spec = list((PROVIDERS.get(provider or "") or {}).get("models") or ())
    cur = _chat_model_id(current)
    out: list[str] = []
    for m in list(live or []) + spec + ([cur] if cur else []):
        name = _chat_model_id(str(m or ""))
        if not name or name in out:
            continue
        if _skip_model(name) and name != cur:
            continue
        out.append(name)
    return out[:40]


def fetch_provider_models(provider: str, api_key: str, base_url: str = "", timeout: int = 4) -> list[str]:
    """Ask this key which chat models it can use. Empty on any miss."""
    key = (api_key or "").strip()
    if not key:
        return []
    pid = normalize_provider(provider)
    spec = _spec(pid)
    base = (base_url or "").strip().rstrip("/") or spec.get("base_url") or ""
    kind = spec.get("kind") or "openai"
    try:
        if kind == "gemini":
            url = f"{base or 'https://generativelanguage.googleapis.com/v1beta'}/models"
            resp = requests.get(
                url,
                params={"key": key, "pageSize": 100},
                headers={"x-goog-api-key": key},
                timeout=timeout,
            )
            if resp.status_code >= 400:
                return []
            data = resp.json() if resp.content else {}
            found = ids_from_gemini_payload(data)
            token = (data.get("nextPageToken") or "").strip() if isinstance(data, dict) else ""
            if token:
                more = requests.get(
                    url,
                    params={"key": key, "pageSize": 100, "pageToken": token},
                    headers={"x-goog-api-key": key},
                    timeout=timeout,
                )
                if more.status_code < 400 and more.content:
                    extra = ids_from_gemini_payload(more.json() if more.content else {})
                    for name in extra:
                        if name not in found:
                            found.append(name)
                    found.sort(key=_model_rank)
            return found[:40]
        if kind == "anthropic":
            url = f"{base or 'https://api.anthropic.com/v1'}/models"
            resp = requests.get(
                url,
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                },
                timeout=timeout,
            )
            if resp.status_code >= 400:
                return []
            return ids_from_openai_payload(resp.json() if resp.content else {})
        if not base:
            return []
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        if pid == "openrouter":
            headers["HTTP-Referer"] = "https://family.poweredby.top"
            headers["X-Title"] = "Family OS"
        resp = requests.get(f"{base}/models", headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            return []
        return ids_from_openai_payload(resp.json() if resp.content else {})
    except Exception:
        return []


def persist_model(model: str, household=None) -> None:
    """Write a working model id so Test this key and the next scan stay on it."""
    model = (model or "").strip()[:120]
    if not model:
        return
    try:
        if household is not None:
            from app.utils.household_ai import household_config, save_household_ai

            cur = household_config(household)
            save_household_ai(
                household,
                provider=cur.get("provider") or DEFAULT_PROVIDER,
                model=model,
                api_key="",
                base_url=cur.get("base_url") or "",
                enabled=cur.get("enabled", True),
                clear_key=False,
            )
            return
        from app.utils.platform_settings import set_setting

        set_setting("ai_model", model)
    except Exception:
        pass


def _pack(
    provider: str,
    key: str,
    model: str,
    base_url: str = "",
    *,
    source: str,
    from_env: bool = False,
) -> dict:
    spec = _spec(provider)
    model = _live_model(provider, model)
    base = (base_url or "").strip().rstrip("/") or spec["base_url"]
    return {
        "provider": provider,
        "label": spec["label"],
        "kind": spec["kind"],
        "hint": spec["hint"],
        "placeholder": spec["placeholder"],
        "model": model,
        "models": menu_models(provider, None, model),
        "has_key": bool(key),
        "key_hint": mask_secret(key),
        "ready": bool(key) and bool(base or spec["kind"] != "openai"),
        "from_env": from_env,
        "source": source,
        "base_url": base,
        "vision": bool(spec.get("vision")),
        "api_key": key,
    }


def platform_config() -> dict:
    provider = _stored_platform_provider()
    key = _stored_platform_key() or _env_key_for(provider)
    from_env = bool(key) and not _stored_platform_key()
    if not key:
        for pid, spec in PROVIDERS.items():
            env_name = spec.get("env")
            if not env_name:
                continue
            k = (os.getenv(env_name) or "").strip()
            if k:
                provider = pid
                key = k
                from_env = True
                break
    return _pack(
        provider,
        key,
        _stored_platform_model(),
        _stored_platform_base(),
        source="platform",
        from_env=from_env,
    )


def _family_request_house_id() -> int:
    try:
        from flask import has_request_context
        from flask_login import current_user

        if not has_request_context():
            return 0
        if not getattr(current_user, "is_authenticated", False):
            return 0
        return int(getattr(current_user, "household_id", 0) or 0)
    except Exception:
        return 0


def _household_in_scope(household) -> bool:
    if household is None:
        return True
    hid = _family_request_house_id()
    oid = int(getattr(household, "id", 0) or 0)
    if hid and oid and hid != oid:
        return False
    return True


def get_ai_config(household=None, *, household_only: bool = False) -> dict:
    """Household work is BYOK only. Platform key is never used by a family."""
    family_hid = _family_request_house_id()
    if family_hid:
        household_only = True
        if household is None:
            try:
                from flask_login import current_user

                household = getattr(current_user, "household", None)
            except Exception:
                household = None
        if household is not None and not _household_in_scope(household):
            return _pack(DEFAULT_PROVIDER, "", DEFAULT_MODEL, "", source="household", from_env=False)
    if household is not None:
        from app.utils.household_ai import household_config

        return household_config(household)
    if household_only:
        return _pack(DEFAULT_PROVIDER, "", DEFAULT_MODEL, "", source="household", from_env=False)
    return platform_config()


def public_ai_config(household=None, *, household_only: bool = False) -> dict:
    cfg = dict(get_ai_config(household, household_only=household_only))
    cfg.pop("api_key", None)
    cfg["chain"] = []
    backup = cfg.get("backup")
    if isinstance(backup, dict):
        backup = dict(backup)
        backup.pop("api_key", None)
        cfg["backup"] = backup
    cfg["providers"] = [
        {
            "id": pid,
            "label": spec["label"],
            "hint": spec["hint"],
            "models": list(spec["models"]),
            "placeholder": spec["placeholder"],
            "needs_base": pid == "custom",
            "vision": bool(spec.get("vision")),
        }
        for pid, spec in PROVIDERS.items()
    ]
    return cfg


def _capacity_err(err: str) -> bool:
    t = (err or "").lower()
    return any(
        s in t
        for s in (
            "503",
            "429",
            "500",
            "502",
            "504",
            "high demand",
            "overloaded",
            "unavailable",
            "resource exhausted",
            "try again later",
            "bad gateway",
            "timed out",
            "timeout",
            "connection",
        )
    )


GROQ_VISION_MODEL = "qwen/qwen3.8-27b"


def _model_rejected(err: str) -> bool:
    t = (err or "").lower()
    return any(
        s in t
        for s in (
            "does not exist",
            "model_not_found",
            "decommissioned",
            "no longer supported",
            "invalid model",
            "unknown model",
            "do not have access",
            "you do not have access",
        )
    )


def _next_listed_model(provider: str | None, current: str | None) -> str | None:
    rest = _sibling_models(provider, current)
    return rest[0] if rest else None


def _sibling_models(provider: str | None, current: str | None, listed: list | None = None) -> list[str]:
    """Other chat ids for this key, starting after the one they picked."""
    models = menu_models(provider or "", listed, current or "")
    if not models:
        return []
    cur = (current or "").strip()
    if provider == "gemini":
        cur = _live_model("gemini", cur)
    if cur in models:
        i = models.index(cur)
        return [m for m in (models[i + 1 :] + models[:i]) if m != cur]
    return [m for m in models if m != cur]


JOB_KINDS = ("any", "everyday", "heavy")


def normalize_job(value: str | None) -> str:
    v = (value or "any").strip().lower()
    aliases = {
        "chat": "everyday",
        "basic": "everyday",
        "light": "everyday",
        "fast": "everyday",
        "photo": "heavy",
        "photos": "heavy",
        "vision": "heavy",
        "research": "heavy",
        "both": "any",
        "all": "any",
        "": "any",
    }
    v = aliases.get(v, v)
    return v if v in JOB_KINDS else "any"


def guess_job(provider: str | None, model: str | None) -> str:
    m = (model or "").lower()
    if any(s in m for s in ("lite", "mini", "haiku", "8b", "20b", "flash-lite")):
        return "everyday"
    if any(s in m for s in ("pro", "sonnet", "gpt-4o", "grok-4", "120b", "large", "opus")):
        return "heavy"
    return "any"


def slots_for_job(slots: list, job: str | None) -> list:
    """Everyday vs heavy first, then the other keys as backup."""
    want = normalize_job(job) if job else "any"
    if not slots or want == "any":
        return list(slots or [])
    pref, rest = [], []
    for slot in slots:
        kind = normalize_job(slot.get("job"))
        if kind in (want, "any"):
            pref.append(slot)
        else:
            rest.append(slot)
    return (pref or list(slots)) + [s for s in rest if s not in (pref or [])]


def _for_image(cfg: dict, image_bytes) -> dict:
    """Groq text models cannot see a photo. Qwen on the same key can."""
    if not image_bytes or (cfg.get("provider") or "") != "groq":
        return cfg
    if (cfg.get("model") or "") == GROQ_VISION_MODEL and cfg.get("vision"):
        return cfg
    nxt = dict(cfg)
    nxt["model"] = GROQ_VISION_MODEL
    nxt["vision"] = True
    return nxt


def _next_gemini_model(current: str | None) -> str | None:
    models = list((PROVIDERS.get("gemini") or {}).get("models") or ())
    cur = _live_model("gemini", current or "")
    if cur in models:
        rest = [m for m in models if m != cur]
        return rest[0] if rest else None
    return models[0] if models else None


def complete(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 400,
    timeout: int = 12,
    household=None,
    household_only: bool = False,
    image_bytes: bytes | None = None,
    image_mime: str | None = None,
    job: str | None = None,
) -> tuple[bool, str]:
    if household is not None and not _household_in_scope(household):
        return False, "AI stays in this household."
    cfg = get_ai_config(household, household_only=household_only)
    slots = [c for c in (cfg.get("chain") or []) if (c.get("api_key") or "").strip()]
    if not slots and (cfg.get("api_key") or "").strip():
        slots = [cfg]
    slots = slots_for_job(slots, job)
    if not slots:
        return False, "No AI key on this household. Paste your own Gemini (free) or other key in Household. Family OS does not share the owner's key."

    def _call(use_cfg):
        use_cfg = _for_image(use_cfg, image_bytes)
        kind = use_cfg.get("kind") or "openai"
        if kind == "gemini":
            return _gemini(
                use_cfg, prompt, system, max_tokens, timeout, image_bytes, image_mime, household=household
            )
        if kind == "anthropic":
            return _anthropic(use_cfg, prompt, system, max_tokens, timeout, image_bytes, image_mime)
        return _openai_compat(use_cfg, prompt, system, max_tokens, timeout, image_bytes, image_mime)

    def _persist_swap(local, new_model: str, *, keep: bool) -> None:
        if not keep or not new_model or not local.get("key_id"):
            return
        try:
            from app.utils.household_ai import set_key_model

            set_key_model(household, local["key_id"], new_model)
        except Exception:
            persist_model(new_model, household=household)

    def _attempt(use_cfg) -> tuple[bool, str]:
        last = ""
        local = dict(use_cfg)
        tried: list[str] = []
        while True:
            model = (local.get("model") or "").strip() or "?"
            if model in tried:
                break
            tried.append(model)
            try:
                text = _call(local)
                if text:
                    return True, text
                last = "AI returned nothing. Check the key, model, and base URL."
            except requests.Timeout:
                last = "AI timed out."
            except Exception as exc:
                last = str(exc)
                suggested = _suggested_model(last)
                if suggested and suggested not in tried:
                    _persist_swap(local, suggested, keep=True)
                    local = dict(local)
                    local["model"] = suggested
                    continue
            if _capacity_err(last):
                time.sleep(0.45)
                try:
                    text = _call(local)
                    if text:
                        return True, text
                except Exception as exc:
                    last = str(exc)
            alt = next(
                (
                    m
                    for m in _sibling_models(local.get("provider"), model, local.get("models"))
                    if m not in tried
                ),
                None,
            )
            if not alt:
                break
            if _model_rejected(last):
                _persist_swap(local, alt, keep=True)
            local = dict(local)
            local["model"] = alt
        return False, last

    last_err = ""
    for slot in slots:
        ok, text = _attempt(slot)
        if ok:
            return True, text
        last_err = text
    if _capacity_err(last_err):
        return False, "The model is busy right now. I can still look up this house — tools, vehicles, basket, what’s due."
    if last_err:
        return False, f"AI request failed: {last_err}" if "AI " not in last_err[:4] and "timed" not in last_err.lower() else last_err
    return False, "AI returned nothing. Check the key, model, and base URL."


def complete_json(prompt: str, **kwargs) -> tuple[bool, dict]:
    ok, text = complete(prompt, **kwargs)
    if not ok:
        return False, {"error": text}
    parsed = parse_json_object(text)
    if parsed is None:
        return False, {"error": "AI did not return JSON.", "raw": text[:400]}
    return True, parsed


def parse_json_object(text: str) -> dict | None:
    raw = (text or "").strip()
    if not raw:
        return None
    m = _JSON_FENCE.search(raw)
    if m:
        raw = m.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def ping_ai(household=None, *, household_only: bool = False) -> tuple[bool, str]:
    cfg = get_ai_config(household, household_only=household_only)
    if not cfg.get("has_key"):
        if household is not None or household_only:
            return False, "No AI key on this household yet. Paste your own — Gemini is free."
        return False, "No owner-console AI key. Families never use this page."
    ok, text = complete(
        "Reply with the single word pong.",
        max_tokens=256,
        timeout=30,
        household=household,
        household_only=household_only,
    )
    if not ok:
        return False, text
    return True, f"Reachable · {cfg['label']} · {cfg['model']} · {text[:80]}"


def _user_parts(prompt: str, image_bytes, image_mime) -> list[dict]:
    parts: list[dict] = [{"type": "text", "text": prompt}]
    if image_bytes and image_mime:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{image_mime};base64,{b64}"},
            }
        )
    return parts


def _openai_compat(cfg, prompt, system, max_tokens, timeout, image_bytes, image_mime) -> str | None:
    url = f"{cfg['base_url']}/chat/completions"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    if image_bytes and image_mime and cfg.get("vision"):
        messages.append({"role": "user", "content": _user_parts(prompt, image_bytes, image_mime)})
    else:
        messages.append({"role": "user", "content": prompt})
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    if cfg["provider"] == "openrouter":
        headers["HTTP-Referer"] = "https://family.poweredby.top"
        headers["X-Title"] = "Family OS"
    resp = requests.post(
        url,
        headers=headers,
        json={
            "model": cfg["model"],
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.1,
        },
        timeout=timeout,
    )
    if resp.status_code >= 400:
        raise RuntimeError(_err_body(resp))
    data = resp.json() if resp.content else {}
    return (
        (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        or ""
    ).strip() or None


def _gemini(cfg, prompt, system, max_tokens, timeout, image_bytes, image_mime, household=None) -> str | None:
    model = _live_model("gemini", cfg.get("model") or DEFAULT_MODEL)
    url = f"{cfg['base_url']}/models/{model}:generateContent"
    parts: list[dict] = []
    text = prompt if not system else f"{system}\n\n{prompt}"
    parts.append({"text": text})
    if image_bytes and image_mime:
        parts.append(
            {
                "inline_data": {
                    "mime_type": image_mime,
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                }
            }
        )
    # Gemini 3 thinking eats maxOutputTokens. MINIMAL leaves room for the actual answer.
    out_cap = max(int(max_tokens or 256), 512)
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "maxOutputTokens": out_cap,
            "temperature": 0.1,
            "thinkingConfig": {"thinkingLevel": "MINIMAL"},
        },
    }
    resp = requests.post(
        url,
        params={"key": cfg["api_key"]},
        headers={"x-goog-api-key": cfg["api_key"], "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )
    if resp.status_code >= 400:
        err = _err_body(resp)
        suggested = _suggested_model(err)
        if suggested and suggested != model:
            persist_model(suggested, household=household)
            cfg = dict(cfg)
            cfg["model"] = suggested
            return _gemini(cfg, prompt, system, max_tokens, timeout, image_bytes, image_mime, household=household)
        raise RuntimeError(err)
    data = resp.json() if resp.content else {}
    cands = data.get("candidates") or []
    bits = []
    for p in ((cands[0].get("content") or {}).get("parts") or []) if cands else []:
        if p.get("thought"):
            continue
        t = p.get("text")
        if t:
            bits.append(t)
    return "\n".join(bits).strip() or None


def _anthropic(cfg, prompt, system, max_tokens, timeout, image_bytes, image_mime) -> str | None:
    url = f"{cfg['base_url']}/messages"
    content: list[dict] = []
    if image_bytes and image_mime:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_mime,
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                },
            }
        )
    content.append({"type": "text", "text": prompt})
    body: dict[str, Any] = {
        "model": cfg["model"],
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}],
    }
    if system:
        body["system"] = system
    resp = requests.post(
        url,
        headers={
            "x-api-key": cfg["api_key"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=body,
        timeout=timeout,
    )
    if resp.status_code >= 400:
        raise RuntimeError(_err_body(resp))
    data = resp.json() if resp.content else {}
    bits = []
    for block in data.get("content") or []:
        if block.get("type") == "text" and block.get("text"):
            bits.append(block["text"])
    return "\n".join(bits).strip() or None


def _err_body(resp) -> str:
    try:
        data = resp.json()
        err = data.get("error")
        if isinstance(err, dict):
            return f"{resp.status_code}: {err.get('message') or err}"
        if err:
            return f"{resp.status_code}: {err}"
        return f"{resp.status_code}: {str(data)[:240]}"
    except Exception:
        return f"{resp.status_code}: {(resp.text or '')[:240]}"
