"""Product pictures for inventory rows. Catalog front-of-pack first, then a household photo."""
from __future__ import annotations


def https_url(url: str | None) -> str | None:
    s = (url or "").strip()
    if not s:
        return None
    if s.startswith("//"):
        s = "https:" + s
    elif s.startswith("http://"):
        s = "https://" + s[7:]
    return s[:500] or None


def item_thumb_url(item) -> str | None:
    g = getattr(item, "grocery", None)
    url = https_url(getattr(g, "image_url", None) if g is not None else None)
    if url:
        return url
    photos = getattr(item, "photos", None) or []
    for p in photos:
        kind = (getattr(p, "kind", None) or "photo").strip().lower()
        if kind in ("photo", "") and getattr(p, "id", None):
            try:
                from flask import url_for

                return url_for("items.serve_photo", photo_id=p.id)
            except Exception:
                return f"/items/photo/{p.id}"
    return None
