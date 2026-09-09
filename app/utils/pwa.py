# ================================================================
# Browser-installable app (PWA) for family.poweredby.top
# Same pattern as Aegis / MyVineChurch: /sw.js, host-correct manifest,
# install prompt remembered per device fingerprint + user.
# ================================================================
from __future__ import annotations

import json
import re

from flask import jsonify, make_response, request, send_from_directory
from sqlalchemy import text


_HEAD_SNIPPET = """
  <meta name="theme-color" content="#1f6a45">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="{title}">
  <link rel="manifest" href="{manifest}">
  <link rel="apple-touch-icon" href="{icon}">
  <link rel="apple-touch-icon" sizes="180x180" href="{icon}">
  <meta name="format-detection" content="telephone=no">
  <script src="{script}" defer></script>
"""

_CHOICES = frozenset({"dismissed", "installed", "no", "yes", "never"})
_SURFACES = frozenset({"phone", "desktop"})
_SCRIPT_VER = "family-os2"


def _brand() -> dict:
    return {
        "name": "Family OS",
        "short": "Family",
        "title": "Family OS",
        "desc": "Household operating system — scan, stock, maintain.",
        "guest_start": "/",
        "authed_start": "/",
    }


def _choice_allowed(choice: str) -> bool:
    if choice in _CHOICES:
        return True
    if choice.startswith("snooze:"):
        tail = choice.split(":", 1)[-1]
        return tail.isdigit() and len(tail) >= 10
    return False


def _device_bits() -> tuple[str | None, str | None]:
    fp = None
    ip = None
    try:
        from poweredbytop.security.device_print import request_audit_context

        ctx = request_audit_context() or {}
        fp = (ctx.get("device_fp") or "").strip() or None
        ip = (ctx.get("ip") or "").strip() or None
    except Exception:
        pass
    if not ip:
        try:
            from poweredbytop.utils.helpers import get_real_ip

            ip = (get_real_ip() or "").strip() or None
        except Exception:
            ip = (request.remote_addr or "").strip() or None
    return fp, ip


def _ensure_choice_table(conn) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS pwa_prompt_choices (
                id INT NOT NULL AUTO_INCREMENT,
                device_fp VARCHAR(64) NULL,
                ip VARCHAR(45) NULL,
                surface VARCHAR(16) NOT NULL,
                choice VARCHAR(64) NOT NULL,
                user_id INT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (id),
                KEY idx_pwa_fp_surface (device_fp, surface),
                KEY idx_pwa_user_surface (user_id, surface)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    )


def _lookup_choice(surface: str) -> str | None:
    fp, _ip = _device_bits()
    uid = None
    try:
        from flask_login import current_user

        if getattr(current_user, "is_authenticated", False):
            uid = int(current_user.id)
            extra = getattr(current_user, "extra_data", None)
            if isinstance(extra, dict):
                saved = (extra.get("pwa_choice") or {}).get(surface)
                if saved and _choice_allowed(str(saved)):
                    return str(saved)
    except Exception:
        uid = None
    try:
        from app.builddb.builddb import db

        with db.engine.begin() as conn:
            _ensure_choice_table(conn)
            if fp:
                row = conn.execute(
                    text(
                        "SELECT choice FROM pwa_prompt_choices "
                        "WHERE device_fp = :fp AND surface = :s "
                        "ORDER BY updated_at DESC LIMIT 1"
                    ),
                    {"fp": fp, "s": surface},
                ).mappings().first()
                if row and _choice_allowed(str(row.get("choice") or "")):
                    return str(row["choice"])
            if uid:
                row = conn.execute(
                    text(
                        "SELECT choice FROM pwa_prompt_choices "
                        "WHERE user_id = :uid AND surface = :s "
                        "ORDER BY updated_at DESC LIMIT 1"
                    ),
                    {"uid": uid, "s": surface},
                ).mappings().first()
                if row and _choice_allowed(str(row.get("choice") or "")):
                    return str(row["choice"])
    except Exception:
        return None
    return None


def _save_choice(surface: str, choice: str) -> None:
    fp, ip = _device_bits()
    uid = None
    try:
        from flask_login import current_user

        if getattr(current_user, "is_authenticated", False):
            uid = int(current_user.id)
            extra = dict(current_user.extra_data) if isinstance(current_user.extra_data, dict) else {}
            bucket = dict(extra.get("pwa_choice") or {})
            bucket[surface] = choice
            extra["pwa_choice"] = bucket
            current_user.extra_data = extra
            try:
                from sqlalchemy.orm.attributes import flag_modified
                from app.builddb.builddb import db

                flag_modified(current_user, "extra_data")
                db.session.add(current_user)
                db.session.commit()
            except Exception:
                pass
    except Exception:
        uid = None
    try:
        from app.builddb.builddb import db

        with db.engine.begin() as conn:
            _ensure_choice_table(conn)
            conn.execute(
                text(
                    """
                    INSERT INTO pwa_prompt_choices (device_fp, ip, surface, choice, user_id)
                    VALUES (:fp, :ip, :s, :c, :uid)
                    """
                ),
                {"fp": fp, "ip": ip, "s": surface, "c": choice, "uid": uid},
            )
    except Exception:
        pass


def _start_url() -> str:
    brand = _brand()
    try:
        from flask_login import current_user

        if getattr(current_user, "is_authenticated", False):
            return brand["authed_start"]
    except Exception:
        pass
    return brand["guest_start"]


def register_pwa(app) -> None:
    @app.route("/sw.js")
    def service_worker():
        static = app.static_folder or "static"
        resp = make_response(send_from_directory(static, "sw.js"))
        resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
        resp.headers["Service-Worker-Allowed"] = "/"
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp

    @app.route("/manifest.webmanifest")
    def pwa_manifest():
        brand = _brand()
        start = _start_url()
        origin = (request.url_root or "/").rstrip("/") + "/"
        body = {
            "name": brand["name"],
            "short_name": brand["short"],
            "description": brand["desc"],
            "start_url": start,
            "scope": "/",
            "id": "/",
            "display": "standalone",
            "display_override": ["standalone", "minimal-ui", "window-controls-overlay"],
            "orientation": "any",
            "dir": "ltr",
            "background_color": "#f3f1ec",
            "theme_color": "#1f6a45",
            "lang": "en",
            "categories": ["lifestyle", "productivity", "utilities"],
            "icons": [
                {
                    "src": "/static/images/pwa-192.png",
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any",
                },
                {
                    "src": "/static/images/pwa-512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
            ],
            "shortcuts": [
                {
                    "name": "Scan item",
                    "short_name": "Scan",
                    "url": "/scan/",
                    "icons": [{"src": "/static/images/pwa-192.png", "sizes": "192x192"}],
                },
                {
                    "name": "Shopping list",
                    "short_name": "List",
                    "url": "/groceries/list",
                    "icons": [{"src": "/static/images/pwa-192.png", "sizes": "192x192"}],
                },
                {
                    "name": "Tools",
                    "short_name": "Tools",
                    "url": "/tools/",
                    "icons": [{"src": "/static/images/pwa-192.png", "sizes": "192x192"}],
                },
            ],
            "prefer_related_applications": False,
            "related_applications": [
                {"platform": "webapp", "url": origin + "manifest.webmanifest"}
            ],
        }
        resp = make_response(json.dumps(body))
        resp.headers["Content-Type"] = "application/manifest+json; charset=utf-8"
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.route("/pwa/choice", methods=["GET", "POST"])
    def pwa_choice():
        if request.method == "GET":
            surface = (request.args.get("surface") or "desktop").strip().lower()
            if surface not in _SURFACES:
                surface = "desktop"
            return jsonify({"ok": True, "choice": _lookup_choice(surface), "surface": surface})
        data = request.get_json(silent=True) or {}
        surface = str(data.get("surface") or request.form.get("surface") or "desktop").strip().lower()
        choice = str(data.get("choice") or request.form.get("choice") or "").strip().lower()
        if surface not in _SURFACES:
            surface = "desktop"
        if not _choice_allowed(choice):
            return jsonify({"ok": False, "error": "choice"}), 400
        _save_choice(surface, choice)
        return jsonify({"ok": True, "choice": choice, "surface": surface})

    @app.after_request
    def _inject_pwa(response):
        try:
            if response.status_code != 200:
                return response
            ctype = (response.headers.get("Content-Type") or "").lower()
            if "text/html" not in ctype:
                return response
            data = response.get_data(as_text=True)
            if not data or "<head" not in data.lower():
                return response
            if "pwa-install.js" in data:
                return response

            brand = _brand()
            manifest = "/manifest.webmanifest"
            icon = "/static/images/pwa-192.png"
            script = f"/static/js/pwa-install.js?v={_SCRIPT_VER}"
            inject = _HEAD_SNIPPET.format(
                title=brand["title"],
                manifest=manifest,
                icon=icon,
                script=script,
            )
            if 'rel="manifest"' in data or "rel='manifest'" in data:
                data = re.sub(
                    r"""<link[^>]+rel=["']manifest["'][^>]*>""",
                    f'<link rel="manifest" href="{manifest}">',
                    data,
                    count=1,
                    flags=re.I,
                )
                if "pwa-install.js" not in data:
                    script_tag = f'<script src="{script}" defer></script>'
                    data, n = re.subn(
                        r"(<head[^>]*>)",
                        r"\1\n  " + script_tag,
                        data,
                        count=1,
                        flags=re.I,
                    )
                    if not n:
                        return response
                response.set_data(data)
                response.headers["Content-Length"] = str(len(data.encode("utf-8")))
                return response

            new_data, n = re.subn(
                r"(<head[^>]*>)",
                r"\1\n" + inject,
                data,
                count=1,
                flags=re.I,
            )
            if n:
                response.set_data(new_data)
                response.headers["Content-Length"] = str(len(new_data.encode("utf-8")))
        except Exception:
            return response
        return response
