from flask import Blueprint, render_template, request, redirect, url_for, jsonify, make_response
from flask_login import login_required, current_user

from app.utils.themes import THEMES, normalize, save_user_theme, stamp_theme_cookie, read_theme

appearance_bp = Blueprint("appearance", __name__, url_prefix="/appearance")


@appearance_bp.route("/")
@login_required
def picker():
    return render_template(
        "appearance.html",
        themes=list(THEMES.values()),
        current=read_theme(),
    )


@appearance_bp.route("/theme", methods=["POST"])
@login_required
def set_theme():
    data = request.get_json(silent=True) or request.form
    theme_id = normalize(data.get("theme"))
    save_user_theme(current_user, theme_id)
    if request.is_json or request.headers.get("X-Requested-With") == "fetch":
        resp = jsonify({"ok": True, "theme": theme_id, "color": THEMES[theme_id]["color"]})
        stamp_theme_cookie(resp, theme_id)
        return resp
    resp = make_response(redirect(url_for("appearance.picker")))
    stamp_theme_cookie(resp, theme_id)
    return resp
