"""Stay on the page you were on after a POST. Never dump people on Home."""
from __future__ import annotations

from urllib.parse import urlparse

from flask import request, url_for


def same_site_path(raw: str | None) -> str | None:
    raw = (raw or "").strip()
    if not raw or raw.startswith("//") or raw.startswith("\\"):
        return None
    if raw.startswith("/"):
        return raw[:2000]
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    if parsed.scheme not in ("http", "https", ""):
        return None
    host = ""
    try:
        host = request.host
    except Exception:
        host = ""
    if parsed.netloc and host and parsed.netloc != host:
        return None
    if parsed.netloc and not host:
        return None
    path = parsed.path or "/"
    if not path.startswith("/"):
        return None
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return path[:2000]


def list_url_for_item(item) -> str:
    kind = (getattr(item, "item_type", None) or "").strip().lower()
    if kind == "grocery":
        return url_for("groceries.index")
    if kind == "tool":
        return url_for("tools.index")
    if kind == "vehicle":
        return url_for("vehicles.index")
    if kind == "house":
        return url_for("house.index")
    return url_for("find.index")


def stay_path(item=None, *, fallback: str | None = None) -> str:
    raw = (request.form.get("next") or request.args.get("next") or "").strip()
    path = same_site_path(raw)
    if not path:
        path = same_site_path(request.referrer)
    item_id = getattr(item, "id", None)
    if path and item_id is not None:
        base = path.split("?", 1)[0].rstrip("/")
        if base.endswith(f"/items/{item_id}"):
            path = None
    if path and path.startswith("/auth"):
        path = None
    if path:
        return path
    if item is not None:
        return list_url_for_item(item)
    return fallback or url_for("find.index")
