"""Household what-happened log. Parents can undo a kid's tap."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.builddb.builddb import db


def _in_house(obj, row) -> bool:
    if obj is None or row is None:
        return False
    try:
        return int(getattr(obj, "household_id", 0) or 0) == int(row.household_id)
    except (TypeError, ValueError):
        return False


def _num(val):
    if val is None:
        return None
    if isinstance(val, Decimal):
        return float(val)
    try:
        return float(val)
    except Exception:
        return val


def _who(user=None, user_id=None) -> str:
    from flask_login import current_user

    u = user if user is not None else current_user
    if u is None or not getattr(u, "is_authenticated", False):
        u = None
        if user_id:
            try:
                from app.builddb.table_users import User

                u = User.query.get(int(user_id))
            except Exception:
                u = None
    if u is None:
        return "Someone"
    return (getattr(u, "name", None) or getattr(u, "username", None) or "Someone").split()[0]


def record(
    *,
    action: str,
    summary: str,
    target_table: str | None = None,
    target_id: int | None = None,
    item_id: int | None = None,
    old_json=None,
    new_json=None,
    reversible: bool = True,
    user_id=None,
    household_id=None,
):
    try:
        from flask_login import current_user
        from app.builddb.table_household_activity import HouseholdActivity

        uid = user_id
        if uid is None and getattr(current_user, "is_authenticated", False):
            uid = current_user.id
        hid = household_id
        if hid is None:
            from app.utils.household import household_id as current_household

            hid = current_household()
        row = HouseholdActivity(
            household_id=hid,
            user_id=uid,
            action=(action or "do")[:40],
            summary=(summary or action)[:240],
            target_table=(target_table or None),
            target_id=target_id,
            item_id=item_id,
            old_json=old_json,
            new_json=new_json,
            reversible=bool(reversible),
        )
        db.session.add(row)
        db.session.flush()
        return row
    except Exception as exc:
        print(f"[activity] record failed: {exc}", flush=True)
        return None


def log_grocery(item, g, action: str, prev_qty, new_qty, amount, user_id=None):
    from app.utils.scan import qty_label

    who = _who(user_id=user_id)
    name = getattr(item, "name", None) or "item"
    prev_s = qty_label(prev_qty)
    new_s = qty_label(new_qty)
    if action == "restock":
        summary = f"{who} added {qty_label(amount)} {name} ({prev_s} → {new_s})"
    elif action == "need_more":
        summary = f"{who} said {name} needs more ({new_s} on hand)"
    else:
        summary = f"{who} used {qty_label(amount)} {name} ({prev_s} → {new_s})"
    return record(
        action=f"grocery.{action}",
        summary=summary,
        target_table="grocery_items",
        target_id=getattr(g, "id", None),
        item_id=getattr(item, "id", None),
        old_json={
            "quantity": _num(prev_qty),
            "needs_restock": bool(getattr(g, "needs_restock", False)),
        },
        new_json={"quantity": _num(new_qty), "amount": _num(amount)},
        user_id=user_id,
        household_id=getattr(item, "household_id", None),
    )


def newest_at(hid: int):
    """The last row this house stored, outside the recent window."""
    from app.builddb.table_household_activity import HouseholdActivity

    row = (
        HouseholdActivity.query.filter_by(household_id=int(hid))
        .order_by(HouseholdActivity.id.desc())
        .first()
    )
    return row.created_at if row is not None else None


def recent(hid: int, *, limit: int = 40, hours: int | None = 48):
    from datetime import timedelta
    from app.builddb.table_household_activity import HouseholdActivity
    from app.builddb.table_users import User

    q = HouseholdActivity.query.filter_by(household_id=hid)
    if hours:
        since = datetime.utcnow() - timedelta(hours=int(hours))
        q = q.filter(HouseholdActivity.created_at >= since)
    rows = q.order_by(HouseholdActivity.created_at.desc(), HouseholdActivity.id.desc()).limit(limit).all()
    uids = {r.user_id for r in rows if r.user_id} | {r.reversed_by for r in rows if r.reversed_by}
    people = {}
    if uids:
        people = {u.id: u for u in User.query.filter(User.id.in_(list(uids))).all()}
    out = []
    for r in rows:
        actor = people.get(r.user_id)
        out.append(
            {
                "id": r.id,
                "action": r.action,
                "summary": r.summary,
                "who": (actor.name or actor.username) if actor else "Someone",
                "when": r.created_at,
                "item_id": r.item_id,
                "can_reverse": bool(r.reversible) and r.reversed_at is None,
                "reversed_at": r.reversed_at,
                "old_qty": (r.old_json or {}).get("quantity") if isinstance(r.old_json, dict) else None,
                "new_qty": (r.new_json or {}).get("quantity") if isinstance(r.new_json, dict) else None,
            }
        )
    return out


def reverse_row(row, *, by_id: int | None) -> tuple[bool, str]:
    if row is None:
        return False, "Nothing to undo."
    if row.reversed_at is not None:
        return False, "Already put back."
    if not row.reversible:
        return False, "That one can't be undone."
    action = (row.action or "")
    try:
        spec = row.old_json if isinstance(row.old_json, dict) else {}
        if spec.get("undo"):
            from app.utils.activity_undo import undo_recorded

            ok, msg = undo_recorded(row, actor_id=by_id)
        elif action.startswith("grocery."):
            ok, msg = _undo_grocery(row)
        elif action == "item.remove":
            ok, msg = _undo_item_remove(row)
        elif action == "part.off":
            ok, msg = _undo_part_off(row)
        elif action == "part.add":
            ok, msg = _undo_part_add(row)
        elif action == "scan.host_attach":
            ok, msg = _undo_host_attach(row)
        elif action == "user.remove":
            ok, msg = _undo_user_remove(row)
        else:
            return False, "Don't know how to undo that."
        if not ok:
            db.session.rollback()
            return False, msg
        row.reversed_at = datetime.utcnow()
        row.reversed_by = by_id
        db.session.commit()
        return True, msg
    except Exception as exc:
        db.session.rollback()
        return False, f"Could not undo: {exc}"


def _undo_grocery(row) -> tuple[bool, str]:
    from app.builddb.table_items import Item
    from app.utils.scan import set_quantity, _sync_grocery_list, qty_label

    item = Item.query.get(row.item_id)
    if item is None or item.grocery is None or not _in_house(item, row):
        return False, "That grocery is gone."
    g = item.grocery
    old = row.old_json if isinstance(row.old_json, dict) else {}
    prev = old.get("quantity")
    if prev is None:
        return False, "No old count to restore."
    set_quantity(g, prev)
    if "needs_restock" in old:
        g.needs_restock = bool(old.get("needs_restock"))
    _sync_grocery_list(g, item, row.user_id)
    return True, f"{item.name} is back to {qty_label(prev)}."


def _undo_user_remove(row) -> tuple[bool, str]:
    from app.builddb.table_users import User
    from app.utils.people import undo_remove

    user = User.query.get(row.target_id)
    if not _in_house(user, row):
        return False, "Can't find that person."
    old = row.old_json if isinstance(row.old_json, dict) else {}
    return undo_remove(user, old)


def _undo_item_remove(row) -> tuple[bool, str]:
    from app.builddb.table_items import Item

    item = Item.query.get(row.target_id or row.item_id)
    if item is None or not _in_house(item, row):
        return False, "Can't find that item."
    item.removed_at = None
    extra = item.extra_data if isinstance(item.extra_data, dict) else {}
    old_code = extra.pop("removed_barcode", None)
    if old_code and not item.barcode:
        item.barcode = old_code
        item.extra_data = extra or None
    return True, f"{item.name} is back in the house."


def _undo_part_off(row) -> tuple[bool, str]:
    from app.builddb.table_vehicle_parts import VehiclePart

    part = VehiclePart.query.get(row.target_id)
    if part is None or not _in_house(part, row):
        return False, "Can't find that part."
    part.is_current = True
    part.status = "installed"
    return True, f"{part.name} is back on."


def _undo_part_add(row) -> tuple[bool, str]:
    from app.builddb.table_vehicle_parts import VehiclePart

    part = VehiclePart.query.get(row.target_id)
    if part is None or not _in_house(part, row):
        return False, "Can't find that part."
    part.is_current = False
    part.status = "retired"
    return True, f"{part.name} taken off again (wasn't supposed to be added)."


def _undo_host_attach(row) -> tuple[bool, str]:
    from app.builddb.table_items import Item
    from app.builddb.table_vehicle_parts import VehiclePart

    item = Item.query.get(row.item_id)
    if item is None or not _in_house(item, row):
        return False, "Can't find that scan."
    old = row.old_json if isinstance(row.old_json, dict) else {}
    new = row.new_json if isinstance(row.new_json, dict) else {}
    item.linked_item_id = old.get("linked_item_id")
    part_id = new.get("part_id") or row.target_id
    if part_id and new.get("part_id"):
        part = VehiclePart.query.get(part_id)
        if part is not None:
            part.is_current = False
            part.status = "retired"
    if new.get("consumed") and item.grocery is not None:
        from app.utils.scan import set_quantity, clamp_qty

        set_quantity(item.grocery, clamp_qty(item.grocery.quantity) + 1)
    return True, f"Undid {item.name} on that equipment."


def set_item_qty(item, qty, *, user_id=None) -> tuple[bool, str]:
    from app.utils.scan import set_quantity, _sync_grocery_list, qty_label, clamp_qty

    if item is None or item.grocery is None:
        return False, "Not a grocery."
    g = item.grocery
    prev = clamp_qty(g.quantity)
    new = clamp_qty(qty)
    set_quantity(g, new)
    g.needs_restock = new <= clamp_qty(g.restock_threshold, "1")
    _sync_grocery_list(g, item, user_id)
    record(
        action="grocery.set",
        summary=f"{_who()} set {item.name} to {qty_label(new)} (was {qty_label(prev)})",
        target_table="grocery_items",
        target_id=g.id,
        item_id=item.id,
        old_json={"quantity": _num(prev), "needs_restock": bool(g.needs_restock)},
        new_json={"quantity": _num(new)},
        user_id=user_id,
    )
    db.session.commit()
    return True, f"{item.name} is now {qty_label(new)}."
