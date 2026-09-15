# Threat map — loaded only when this module imports successfully.
# create_app wraps this import so a failure cannot un-register /security.
from __future__ import annotations

import os

from flask import (
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from . import security_bp
from .utils import can_access_security_console, csrf_ok
from .views import _base_ctx, security_required

_ALERT_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".webm"}
_ALERT_MIME = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".webm": "audio/webm",
}
_ALERT_MAX = 4 * 1024 * 1024
_ALERT_STEM = "threat-map-alert"


def _alert_dir() -> str:
    root = os.path.abspath(
        os.path.join(current_app.root_path, "..", "uploads", "security")
    )
    os.makedirs(root, exist_ok=True)
    return root


def _alert_path() -> str | None:
    d = _alert_dir()
    try:
        names = os.listdir(d)
    except Exception:
        return None
    for name in names:
        stem, ext = os.path.splitext(name)
        if stem == _ALERT_STEM and ext.lower() in _ALERT_EXTS:
            path = os.path.join(d, name)
            if os.path.isfile(path):
                return path
    return None


def _alert_url() -> str:
    path = _alert_path()
    if not path:
        return ""
    try:
        v = int(os.path.getmtime(path))
    except Exception:
        v = 1
    return url_for("security.threat_map_alert", v=v)


def _clear_alert_files() -> None:
    d = _alert_dir()
    try:
        names = os.listdir(d)
    except Exception:
        return
    for name in names:
        stem, ext = os.path.splitext(name)
        if stem == _ALERT_STEM and ext.lower() in _ALERT_EXTS:
            try:
                os.remove(os.path.join(d, name))
            except Exception:
                pass


def _flag_on() -> bool:
    flag = (
        os.getenv("FAMILY_THREAT_MAP")
        or os.getenv("AEGIS_THREAT_MAP")
        or os.getenv("AEGISX_THREAT_MAP")
        or "1"
    ).strip().lower()
    return flag not in ("0", "false", "off")


def _json_denied(code=401):
    return jsonify({"ok": False, "error": "auth"}), code


def _parse_window(allow_lifetime: bool = False) -> str:
    from . import threat_queries as tq

    window = (request.args.get("window") or "24h").strip().lower()
    if window in tq.LIFETIME_WINDOWS:
        window = "lifetime"
    allowed = set(tq.WINDOWS)
    if allow_lifetime:
        allowed.add("lifetime")
    if window not in allowed:
        window = "24h"
    return window


def threat_map_json_required(f):
    from functools import wraps

    @wraps(f)
    def wrapped(*args, **kwargs):
        if not _flag_on():
            return jsonify({"ok": False, "error": "off"}), 404
        from app.utils.platform_auth import is_owner

        if not is_owner():
            return _json_denied(401)
        if not can_access_security_console():
            return _json_denied(403)
        return f(*args, **kwargs)

    return wrapped


@security_bp.route("/threat-map")
@security_required
def threat_map():
    if not _flag_on():
        from flask import abort

        abort(404)
    path = _alert_path()
    return render_template(
        "security/threat_map.html",
        page_title="Threat map",
        alert_url=_alert_url(),
        alert_name=os.path.basename(path) if path else "",
        **_base_ctx(),
    )


@security_bp.route("/threat-map/alert", methods=["GET", "POST"])
@security_required
def threat_map_alert():
    if not _flag_on():
        abort(404)
    if request.method == "GET":
        path = _alert_path()
        if not path:
            abort(404)
        ext = os.path.splitext(path)[1].lower()
        return send_file(
            path,
            mimetype=_ALERT_MIME.get(ext, "application/octet-stream"),
            max_age=300,
            download_name=os.path.basename(path),
        )

    if not csrf_ok():
        flash("Session expired. Try the upload again.", "danger")
        return redirect(url_for("security.threat_map"))

    action = (request.form.get("action") or "upload").strip().lower()
    if action == "clear":
        _clear_alert_files()
        flash("Threat map alert sound cleared. Hits use the built-in beep.", "info")
        return redirect(url_for("security.threat_map"))

    storage = request.files.get("alert_file")
    if not storage or not storage.filename:
        flash("Choose an audio file (mp3, wav, ogg, m4a, or webm).", "danger")
        return redirect(url_for("security.threat_map"))
    from werkzeug.utils import secure_filename

    name = secure_filename(storage.filename or "")
    ext = os.path.splitext(name)[1].lower()
    if ext not in _ALERT_EXTS:
        flash("Alert sound must be mp3, wav, ogg, m4a, or webm.", "danger")
        return redirect(url_for("security.threat_map"))
    storage.stream.seek(0, os.SEEK_END)
    size = storage.stream.tell()
    storage.stream.seek(0)
    if size > _ALERT_MAX:
        flash("Alert sound must be 4 MB or smaller.", "danger")
        return redirect(url_for("security.threat_map"))

    dest_dir = _alert_dir()
    tmp = os.path.join(dest_dir, _ALERT_STEM + ".tmp")
    storage.save(tmp)
    try:
        from app.utils.clamav_scanner import scan_file

        result = scan_file(tmp) or {}
        status = result.get("status") or "error"
        if status not in ("clean", "skipped"):
            try:
                os.remove(tmp)
            except Exception:
                pass
            flash(result.get("message") or "Upload blocked by file scanner.", "danger")
            return redirect(url_for("security.threat_map"))
    except ImportError:
        pass
    except Exception as exc:
        current_app.logger.warning("threat-map alert scan skipped: %s", exc)

    _clear_alert_files()
    final = os.path.join(dest_dir, _ALERT_STEM + ext)
    os.replace(tmp, final)
    try:
        from app.utils.platform_auth import current_owner
        from app.utils.platform_settings import audit

        row = current_owner()
        audit(
            "security.threat_map_alert",
            owner_id=None if row is None else row.id,
            detail={"filename": name, "bytes": size},
        )
    except Exception:
        pass
    flash("Threat map alert sound saved. Live hits will play this file.", "success")
    return redirect(url_for("security.threat_map"))


@security_bp.route("/threat-map/summary")
@threat_map_json_required
def threat_map_summary():
    from . import threat_queries as tq

    data = tq.summary_for_window(_parse_window(allow_lifetime=True))
    data["ok"] = True
    return jsonify(data)


@security_bp.route("/threat-map/countries")
@threat_map_json_required
def threat_map_countries():
    from . import threat_queries as tq

    data = tq.countries_for_window(_parse_window(allow_lifetime=True), fill=True)
    data["ok"] = True
    return jsonify(data)


@security_bp.route("/threat-map/country/<iso2>")
@threat_map_json_required
def threat_map_country(iso2):
    from . import threat_queries as tq

    window = _parse_window(allow_lifetime=True)
    if window == "lifetime":
        data = tq.country_history_totals(iso2)
    else:
        data = tq.country_detail(iso2, window)
    data["ok"] = True
    return jsonify(data)


@security_bp.route("/threat-map/replay")
@threat_map_json_required
def threat_map_replay():
    from . import threat_queries as tq

    window = _parse_window(allow_lifetime=True)
    try:
        limit = int(request.args.get("limit") or 1500)
    except (TypeError, ValueError):
        limit = 1500
    try:
        after_id = int(request.args.get("after_id") or 0)
    except (TypeError, ValueError):
        after_id = 0
    data = tq.replay_events(window, limit=limit, after_id=after_id)
    data["ok"] = True
    return jsonify(data)


@security_bp.route("/threat-map/recent")
@threat_map_json_required
def threat_map_recent():
    from . import threat_queries as tq

    window = _parse_window()
    try:
        limit = int(request.args.get("limit") or 24)
    except (TypeError, ValueError):
        limit = 24
    limit = max(8, min(limit, 48))
    data = tq.recent_events(window, limit=limit)
    data["ok"] = True
    resp = jsonify(data)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp


@security_bp.route("/threat-map/live")
@threat_map_json_required
def threat_map_live():
    from . import threat_queries as tq

    try:
        since_id = int(request.args.get("since_id") or 0)
    except (TypeError, ValueError):
        since_id = 0
    try:
        limit = int(request.args.get("limit") or 80)
    except (TypeError, ValueError):
        limit = 80
    limit = max(1, min(limit, 120))
    arm = (request.args.get("arm") or "").strip().lower() in ("1", "true", "yes")
    follow = (request.args.get("follow") or "").strip().lower() in ("1", "true", "yes")
    data = tq.live_events(since_id=since_id, limit=limit, arm=arm, follow=follow)
    data["ok"] = True
    resp = jsonify(data)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp
