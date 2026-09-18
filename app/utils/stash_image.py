"""Download a free catalog/Commons picture onto our server when we do not have one."""
from __future__ import annotations

import os
import secrets
from io import BytesIO

import requests

from app.utils.crypto import write_encrypted_file

_UA = {"User-Agent": "family.poweredby.top/1.0 (household OS; picture stash)"}
_MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_SKIP_SLOTS = frozenset({"misc", "other", "interior", "paint", "bed"})


def _uploads_root() -> str:
    from flask import current_app

    root = os.path.join(os.path.dirname(current_app.root_path), "uploads")
    os.makedirs(root, exist_ok=True)
    return root


def fetch_image(url: str) -> tuple[bytes, str] | None:
    s = (url or "").strip()
    if not s.startswith("http"):
        return None
    try:
        r = requests.get(s, headers=_UA, timeout=5, stream=True)
        if r.status_code != 200:
            return None
        mime = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        ext = _MIME_EXT.get(mime)
        if not ext:
            path = s.split("?", 1)[0].lower()
            for cand in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                if path.endswith(cand):
                    ext = ".jpg" if cand == ".jpeg" else cand
                    break
        if not ext:
            return None
        buf = BytesIO()
        n = 0
        for chunk in r.iter_content(64 * 1024):
            n += len(chunk)
            if n > 2_500_000:
                return None
            buf.write(chunk)
        data = buf.getvalue()
        if len(data) < 80:
            return None
        return data, ext
    except Exception:
        return None


def save_photo_bytes(item, data: bytes, *, ext=".jpg", user_id=None, part_id=None, caption=None, kind="photo"):
    from app.builddb.builddb import db
    from app.builddb.table_photo_notes import PhotoNote

    if not data or not getattr(item, "id", None):
        return None
    hid = item.household_id
    folder = os.path.join(_uploads_root(), str(hid), str(item.id))
    os.makedirs(folder, exist_ok=True)
    name = secrets.token_hex(8) + ext + ".enc"
    path = os.path.join(folder, name)
    write_encrypted_file(path, data)
    row = PhotoNote(
        household_id=hid,
        item_id=item.id,
        part_id=int(part_id) if part_id else None,
        kind=kind or "photo",
        caption=(caption or "").strip() or None,
        image_path=f"{hid}/{item.id}/{name}",
        created_by=user_id,
    )
    db.session.add(row)
    db.session.flush()
    return row


def stash_url(item, url: str, user_id=None, part_id=None, caption=None):
    got = fetch_image(url)
    if not got:
        return None
    data, ext = got
    return save_photo_bytes(
        item, data, ext=ext, user_id=user_id, part_id=part_id, caption=caption
    )


def commons_thumb_url(query: str) -> str | None:
    q = " ".join((query or "").split())[:80]
    if len(q) < 4:
        return None
    try:
        r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": q,
                "gsrnamespace": 6,
                "gsrlimit": 4,
                "prop": "imageinfo",
                "iiprop": "url|mime|size",
                "iiurlwidth": 480,
            },
            headers=_UA,
            timeout=4,
        )
        pages = ((r.json() or {}).get("query") or {}).get("pages") or {}
    except Exception:
        return None
    for page in pages.values():
        info = (page.get("imageinfo") or [None])[0] or {}
        mime = (info.get("mime") or "").lower()
        if mime not in _MIME_EXT:
            continue
        url = info.get("thumburl") or info.get("url")
        if url and str(url).startswith("http"):
            return str(url)
    return None


def stash_part_picture(item, part, user_id=None):
    """If this part has no photo, try one free Commons picture. Fail quiet."""
    from app.builddb.table_photo_notes import PhotoNote
    from app.utils.vehicle_systems import slot_label

    if part is None or getattr(part, "slot", None) in _SKIP_SLOTS:
        return None
    existing = PhotoNote.query.filter_by(item_id=item.id, part_id=part.id).first()
    if existing:
        return existing
    label = slot_label(getattr(part, "system", None), getattr(part, "slot", None))
    name = (getattr(part, "name", None) or "").strip()
    query = f"{label} automotive"
    if name and name.lower() not in query.lower():
        query = f"{name} {label} car part"
    url = commons_thumb_url(query)
    if not url:
        return None
    return stash_url(item, url, user_id=user_id, part_id=part.id, caption=name or label)
