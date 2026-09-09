"""Bring-your-own-key AI. Household first, platform fallback, then env.

The site is not an AI product. Keys parse scans, photos, and UPC guesses
(car battery vs AA vs food). Never sent to the browser.
"""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

import requests

from app.utils.platform_settings import get_setting, mask_secret

# OpenAI-compatible unless kind says otherwise.
PROVIDERS: dict[str, dict[str, Any]] = {
    "xai": {
        "label": "SpaceXAI (Grok)",
        "kind": "openai",
        "base_url": "https://api.x.ai/v1",
        "models": ("grok-4.6", "grok-4.5", "grok-4", "grok-3-mini"),
        "hint": "console.x.ai — free-tier or paid. OpenAI-compatible.",
        "env": "XAI_API_KEY",
        "placeholder": "xai-…",
        "vision": True,
    },
    "gemini": {
        "label": "Google Gemini",
        "kind": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "models": (
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash-lite",
        ),
        "hint": "aistudio.google.com — a free Gemini key works.",
        "env": "GEMINI_API_KEY",
        "placeholder": "AIza…",
        "vision": True,
    },
    "openai": {
        "label": "OpenAI",
        "kind": "openai",
        "base_url": "https://api.openai.com/v1",
        "models": ("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "o4-mini"),
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
        "models": ("llama-3.3-70b-versatile", "llama-3.1-8b-instant"),
        "hint": "console.groq.com — free-tier key.",
        "env": "GROQ_API_KEY",
        "placeholder": "gsk_…",
        "vision": False,
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

DEFAULT_PROVIDER = "xai"
DEFAULT_MODEL = "grok-4.6"
# Back-compat for the old platform page.
MODELS = PROVIDERS["xai"]["models"]
BASE_URL = PROVIDERS["xai"]["base_url"]

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
    model = (model or "").strip() or (spec["models"][0] if spec["models"] else DEFAULT_MODEL)
    base = (base_url or "").strip().rstrip("/") or spec["base_url"]
    return {
        "provider": provider,
        "label": spec["label"],
        "kind": spec["kind"],
        "hint": spec["hint"],
        "placeholder": spec["placeholder"],
        "model": model,
        "models": list(spec["models"]),
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


def get_ai_config(household=None, *, household_only: bool = False) -> dict:
    """Public config (key never leaves as full secret except internally)."""
    if household is not None:
        from app.utils.household_ai import household_config

        hh = household_config(household)
        if hh.get("has_key") or household_only:
            return hh
        if household_only:
            return hh
    return platform_config()


def public_ai_config(household=None, *, household_only: bool = False) -> dict:
    cfg = dict(get_ai_config(household, household_only=household_only))
    cfg.pop("api_key", None)
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
) -> tuple[bool, str]:
    cfg = get_ai_config(household, household_only=household_only)
    key = (cfg.get("api_key") or "").strip()
    if not key:
        return False, "No AI key on this household. Paste a Gemini, Grok, or other key in Household."
    kind = cfg.get("kind") or "openai"
    try:
        if kind == "gemini":
            text = _gemini(cfg, prompt, system, max_tokens, timeout, image_bytes, image_mime)
        elif kind == "anthropic":
            text = _anthropic(cfg, prompt, system, max_tokens, timeout, image_bytes, image_mime)
        else:
            text = _openai_compat(cfg, prompt, system, max_tokens, timeout, image_bytes, image_mime)
    except requests.Timeout:
        return False, "AI timed out."
    except Exception as exc:
        return False, f"AI request failed: {exc}"
    if text is None:
        return False, "AI returned nothing. Check the key, model, and base URL."
    return True, text


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
        who = "this household" if household_only else "this household or the platform"
        return False, f"No AI key on {who} yet."
    ok, text = complete(
        "Reply with the single word pong.",
        max_tokens=16,
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


def _gemini(cfg, prompt, system, max_tokens, timeout, image_bytes, image_mime) -> str | None:
    model = cfg["model"]
    if model.startswith("models/"):
        model = model[len("models/") :]
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
    resp = requests.post(
        url,
        params={"key": cfg["api_key"]},
        json={
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.1},
        },
        timeout=timeout,
    )
    if resp.status_code >= 400:
        raise RuntimeError(_err_body(resp))
    data = resp.json() if resp.content else {}
    cands = data.get("candidates") or []
    bits = []
    for p in ((cands[0].get("content") or {}).get("parts") or []) if cands else []:
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
