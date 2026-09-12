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


def _calendar_next():
    nxt = (request.form.get("next") or "").strip()
    if nxt == "reminders":
        return redirect(url_for("reminders.index"))
    if nxt == "home":
        return redirect(url_for("home.home"))
    return redirect(url_for("appearance.picker") + "#calendar")


@appearance_bp.route("/notify", methods=["POST"])
@login_required
def set_notify():
    return set_calendar()


@appearance_bp.route("/calendar", methods=["POST"])
@login_required
def set_calendar():
    from app.utils.calendar import (
        calendar_target,
        guess_provider,
        normalize_cal_mode,
        normalize_provider,
    )

    email = (request.form.get("calendar_email") or "").strip().lower()
    if email and "@" not in email:
        flash("That doesn't look like an email for a calendar.", "danger")
        return _calendar_next()
    provider = normalize_provider(request.form.get("calendar_provider"), email)
    if not (request.form.get("calendar_provider") or "").strip() and email:
        provider = guess_provider(email)
    mode = normalize_cal_mode(request.form.get("calendar_mode"), "auto")
    email_due = (request.form.get("email_due") or "").strip() in ("1", "on", "yes", "both", "email")
    raw_via = (request.form.get("notify_via") or "").strip().lower()
    if raw_via in ("email", "calendar", "both", "off"):
        via = raw_via
    elif mode == "auto" and email_due:
        via = "both"
    elif mode == "auto":
        via = "calendar"
    elif email_due:
        via = "email"
    else:
        via = "off"

    current_user.calendar_email = email or None
    current_user.calendar_provider = provider
    current_user.calendar_mode = mode
    current_user.notify_via = via
    db.session.commit()
    target = calendar_target(current_user)
    if mode == "auto" and not target["cal_ready"]:
        flash("Auto-add needs the email of the calendar. Set it above.", "warning")
    elif mode == "auto":
        extra = " We'll also email you when it's due." if via in ("email", "both") else ""
        flash(f"Auto-add is on for {target['cal_label']}.{extra}", "success")
    else:
        flash("Manual. Due dates stay on Family OS until you add them.", "success")
    return _calendar_next()
