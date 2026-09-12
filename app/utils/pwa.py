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
  <link rel="apple-touch-startup-image" href="/static/images/intro-poster-phone.jpg">
  <meta name="format-detection" content="telephone=no">
  <script src="{script}" defer></script>
"""

_CHOICES = frozenset({"dismissed", "installed", "no", "yes", "never"})
_SURFACES = frozenset({"phone", "desktop"})
_SCRIPT_VER = "family-os2"

_INTRO_HEAD = """
  <style id="family-intro-css">
  #family-intro{display:none;position:fixed;inset:0;z-index:2147483000;background:#1c1814;align-items:stretch;justify-content:center;overflow:hidden}
  html.family-intro-on #family-intro{display:flex}
  html.family-intro-on,html.family-intro-on body{overflow:hidden}
  #family-intro video,#family-intro .family-intro-poster{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
  #family-intro .family-intro-veil{position:absolute;inset:0;background:linear-gradient(180deg,rgba(28,24,20,.12) 0%,rgba(28,24,20,.55) 100%);pointer-events:none}
  #family-intro .family-intro-scan{position:absolute;left:10%;right:10%;height:2px;top:44%;background:#2f8c5a;box-shadow:0 0 14px #2f8c5a;opacity:0;pointer-events:none}
  html.family-intro-on #family-intro .family-intro-scan{animation:familyIntroScan 1.55s ease-in-out .15s 1}
  @keyframes familyIntroScan{0%{opacity:0;transform:translateY(-80px)}14%{opacity:.95}78%{opacity:.8}100%{opacity:0;transform:translateY(100px)}}
  #family-intro .family-intro-mark{position:relative;z-index:2;margin-top:auto;margin-bottom:max(3.5rem,12vh);display:flex;flex-direction:column;align-items:center;gap:.35rem;color:#f3f1ec;text-align:center;opacity:0;transform:translateY(8px);transition:opacity .45s ease,transform .45s ease;pointer-events:none}
  html.family-intro-brand #family-intro .family-intro-mark{opacity:1;transform:none}
  #family-intro .family-intro-mark img{width:52px;height:52px;border-radius:14px;box-shadow:0 8px 24px rgba(0,0,0,.35)}
  #family-intro .family-intro-mark strong{font:700 1.15rem/1.2 system-ui,-apple-system,sans-serif;letter-spacing:-.03em}
  #family-intro .family-intro-mark span{font:600 .72rem/1.2 system-ui,-apple-system,sans-serif;letter-spacing:.14em;text-transform:uppercase;color:#b7ebc6}
  #family-intro .family-intro-skip{position:absolute;top:calc(.7rem + env(safe-area-inset-top,0px));right:.8rem;z-index:3;border:0;background:rgba(20,24,22,.42);color:#f3f1ec;border-radius:999px;padding:.35rem .75rem;font:600 .8rem system-ui,sans-serif;cursor:pointer}
  html.family-intro-out #family-intro{opacity:0;transition:opacity .4s ease}
  @media (prefers-reduced-motion: reduce){html.family-intro-on #family-intro .family-intro-scan{animation:none}}
  </style>
  <script>
  (function(){
    try {
      if ((location.pathname || "").indexOf("/platform") === 0) return;
      if (sessionStorage.getItem("family.intro.v1") === "1") return;
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
      var stand = window.matchMedia("(display-mode: standalone)").matches
        || window.matchMedia("(display-mode: window-controls-overlay)").matches
        || window.matchMedia("(display-mode: minimal-ui)").matches
        || window.navigator.standalone === true;
      if (!stand) return;
      document.documentElement.classList.add("family-intro-on");
      setTimeout(function(){
        try { sessionStorage.setItem("family.intro.v1", "1"); } catch (e) {}
        document.documentElement.classList.remove("family-intro-on","family-intro-brand","family-intro-out");
      }, 4200);
    } catch (e) {}
  })();
  </script>
  <script src="/static/js/intro.js?v=os1" defer></script>
"""

_INTRO_BODY = """
  <div id="family-intro" role="dialog" aria-label="Family OS">
    <img class="family-intro-poster" src="/static/images/intro-poster.jpg" alt="">
    <video id="family-intro-video" muted playsinline preload="auto" poster="/static/images/intro-poster.jpg">
      <source src="/static/video/intro.webm" type="video/webm">
      <source src="/static/video/intro.mp4" type="video/mp4">
    </video>
    <div class="family-intro-scan" aria-hidden="true"></div>
    <div class="family-intro-veil" aria-hidden="true"></div>
    <div class="family-intro-mark">
      <img src="/static/images/fav.jpg" alt="">
      <strong>Family OS</strong>
      <span>Scan it. Know it.</span>
    </div>
    <button type="button" class="family-intro-skip" id="family-intro-skip">Skip</button>
  </div>
"""


def _inject_intro(data: str) -> str:
    if 'id="family-intro"' in data or "id='family-intro'" in data:
        return data
    if "<head" in data.lower():
        data, _n = re.subn(
            r"(<head[^>]*>)",
            lambda m: m.group(1) + "\n" + _INTRO_HEAD,
            data,
            count=1,
            flags=re.I,
        )
    if "<body" in data.lower():
        data, _n = re.subn(
            r"(<body[^>]*>)",
            lambda m: m.group(1) + "\n" + _INTRO_BODY,
            data,
            count=1,
            flags=re.I,
        )
    return data


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
            "screenshots": [
                {
                    "src": "/static/images/intro-poster.jpg",
                    "sizes": "1280x720",
                    "type": "image/jpeg",
                    "form_factor": "wide",
                    "label": "Scan what's in the house",
                },
                {
                    "src": "/static/images/intro-poster-phone.jpg",
                    "sizes": "720x1280",
                    "type": "image/jpeg",
                    "form_factor": "narrow",
                    "label": "Scan a box in the pantry",
                },
            ],
        }
        resp = make_response(json.dumps(body))
        resp.headers["Content-Type"] = "application/manifest+json; charset=utf-8"
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.route("/offline")
    def offline_shell():
        static = app.static_folder or "static"
        resp = make_response(send_from_directory(static, "offline.html"))
        resp.headers["Content-Type"] = "text/html; charset=utf-8"
        resp.headers["Cache-Control"] = "public, max-age=86400"
        resp.headers["X-Robots-Tag"] = "noindex"
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
            if (request.path or "") == "/offline":
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
