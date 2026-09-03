"""Scan is a truth event. Apply consume / restock / open based on item type."""
from datetime import datetime, timedelta
from decimal import Decimal

from app.builddb.builddb import db
from app.builddb.table_items import Item
from app.builddb.table_grocery_items import GroceryItem
from app.builddb.table_grocery_list import GroceryListEntry
from app.builddb.table_scan_events import ScanEvent
from app.builddb.table_tools import Tool
from app.builddb.table_vehicles import Vehicle


def _dec(val, default="0"):
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal(default)


def find_item(household_id: int, barcode: str):
    code = (barcode or "").strip()
    if not code:
        return None
    item = Item.query.filter_by(household_id=household_id, barcode=code).first()
    if item:
        return item
    # FAM:{hid}:{item_id} payload from our own QR labels
    if code.upper().startswith("FAM:"):
        parts = code.split(":")
        if len(parts) >= 3:
            try:
                hid = int(parts[1])
                iid = int(parts[2])
            except ValueError:
                return None
            if hid != household_id:
                return None
            return Item.query.filter_by(household_id=household_id, id=iid).first()
    return None


def _sync_grocery_list(g: GroceryItem, item: Item, user_id):
    open_row = GroceryListEntry.query.filter_by(
        household_id=g.household_id, item_id=item.id, status="open"
    ).first()
    if g.needs_restock:
        if not open_row:
            db.session.add(
                GroceryListEntry(
                    household_id=g.household_id,
                    item_id=item.id,
                    name=item.name,
                    quantity_needed=max(_dec(g.restock_threshold), Decimal("1")),
                    status="open",
                    added_reason="auto_threshold",
                    created_by=user_id,
                )
            )
    elif open_row:
        open_row.status = "done"
        open_row.completed_at = datetime.utcnow()


def apply_grocery_stock(g: GroceryItem, item: Item, action: str, amount, user_id):
    qty = _dec(g.quantity)
    amt = _dec(amount, "1")
    if amt <= 0:
        amt = Decimal("1")
    if action == "restock":
        qty = qty + amt
        g.last_restocked_at = datetime.utcnow()
    else:
        qty = qty - amt
        if qty < 0:
            qty = Decimal("0")
        g.last_consumed_at = datetime.utcnow()
        g.consume_count = int(g.consume_count or 0) + 1
    g.quantity = qty
    thresh = _dec(g.restock_threshold, "1")
    g.is_in_stock = qty > 0
    g.needs_restock = qty <= thresh
    _sync_grocery_list(g, item, user_id)
    remaining = qty
    return {
        "quantity": float(remaining),
        "is_in_stock": bool(g.is_in_stock),
        "needs_restock": bool(g.needs_restock),
        "message": (
            f"{item.name} updated. {remaining} remaining."
            if action != "restock"
            else f"{item.name} restocked. {remaining} on hand."
        ),
    }


def consumption_hint(g: GroceryItem) -> str | None:
    extra = g.extra_data or {}
    if not g.last_consumed_at or not g.consume_count:
        return None
    # crude: days since created / consume_count if we stored first consume
    first = extra.get("first_consumed_at")
    try:
        if first:
            start = datetime.fromisoformat(str(first).replace("Z", ""))
        else:
            start = g.last_consumed_at
        days = max((datetime.utcnow() - start).total_seconds() / 86400.0, 1.0 / 24)
        rate = max(days / max(int(g.consume_count), 1), 1.0 / 24)
        qty = float(_dec(g.quantity))
        every = max(int(round(rate)), 1)
        if qty <= 0:
            return f"You typically use this every {every} days."
        left = max(int(round(rate * qty)), 1)
        return f"You use this about every {every} days. Estimated depletion: {left} days."
    except Exception:
        return None


def process_scan(household_id: int, user_id: int, barcode: str, action: str, amount=1):
    code = (barcode or "").strip()
    action = (action or "auto").strip().lower()
    item = find_item(household_id, code)
    event = ScanEvent(
        household_id=household_id,
        user_id=user_id,
        barcode=code,
        action=action,
        amount=_dec(amount, "1"),
        item_id=item.id if item else None,
    )
    db.session.add(event)

    if item is None:
        db.session.commit()
        return {
            "found": False,
            "barcode": code,
            "create": True,
            "message": "Unknown barcode for this household. Create a new item.",
        }

    payload = {
        "found": True,
        "barcode": code,
        "item_id": item.id,
        "item_type": item.item_type,
        "name": item.name,
        "create": False,
    }

    if item.item_type == "grocery":
        g = GroceryItem.query.filter_by(household_id=household_id, item_id=item.id).first()
        if g is None:
            g = GroceryItem(item_id=item.id, household_id=household_id, quantity=0)
            db.session.add(g)
        if action == "auto":
            action = "consume"
        if action in ("consume", "restock"):
            extra = dict(g.extra_data or {})
            if action == "consume" and not extra.get("first_consumed_at"):
                extra["first_consumed_at"] = datetime.utcnow().isoformat()
                g.extra_data = extra
            stock = apply_grocery_stock(g, item, action, amount, user_id)
            payload.update(stock)
            payload["hint"] = consumption_hint(g)
        else:
            payload["quantity"] = float(_dec(g.quantity))
            payload["message"] = f"Opened {item.name}."
    else:
        payload["message"] = f"Opened {item.name}."
        if item.item_type == "tool":
            t = Tool.query.filter_by(household_id=household_id, item_id=item.id).first()
            if t:
                payload["oil_type"] = t.oil_type
                payload["fuel_type"] = t.fuel_type
                payload["last_maintenance_at"] = (
                    t.last_maintenance_at.isoformat() if t.last_maintenance_at else None
                )
        if item.item_type == "vehicle":
            v = Vehicle.query.filter_by(household_id=household_id, item_id=item.id).first()
            if v:
                payload["oil_type"] = v.oil_type
                payload["current_mileage"] = v.current_mileage

    event.item_id = item.id
    event.action = action
    event.result_json = {"name": item.name, "type": item.item_type}
    db.session.commit()
    payload["action"] = action
    return payload
