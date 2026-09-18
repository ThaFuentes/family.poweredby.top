from flask import Blueprint, render_template, redirect, url_for
from flask_login import current_user

from app.utils.household import household_id
from app.utils.needs import home_dashboard
from app.utils.permissions import role_of

home_bp = Blueprint("home", __name__)


@home_bp.route("/open")
def open_start():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    from app.utils.dashboard import start_url

    return redirect(start_url(current_user))


@home_bp.route("/about")
def about():
    if current_user.is_authenticated:
        return redirect(url_for("home.home"))
    return render_template("landing.html")


@home_bp.route("/")
def home():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    hid = household_id()
    try:
        from app.utils.notify import maybe_flush_due_emails

        maybe_flush_due_emails(hid)
    except Exception:
        pass
    is_child = role_of() == "child"
    dash = home_dashboard(hid, is_child=is_child, user_id=current_user.id)
    from app.utils.calendar import ensure_calendar_token, member_subscribe
    from app.builddb.table_households import Household as HouseholdRow

    household = getattr(current_user, "household", None) or HouseholdRow.query.get(hid)
    token = ensure_calendar_token(current_user)
    cal_url = url_for("reminders.calendar_feed", token=token, _external=True)
    cal_links = member_subscribe(current_user, household, cal_url)
    from app.utils.dashboard import dashboard_prefs

    prefs = dashboard_prefs(current_user)
    tmpl = "home_kid.html" if is_child else "home.html"
    return render_template(
        tmpl,
        counts=dash["counts"],
        needs=dash["needs"],
        house=dash["house"],
        is_child=is_child,
        cal_url=cal_links["https"],
        cal_links=cal_links,
        cal_next="home",
        dash=prefs,
    )
