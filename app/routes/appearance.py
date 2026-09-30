from flask import Blueprint, abort, render_template, request, redirect, url_for, jsonify, make_response, flash
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
    from app.utils.dashboard import dashboard_prefs

    ctx = dict(
        themes=list(THEMES.values()),
        current=read_theme(),
        cal_url=links["https"],
        cal_links=links,
        cal_next="look",
        dash=dashboard_prefs(current_user),
    )
    ctx.update(_twofa_ctx())
    return render_template("appearance.html", **ctx)


def _twofa_ctx():
    """Look-page 2FA card. BOT accounts only for now."""
    from app.utils.passwords import reset_inbox_label
    from app.utils.twofa import twofa_method, twofa_settings

    if not bool(getattr(current_user, "is_bot", False)):
        return {"twofa": None}
    blob = twofa_settings(current_user)
    method = twofa_method(current_user)
    return {
        "twofa": {
            "method": method,
            "pending_secret": (blob.get("secret") or "") if not method else "",
            "inbox": (current_user.security_email or current_user.email or "").strip(),
            "reset_inbox": reset_inbox_label(current_user),
        }
    }


def _twofa_next():
    """Back to the first-sign-in wall while a bot still owes setup. Otherwise Look."""
    from app.utils.twofa import bot_setup_remaining

    nxt = (request.form.get("next") or "").strip()
    if bot_setup_remaining(current_user):
        return redirect(url_for("auth.bot_setup"))
    if nxt == "setup":
        return redirect(url_for("home.home"))
    return redirect(url_for("appearance.picker") + "#twofa")


@appearance_bp.route("/2fa/start", methods=["POST"])
@login_required
def twofa_start():
    from app.utils import twofa as twofa_util

    if not bool(getattr(current_user, "is_bot", False)):
        abort(403)
    if twofa_util.twofa_method(current_user):
        flash("2FA is already on.", "warning")
        return _twofa_next()
    twofa_util.begin_totp_setup(current_user)
    db.session.commit()
    return _twofa_next()


@appearance_bp.route("/2fa/qr.png")
@login_required
def twofa_qr():
    from app.utils import twofa as twofa_util
    from app.utils.qr_labels import qr_png_response

    if not bool(getattr(current_user, "is_bot", False)):
        abort(403)
    blob = twofa_util.twofa_settings(current_user)
    secret = (blob.get("secret") or "").strip()
    if not secret or twofa_util.twofa_method(current_user) == "app":
        abort(404)
    label = f"{current_user.username}@{(getattr(current_user.household, 'handle', '') or 'family')}"
    return qr_png_response(twofa_util.otpauth_url(secret, label), "twofa-qr.png")


@appearance_bp.route("/2fa/confirm", methods=["POST"])
@login_required
def twofa_confirm():
    from app.utils import twofa as twofa_util

    if not bool(getattr(current_user, "is_bot", False)):
        abort(403)
    ok, msg = twofa_util.confirm_totp_setup(current_user, request.form.get("code") or "")
    db.session.commit()
    flash(msg, "success" if ok else "danger")
    return _twofa_next()


@appearance_bp.route("/2fa/method", methods=["POST"])
@login_required
def twofa_set_method():
    """App codes or emailed codes — emailed ones land in the 2FA inbox."""
    from app.utils import twofa as twofa_util

    if not bool(getattr(current_user, "is_bot", False)):
        abort(403)
    want = (request.form.get("method") or "").strip().lower()
    if want == "email":
        if not twofa_util.twofa_inbox_for(current_user):
            flash("Name a 2FA email first — that is where codes would go.", "danger")
            return _twofa_next()
        twofa_util.save_twofa(current_user, method="email")
        db.session.commit()
        flash(f"2FA is now an emailed code to {twofa_util.twofa_inbox_for(current_user)}.", "success")
    elif want == "app":
        if not (twofa_util.twofa_settings(current_user).get("secret") or "").strip():
            flash("Scan the code and confirm one code from the app first.", "warning")
            return _twofa_next()
        twofa_util.save_twofa(current_user, method="app")
        db.session.commit()
        flash("2FA is now the authenticator app.", "success")
    else:
        flash("Pick the authenticator app or the emailed code.", "danger")
    return _twofa_next()


@appearance_bp.route("/2fa/off", methods=["POST"])
@login_required
def twofa_off():
    if not bool(getattr(current_user, "is_bot", False)):
        abort(403)
    flash(
        "A bot keeps 2FA on. A leader can clear it from People; the next sign-in sets it up again.",
        "warning",
    )
    return _twofa_next()


@appearance_bp.route("/security-email", methods=["POST"])
@login_required
def set_own_security_email():
    """Separate inboxes. A bot's reset inbox cannot be blank or the login email."""
    from app.builddb.table_users import User

    security = (request.form.get("security_email") or "").strip().lower() or None
    reset = (request.form.get("reset_email") or "").strip().lower() or None
    for addr in (security, reset):
        if addr and "@" not in addr:
            flash("That doesn't look like an email.", "danger")
            return _twofa_next()
        if addr:
            taken = User.query.filter(User.email == addr, User.id != current_user.id).first()
            if taken:
                flash("That email is already someone's login.", "danger")
                return _twofa_next()
    if bool(getattr(current_user, "is_bot", False)):
        login = (current_user.email or "").strip().lower()
        if not reset or "@" not in reset or (login and reset == login):
            flash("A bot needs a reset email that is not the login email.", "danger")
            return _twofa_next()
    current_user.security_email = security
    current_user.reset_email = reset
    db.session.commit()
    flash("Security emails saved. 2FA codes and reset links can now go to different inboxes.", "success")
    return _twofa_next()


@appearance_bp.route("/home-sheet")
@login_required
def home_sheet():
    from app.utils.dashboard import dashboard_prefs
    from app.utils.permissions import role_of

    return render_template(
        "appearance/home_sheet.html",
        dash=dashboard_prefs(current_user),
        is_child=role_of() == "child",
        dash_next="sheet",
        dash_compact=False,
    )


@appearance_bp.route("/calendar-sheet")
@login_required
def calendar_sheet():
    from app.builddb.table_households import Household
    from app.utils.calendar import ensure_calendar_token, member_subscribe
    from app.utils.household import household_id

    household = Household.query.get(household_id())
    token = ensure_calendar_token(current_user)
    cal_url = url_for("reminders.calendar_feed", token=token, _external=True)
    links = member_subscribe(current_user, household, cal_url)
    return render_template(
        "appearance/calendar_sheet.html",
        cal_url=links["https"],
        cal_links=links,
        cal_next="sheet",
    )


@appearance_bp.route("/dashboard", methods=["POST"])
@login_required
def set_dashboard():
    from app.utils.dashboard import save_dashboard

    tiles = request.form.getlist("tiles")
    save_dashboard(
        current_user,
        start=request.form.get("start") or "",
        tiles=tiles,
        show_needs=(request.form.get("show_needs") or "") in ("1", "on", "yes", "true"),
    )
    flash("Your home is saved. That's what opens for you.", "success")
    nxt = (request.form.get("next") or "").strip()
    if nxt == "sheet":
        return redirect(url_for("appearance.home_sheet"))
    if nxt == "home":
        return redirect(url_for("home.home"))
    return redirect(url_for("appearance.picker") + "#home")


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
    if nxt == "sheet":
        return redirect(url_for("appearance.calendar_sheet"))
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

    if (request.form.get("clear_calendar") or "") == "1":
        current_user.calendar_email = None
        current_user.calendar_mode = "manual"
        db.session.commit()
        flash("Calendar removed. Due dates stay on Family OS until you name an inbox again.", "success")
        return _calendar_next()
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
