"""Per-device / per-user visual language. Not just a palette swap."""
from __future__ import annotations

from flask import request

COOKIE = "family_theme"
MAX_AGE = 60 * 60 * 24 * 400

THEMES = {
    "default": {
        "id": "default",
        "label": "Default",
        "blurb": "Warm household OS. Cream, green, big scan button.",
        "color": "#1f6a45",
    },
    "clean": {
        "id": "clean",
        "label": "Clean",
        "blurb": "Quiet paper. Thin rules, no chrome, no glow.",
        "color": "#111111",
    },
    "dark": {
        "id": "dark",
        "label": "Dark",
        "blurb": "Night kitchen. Dim cards, mint on near-black.",
        "color": "#0c0d0e",
    },
    "when99": {
        "id": "when99",
        "label": "When99",
        "blurb": "Teal desktop, chunky 3-D, a taskbar. 1999 called.",
        "color": "#008080",
    },
}


def normalize(theme_id: str | None) -> str:
    t = (theme_id or "").strip().lower()
    return t if t in THEMES else "default"


def read_theme() -> str:
    try:
        cookie = request.cookies.get(COOKIE)
        if cookie:
            return normalize(cookie)
    except Exception:
        pass
    try:
        from flask_login import current_user

        if getattr(current_user, "is_authenticated", False):
            extra = getattr(current_user, "extra_data", None)
            if isinstance(extra, dict) and extra.get("theme"):
                return normalize(extra.get("theme"))
    except Exception:
        pass
    try:
        from app.utils.platform_auth import current_owner

        owner = current_owner()
        extra = getattr(owner, "extra_data", None) if owner is not None else None
        if isinstance(extra, dict) and extra.get("theme"):
            return normalize(extra.get("theme"))
    except Exception:
        pass
    return "default"


def stamp_theme_cookie(response, theme_id: str):
    theme_id = normalize(theme_id)
    response.set_cookie(
        COOKIE,
        theme_id,
        max_age=MAX_AGE,
        samesite="Lax",
        path="/",
        httponly=False,
    )
    return response


def save_user_theme(user, theme_id: str) -> str:
    theme_id = normalize(theme_id)
    if not user or not getattr(user, "is_authenticated", False):
        return theme_id
    extra = dict(user.extra_data) if isinstance(user.extra_data, dict) else {}
    extra["theme"] = theme_id
    user.extra_data = extra
    try:
        from sqlalchemy.orm.attributes import flag_modified
        from app.builddb.builddb import db

        flag_modified(user, "extra_data")
        db.session.add(user)
        db.session.commit()
    except Exception:
        pass
    return theme_id


def save_owner_theme(owner, theme_id: str) -> str:
    theme_id = normalize(theme_id)
    if owner is None:
        return theme_id
    extra = dict(owner.extra_data) if isinstance(getattr(owner, "extra_data", None), dict) else {}
    extra["theme"] = theme_id
    owner.extra_data = extra
    try:
        from sqlalchemy.orm.attributes import flag_modified
        from app.builddb.builddb import db

        flag_modified(owner, "extra_data")
        db.session.add(owner)
        db.session.commit()
    except Exception:
        pass
    return theme_id
