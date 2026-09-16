from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app.builddb.builddb import db
from app.builddb.table_items import Item
from app.builddb.table_grocery_list import GroceryListEntry
from app.utils.household import household_id, scoped
from app.utils.permissions import require_perm, can
from app.utils.scan import stock_status, STATUS_OUT, STATUS_LOW, STATUS_WANT, apply_grocery_stock, qty_label

groceries_bp = Blueprint("groceries", __name__, url_prefix="/groceries")


def _pantry_groups(items):
    want, out, low, ok = [], [], [], []
    for item in items:
        g = item.grocery
        status = stock_status(g) if g is not None else STATUS_WANT
        if status == STATUS_WANT:
            want.append(item)
        elif status == STATUS_OUT:
            out.append(item)
        elif status == STATUS_LOW:
            low.append(item)
        else:
            ok.append(item)
    return want, out, low, ok


def _place_of(item):
    g = getattr(item, "grocery", None)
    return ((g.default_location if g else None) or "").strip()


def _matches(item, needle: str) -> bool:
    if not needle:
        return True
    n = needle.lower()
    g = getattr(item, "grocery", None)
    blob = " ".join(
        [
            item.name or "",
            (g.brand if g else "") or "",
            (g.default_location if g else "") or "",
            (g.size if g else "") or "",
            item.category or "",
        ]
    ).lower()
    return n in blob


def _rooms(items):
    rooms = {}
    for item in items:
        room = _place_of(item) or "No room yet"
        rooms.setdefault(room, []).append(item)
    return rooms


@groceries_bp.route("/")
@login_required
def index():
    hid = household_id()
    place = (request.args.get("place") or "").strip()
    qtext = (request.args.get("q") or "").strip()
    q = (
        Item.query.options(joinedload(Item.grocery))
        .filter_by(household_id=hid, item_type="grocery")
        .filter(Item.removed_at.is_(None))
        .order_by(Item.name.asc())
        .all()
    )
    if qtext:
        q = [item for item in q if _matches(item, qtext)]
    want_all, out_all, low_all, ok_all = _pantry_groups(q)
    all_hand = ok_all + low_all
    place_counts = {room: len(rows) for room, rows in _rooms(all_hand).items()}
    if place:
        if place.lower() == "no room yet":
            q = [item for item in q if not _place_of(item)]
        else:
            q = [item for item in q if _place_of(item).lower() == place.lower()]
    want_items, out_items, low_items, ok_items = _pantry_groups(q)
    hand_items = ok_items + low_items
    hand_items.sort(key=lambda i: (_place_of(i).lower(), (i.name or "").lower()))
    view = (request.args.get("view") or "hand").strip().lower()
    if view not in ("hand", "out", "want", "all"):
        view = "hand"
    rooms = _rooms(hand_items) if view == "hand" else {}
    return render_template(
        "groceries.html",
        items=q,
        want_items=want_items,
        out_items=out_items,
        low_items=low_items,
        ok_items=ok_items,
        hand_items=hand_items,
        rooms=rooms,
        view=view,
        place=place,
        q=qtext,
        place_counts=place_counts,
        counts={
            "hand": len(hand_items),
            "out": len(out_items),
            "want": len(want_items),
            "all": len(q),
        },
        ai_ready=_ai_ready(),
        pantry_ai_report=session.pop("pantry_ai_report", None),
    )


def _ai_ready() -> bool:
    try:
        from app.builddb.table_households import Household
        from app.utils.ai import get_ai_config

        return bool(get_ai_config(Household.query.get(household_id()), household_only=True).get("ready"))
    except Exception:
        return False


@groceries_bp.route("/ai-place", methods=["POST"])
@login_required
@require_perm("edit_grocery")
def ai_place():
    from flask import session
    from app.builddb.table_households import Household
    from app.utils.classify import parse_pantry_places

    hid = household_id()
    household = Household.query.get(hid)
    items = (
        Item.query.options(joinedload(Item.grocery))
        .filter_by(household_id=hid, item_type="grocery")
        .filter(Item.removed_at.is_(None))
        .order_by(Item.name.asc())
        .all()
    )
    only_empty = (request.form.get("only_empty") or "1") == "1"
    if only_empty:
        items = [i for i in items if i.grocery and not (i.grocery.default_location or "").strip()]
    report = parse_pantry_places(household, items)
    db.session.commit()
    session["pantry_ai_report"] = report
    if report.get("error") and not report.get("moved"):
        flash(report["error"], "danger")
    elif report.get("moved"):
        flash(
            f"AI put {report['moved']} item(s) in rooms."
            if report.get("used_ai")
            else f"Guessed rooms for {report['moved']} item(s).",
            "success",
        )
    else:
        flash("Rooms already looked fine. Nothing moved.", "info")
    return redirect(url_for("groceries.index", view="hand"))


def _basket_payload(rows):
    items = {}
    ids = [r.item_id for r in rows if r.item_id]
    if ids:
        hid = rows[0].household_id
        found = (
            Item.query.options(joinedload(Item.grocery))
            .filter(Item.household_id == hid, Item.id.in_(ids))
            .all()
        )
        items = {i.id: i for i in found}
    out = []
    for r in rows:
        place = ""
        image_url = ""
        if r.item_id:
            item = items.get(r.item_id)
            if item and item.grocery:
                place = (item.grocery.default_location or "").strip()
            if item:
                from app.utils.thumbs import item_thumb_url

                image_url = item_thumb_url(item) or ""
        out.append(
            {
                "id": r.id,
                "name": r.name,
                "reason": r.added_reason or "",
                "quantity_needed": qty_label(r.quantity_needed) if r.quantity_needed else "",
                "item_id": r.item_id,
                "place": place,
                "status": r.status,
                "image_url": image_url,
            }
        )
    return out


@groceries_bp.route("/list")
@login_required
def grocery_list():
    rows = (
        scoped(GroceryListEntry)
        .filter_by(status="open")
        .order_by(GroceryListEntry.created_at.desc())
        .all()
    )
    want_rows = [r for r in rows if (r.added_reason or "") == "want"]
    need_rows = [r for r in rows if (r.added_reason or "") != "want"]
    packed = {p["id"]: p for p in _basket_payload(rows)}
    for r in rows:
        r.image_url = (packed.get(r.id) or {}).get("image_url") or ""
    return render_template(
        "grocery_list.html",
        rows=rows,
        want_rows=want_rows,
        need_rows=need_rows,
        can_add=can("scan") or can("edit_grocery"),
        can_check=can("scan") or can("edit_grocery"),
    )


@groceries_bp.route("/list.json")
@login_required
def grocery_list_json():
    rows = (
        scoped(GroceryListEntry)
        .filter_by(status="open")
        .order_by(GroceryListEntry.created_at.desc())
        .all()
    )
    return jsonify({"rows": _basket_payload(rows)})


@groceries_bp.route("/list/add", methods=["POST"])
@login_required
def list_add():
    if not (can("scan") or can("edit_grocery")):
        flash("You cannot add to the basket.", "warning")
        return redirect(url_for("groceries.grocery_list"))
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Name required.", "danger")
        return redirect(url_for("groceries.grocery_list"))
    db.session.add(
        GroceryListEntry(
            household_id=household_id(),
            name=name,
            status="open",
            added_reason="want",
            created_by=current_user.id,
        )
    )
    db.session.commit()
    return redirect(url_for("groceries.grocery_list"))


def _check_off(row, *, restock=True):
    if restock and row.item_id:
        item = Item.query.filter_by(id=row.item_id, household_id=row.household_id).first()
        if item and item.grocery:
            apply_grocery_stock(
                item.grocery,
                item,
                "restock",
                row.quantity_needed or 1,
                current_user.id,
            )
    row.status = "done"
    row.completed_at = datetime.utcnow()
    if row.item_id:
        extras = GroceryListEntry.query.filter_by(
            household_id=row.household_id, item_id=row.item_id, status="open"
        ).all()
        for extra in extras:
            extra.status = "done"
            extra.completed_at = row.completed_at


@groceries_bp.route("/list/<int:entry_id>/done", methods=["POST"])
@login_required
def list_done(entry_id):
    if not (can("scan") or can("edit_grocery")):
        flash("Ask a grown-up to check that off.", "warning")
        return redirect(url_for("groceries.grocery_list"))
    row = scoped(GroceryListEntry).filter_by(id=entry_id).first_or_404()
    _check_off(row)
    db.session.commit()
    if request.is_json or request.headers.get("X-Requested-With") == "fetch":
        return jsonify({"ok": True, "id": row.id, "status": "done"})
    return redirect(url_for("groceries.grocery_list"))


@groceries_bp.route("/list/<int:entry_id>/toggle", methods=["POST"])
@login_required
def list_toggle(entry_id):
    if not (can("scan") or can("edit_grocery")):
        return jsonify({"error": "not allowed"}), 403
    row = scoped(GroceryListEntry).filter_by(id=entry_id).first_or_404()
    if row.status == "open":
        _check_off(row)
    else:
        row.status = "open"
        row.completed_at = None
    db.session.commit()
    return jsonify({"ok": True, "id": row.id, "status": row.status})


@groceries_bp.route("/list/<int:entry_id>/remove", methods=["POST"])
@login_required
@require_perm("edit_grocery")
def list_remove(entry_id):
    row = scoped(GroceryListEntry).filter_by(id=entry_id).first_or_404()
    db.session.delete(row)
    db.session.commit()
    return redirect(url_for("groceries.grocery_list"))
