from flask import Blueprint, render_template, request, redirect, url_for, jsonify, make_response, flash
from flask_login import login_required, current_user

from app.builddb.builddb import db
from app.utils.themes import THEMES, normalize, save_user_theme, stamp_theme_cookie, read_theme

appearance_bp = Blueprint("appearance", __name__, url_prefix="/appearance")


@appearance_bp.route("/")
@login_required
def picker():
    from app.builddb.table_households import Household
    from app.utils.calendar import ensure_calendar_token, member_subscribe
    from app.utils.household import household_id

    household = Household.query.get(household_id())
    token = ensure_calendar_token(current_user)
    cal_url = url_for("reminders.calendar_feed", token=token, _external=True)
    links = member_subscribe(current_user, household, cal_url)
    return render_template(
        "appearance.html",
        themes=list(THEMES.values()),
        current=read_theme(),
        cal_url=links["https"],
        cal_links=links,
        cal_next="look",
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


@appearance_bp.route("/notify", methods=["POST"])
@login_required
def set_notify():
    via = (request.form.get("notify_via") or "both").strip().lower()
    if via not in ("email", "calendar", "both", "off"):
        via = "both"
    current_user.notify_via = via
    db.session.commit()
    flash("How you get reminders is saved.", "success")
    return redirect(url_for("appearance.picker"))
