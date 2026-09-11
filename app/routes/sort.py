from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.builddb.builddb import db
from app.builddb.table_households import Household
from app.builddb.table_items import Item
from app.utils.household import household_id
from app.utils.permissions import role_of
from app.utils.sort_notes import (
    DEST_LABELS,
    DESTS,
    apply_item,
    normalize_item,
    parse_dump,
)

sort_bp = Blueprint("sort", __name__, url_prefix="/sort")


def _vehicles(hid):
    return (
        Item.query.filter_by(household_id=hid, item_type="vehicle")
        .order_by(Item.name.asc())
        .all()
    )


def _house(hid):
    return (
        Item.query.filter_by(household_id=hid, item_type="house")
        .order_by(Item.id.asc())
        .first()
    )


@sort_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    if role_of() == "child":
        flash("Ask a grown-up to sort notes.", "warning")
        return redirect(url_for("home.home"))
    hid = household_id()
    household = Household.query.get(hid)
    vehicles = _vehicles(hid)
    house = _house(hid)
    items = []
    used = ""
    error = ""
    raw = ""
    if request.method == "POST" and (request.form.get("op") or "preview") == "preview":
        raw = (request.form.get("raw") or "").strip()
        if not raw:
            flash("Paste the Discord dump, list, or wall of notes.", "danger")
        else:
            result = parse_dump(
                raw,
                household=household,
                vehicles=vehicles,
                house_name=house.name if house else None,
            )
            items = result.get("items") or []
            used = result.get("used") or ""
            error = result.get("error") or ""
            if not items:
                flash("Nothing to file in that paste.", "warning")
    return render_template(
        "sort.html",
        items=items,
        used=used,
        error=error,
        raw=raw,
        dests=DESTS,
        dest_labels=DEST_LABELS,
        vehicles=vehicles,
        has_house=bool(house),
    )


@sort_bp.route("/save", methods=["POST"])
@login_required
def save():
    if role_of() == "child":
        flash("Ask a grown-up to sort notes.", "warning")
        return redirect(url_for("home.home"))
    hid = household_id()
    vehicles = _vehicles(hid)
    house = _house(hid)
    keep = set(request.form.getlist("keep"))
    count = 0
    where = []
    try:
        n = int(request.form.get("count") or "0")
    except Exception:
        n = 0
    n = max(0, min(n, 40))
    for i in range(n):
        if str(i) not in keep:
            continue
        prefix = f"item-{i}-"
        card = normalize_item(
            {
                "dest": request.form.get(prefix + "dest"),
                "title": request.form.get(prefix + "title"),
                "body": request.form.get(prefix + "body"),
                "why": request.form.get(prefix + "why"),
                "due_on": request.form.get(prefix + "due_on"),
                "kind": request.form.get(prefix + "kind"),
                "agency": request.form.get(prefix + "agency"),
                "amount": request.form.get(prefix + "amount"),
                "source": request.form.get(prefix + "source"),
                "vehicle_hint": request.form.get(prefix + "vehicle_hint"),
                "system": request.form.get(prefix + "system"),
                "slot": request.form.get(prefix + "slot"),
                "visibility": request.form.get(prefix + "visibility"),
            }
        )
        ok, label = apply_item(
            hid, current_user, card, vehicles=vehicles, house=house
        )
        if ok and label != "skip":
            count += 1
            if label not in where:
                where.append(label)
    if count:
        db.session.commit()
        flash(
            f"Filed {count} " + ("bit." if count == 1 else "bits.")
            + ((" → " + ", ".join(where)) if where else ""),
            "success",
        )
    else:
        db.session.rollback()
        flash("Nothing was checked.", "info")
    return redirect(url_for("sort.index"))
