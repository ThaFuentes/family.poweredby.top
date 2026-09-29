"""Per-key AI budget so one fast turn cannot burst past a provider's rate limit.

Household keys are rate-limited by the provider (Groq caps tokens and requests per
minute per key). Ask may make several model calls in one turn — an inspect round, a
tool round, a say round — and each call re-sends the system prompt and the chat
history. Without a budget that arrives as one large burst and trips a 429.

This module keeps a short rolling window per key (household id + key id) of the
tokens and requests it has just spent, and lets the caller ask whether one more call
fits. It estimates tokens from text length (~4 characters per token), which is close
enough and never needs the network.

Limits come from the owner console (platform settings) or env, and fall back to
conservative defaults:
  ai_max_tokens_per_call   (env AI_MAX_TOKENS_PER_CALL)   default 700
  ai_requests_per_minute   (env AI_REQUESTS_PER_MINUTE)   default 15
  ai_tokens_per_minute     (env AI_TOKENS_PER_MINUTE)     default 12000
"""
from __future__ import annotations

import os
import threading
import time

WINDOW_SECONDS = 60

_DEFAULTS: dict[str, int] = {
    "ai_max_tokens_per_call": 700,
    "ai_requests_per_minute": 15,
    "ai_tokens_per_minute": 12000,
}
_BOUNDS: dict[str, tuple[int, int]] = {
    "ai_max_tokens_per_call": (64, 4096),
    "ai_requests_per_minute": (1, 600),
    "ai_tokens_per_minute": (500, 500_000),
}
_ENV: dict[str, str] = {
    "ai_max_tokens_per_call": "AI_MAX_TOKENS_PER_CALL",
    "ai_requests_per_minute": "AI_REQUESTS_PER_MINUTE",
    "ai_tokens_per_minute": "AI_TOKENS_PER_MINUTE",
}

_LOCK = threading.Lock()
_WINDOW: dict[str, list[tuple[float, int]]] = {}


class AIBudget(RuntimeError):
    """This key has spent its per-minute budget; the caller should back off."""

    def __init__(self, wait: int):
        super().__init__(f"AI key is over its per-minute budget; retry in {int(wait)}s")
        self.wait = max(1, int(wait))


def estimate(text) -> int:
    """Rough token count: about four characters per token."""
    body = "" if text is None else str(text)
    return max(1, (len(body) + 3) // 4)


def _setting_int(key: str) -> int:
    raw = (os.environ.get(_ENV[key]) or "").strip()
    if not raw:
        try:
            from app.utils.platform_settings import get_setting

            raw = (get_setting(key, "") or "").strip()
        except Exception:
            raw = ""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = _DEFAULTS[key]
    low, high = _BOUNDS[key]
    return max(low, min(high, value))


def limits() -> tuple[int, int, int]:
    """(max tokens per call, requests per minute, tokens per minute)."""
    return (
        _setting_int("ai_max_tokens_per_call"),
        _setting_int("ai_requests_per_minute"),
        _setting_int("ai_tokens_per_minute"),
    )


def check(key: str, cost: int, *, rpm: int, tpm: int, window: int = WINDOW_SECONDS) -> tuple[bool, int]:
    """Reserve ``cost`` tokens for ``key``. Returns (allowed, retry_after_seconds)."""
    now = time.time()
    cost = max(1, int(cost or 0))
    with _LOCK:
        rows = [(t, c) for (t, c) in _WINDOW.get(key, []) if now - t < window]
        used = sum(c for _t, c in rows)
        over = bool(rows) and (len(rows) >= max(1, rpm) or used + cost > max(1, tpm))
        if over:
            oldest = min(t for t, _c in rows)
            wait = int(window - (now - oldest)) + 1
            _WINDOW[key] = rows
            return False, max(1, wait)
        rows.append((now, cost))
        _WINDOW[key] = rows
        return True, 0


def spend(key: str, prompt, system, max_tokens: int, *, rpm: int, tpm: int, window: int = WINDOW_SECONDS) -> int:
    """Count one call's tokens against ``key``; raise :class:`AIBudget` when over."""
    cost = estimate(system) + estimate(prompt) + max(1, int(max_tokens or 0))
    allowed, wait = check(key, cost, rpm=rpm, tpm=tpm, window=window)
    if not allowed:
        raise AIBudget(wait)
    return cost


def reset(key: str | None = None) -> None:
    """Forget the window (all keys, or one). Tests and owner resets use this."""
    with _LOCK:
        if key is None:
            _WINDOW.clear()
        else:
            _WINDOW.pop(key, None)
