from datetime import datetime
from flask import Blueprint, Response, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.builddb.builddb import db
from app.builddb.table_households import Household
from app.builddb.table_reminders import Reminder
from app.builddb.table_items import Item
from app.utils.calendar import (
    NOTIFY_CHOICES,
    ensure_calendar_token,
    household_ics,
    household_reminders_via,
    member_subscribe,
    user_for_calendar_token,
)
from app.utils.household import household_id, scoped
from app.utils.notify import announce_reminder, maybe_flush_due_emails
from app.utils.permissions import require_perm
from app.utils.reminders_copy import (
    REMINDER_TYPES,
    RECURRENCE,
    parse_recurrence,
    recurrence_label,
    type_label,
)

reminders_bp = Blueprint("reminders", __name__, url_prefix="/reminders")


@reminders_bp.route("/")
@login_required
def index():
    hid = household_id()
    maybe_flush_due_emails(hid)
    rows = scoped(Reminder).order_by(Reminder.due_at.asc()).all()
    items = scoped(Item).order_by(Item.name.asc()).all()
    household = Household.query.get(hid)
    token = ensure_calendar_token(current_user)
    cal_url = url_for("reminders.calendar_feed", token=token, _external=True)
    links = member_subscribe(current_user, household, cal_url)
    return render_template(
        "reminders.html",
        rows=rows,
        items=items,
        reminders_via=household_reminders_via(household),
        cal_url=links["https"],
        webcal=links["webcal"],
        cal_links=links,
        cal_next="reminders",
        can_set_via=bool(current_user.is_leader),
        reminder_types=REMINDER_TYPES,
        recurrence_choices=RECURRENCE,
        type_label=type_label,
        recurrence_label=recurrence_label,
    )


@reminders_bp.route("/add", methods=["POST"])
@login_required
@require_perm("maintain")
def add():
    from app.services.reminders import create_reminder

    row, err = create_reminder(
        hid=household_id(),
        user_id=current_user.id,
        title=request.form.get("title"),
        rtype=request.form.get("type") or "custom",
        due_at=request.form.get("due_at"),
        linked_item_id=request.form.get("linked_item_id"),
        recurrence=request.form.get("recurrence"),
        notify_via=request.form.get("notify_via"),
    )
    if err:
        flash(err, "danger")
        return redirect(url_for("reminders.index"))
    from app.utils.notify import announce_flash

    note = announce_flash(current_user, row)
    if note:
        flash(note, "success")
    return redirect(url_for("reminders.index"))


@reminders_bp.route("/<int:rid>/done", methods=["POST"])
@login_required
@require_perm("maintain")
def done(rid):
    from app.services.reminders import complete

    row = scoped(Reminder).filter_by(id=rid).first_or_404()
    complete(row)
    db.session.commit()
    return redirect(url_for("reminders.index"))


@reminders_bp.route("/calendar/<token>.ics")
def calendar_feed(token):
    user = user_for_calendar_token(token)
    if user is None:
        return Response("Unknown calendar.", status=404, mimetype="text/plain")
    household = Household.query.get(user.household_id)
    rows = (
        Reminder.query.filter_by(household_id=user.household_id, status="open")
        .order_by(Reminder.due_at.asc())
        .all()
    )
    body = household_ics(household, rows, member_feed=True)
    resp = Response(body, mimetype="text/calendar; charset=utf-8")
    resp.headers["Content-Type"] = "text/calendar; charset=utf-8; method=PUBLISH"
    resp.headers["Content-Disposition"] = 'inline; filename="family-os.ics"'
    resp.headers["Cache-Control"] = "public, max-age=300"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@reminders_bp.route("/calendar/rotate", methods=["POST"])
@login_required
def rotate_calendar():
    from app.utils.calendar import rotate_calendar_token

    rotate_calendar_token(current_user)
    flash("New calendar link. Update the subscription on your phone.", "success")
    nxt = (request.form.get("next") or "").strip()
    if nxt == "look":
        return redirect(url_for("appearance.picker") + "#calendar")
    if nxt == "home":
        return redirect(url_for("home.home"))
    return redirect(url_for("reminders.index"))
