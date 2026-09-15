"""Scan is a truth event. Kids scan, then tap Just used / Needs more / Got more."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.builddb.builddb import db
from app.builddb.table_items import Item
from app.builddb.table_grocery_items import GroceryItem
from app.builddb.table_grocery_list import GroceryListEntry
from app.builddb.table_scan_events import ScanEvent
from app.builddb.table_tools import Tool
from app.builddb.table_vehicles import Vehicle

STATUS_OUT = "out"
STATUS_LOW = "low"
STATUS_OK = "ok"
STATUS_WANT = "want"

HEADLINES = {
    STATUS_OUT: "Out",
    STATUS_LOW: "Need more",
    STATUS_OK: "In stock",
    STATUS_WANT: "Want",
}

_ACTION_ALIASES = {
    "auto": "check",
    "lookup": "check",
    "status": "check",
    "": "check",
    "use": "consume",
    "used": "consume",
    "just_used": "consume",
    "just-used": "consume",
    "bought": "restock",
    "got_more": "restock",
    "got-more": "restock",
    "got_it": "restock",
    "got-it": "restock",
    "needs_more": "need_more",
    "needs-more": "need_more",
    "need-more": "need_more",
    "want": "want",
    "wish": "want",
    "wishlist": "want",
    "want_this": "want",
    "set": "set",
    "set_count": "set",
    "on_hand": "set",
    "in_use": "consume",
    "into": "into",
    "into_house": "into",
    "inventory": "into",
    "miles": "mileage",
    "odometer": "mileage",
    "hours": "hours",
}


def _dec(val, default="0"):
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal(default)


def clamp_qty(val, default="0") -> Decimal:
    """Household counts never go below zero."""
    q = _dec(val, default)
    if q < 0:
        return Decimal("0")
    return q


def qty_label(val) -> str:
    q = clamp_qty(val)
    if q == q.to_integral_value():
        return str(int(q))
    return format(q.normalize(), "f")


def set_quantity(g: GroceryItem, val) -> Decimal:
    q = clamp_qty(val)
    g.quantity = q
    g.is_in_stock = q > 0
    return q


def ever_had(g: GroceryItem) -> bool:
    """True once this household has stocked or used the item. False = want / never had."""
    if g is None:
        return False
    if int(g.consume_count or 0) > 0:
        return True
    return bool(g.last_restocked_at or g.last_consumed_at)


def stock_status(g: GroceryItem) -> str:
    qty = clamp_qty(g.quantity)
    thresh = clamp_qty(g.restock_threshold, "1")
    if qty > 0:
        if qty <= thresh or bool(g.needs_restock):
            return STATUS_LOW
        return STATUS_OK
    if ever_had(g):
        return STATUS_OUT
    return STATUS_WANT


def find_item(household_id: int, barcode: str):
    code = (barcode or "").strip()
    if not code:
        return None
    item = (
        Item.query.filter_by(household_id=household_id, barcode=code)
        .filter(Item.removed_at.is_(None))
        .first()
    )
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
            return (
                Item.query.filter_by(household_id=household_id, id=iid)
                .filter(Item.removed_at.is_(None))
                .first()
            )
    return None


def _open_list_row(g: GroceryItem, item: Item):
    return GroceryListEntry.query.filter_by(
        household_id=g.household_id, item_id=item.id, status="open"
    ).first()


def _sync_grocery_list(g: GroceryItem, item: Item, user_id) -> bool:
    """Keep the shopping list in sync with stock. Returns whether it is on the list."""
    open_row = _open_list_row(g, item)
    status = stock_status(g)
    if g.needs_restock or status != STATUS_OK:
        if status == STATUS_WANT:
            reason = "want"
        elif status == STATUS_OUT:
            reason = "out"
        else:
            reason = "need_more"
        if not open_row:
            db.session.add(
                GroceryListEntry(
                    household_id=g.household_id,
                    item_id=item.id,
                    name=item.name,
                    quantity_needed=max(clamp_qty(g.restock_threshold, "1"), Decimal("1")),
                    status="open",
                    added_reason=reason,
                    created_by=user_id,
                )
            )
        else:
            open_row.added_reason = reason
            open_row.name = item.name
        return True
    if open_row:
        open_row.status = "done"
        open_row.completed_at = datetime.utcnow()
    return False


def _household_of(item):
    try:
        from app.builddb.table_households import Household

        return Household.query.get(item.household_id)
    except Exception:
        return None


def _places_for(item) -> list:
    try:
        from app.utils.places import list_places

        return list_places(_household_of(item))
    except Exception:
        return []


def _ai_ready(item) -> bool:
    try:
        from app.utils.ai import get_ai_config

        return bool(get_ai_config(_household_of(item), household_only=True).get("ready"))
    except Exception:
        return False


def apply_place(g: GroceryItem, item: Item, *, location=None, skip_place=False) -> dict:
    """Remember a room, or skip. AI/memory fill in when we can."""
    from app.builddb.table_households import Household
    from app.utils.places import remember_upc, recall_upc, snap_location

    household = Household.query.get(item.household_id)
    report = ((g.extra_data or {}).get("ai") if isinstance(g.extra_data, dict) else None) or {}
    if skip_place:
        return {"needs_place": False, "skipped_place": True, "ai_report": report}
    chosen = snap_location(location, household) if location else None
    if chosen:
        g.default_location = chosen
        try:
            remember_upc(
                household,
                item.barcode or "",
                {"location": chosen, "name": item.name, "item_type": item.item_type},
            )
        except Exception:
            pass
        return {"needs_place": False, "ai_report": report, "location": chosen}
    if (g.default_location or "").strip():
        return {"needs_place": False, "ai_report": report, "location": g.default_location}
    mem = None
    try:
        mem = recall_upc(household, item.barcode or "")
    except Exception:
        mem = None
    if mem and mem.get("location"):
        g.default_location = snap_location(mem["location"], household) or mem["location"]
        return {"needs_place": False, "from_memory": True, "ai_report": report, "location": g.default_location}
    try:
        from app.utils.classify import place_new_grocery
        from app.utils.barcode_lookup import lookup_product

        lookup = lookup_product(item.barcode) if item.barcode else {"name": item.name}
        report = place_new_grocery(item, g, lookup, household)
    except Exception:
        pass
    has = bool((g.default_location or "").strip())
    return {
        "needs_place": not has,
        "ai_report": report,
        "location": g.default_location,
    }


def grocery_payload(g: GroceryItem, item: Item, action="check", on_list=False, amount=1, prev_qty=None):
    status = stock_status(g)
    qty = qty_label(g.quantity)
    unit = (g.unit or "each").strip() or "each"
    amt = qty_label(amount)
    loc = (g.default_location or "").strip()

    if action == "set":
        message = f"{item.name} is {qty} {unit} on hand."
    elif action == "restock":
        if status == STATUS_OK:
            message = f"Got more {item.name}. {qty} {unit} now."
        elif status == STATUS_LOW:
            message = f"Got more {item.name}. {qty} {unit} now — still need more."
        else:
            message = f"Got more {item.name}, but the count is still 0."
    elif action == "want":
        message = f"{item.name} is on the want list."
    elif action == "need_more":
        if status == STATUS_WANT:
            message = f"{item.name} is on the want list."
        elif status == STATUS_OUT:
            message = f"{item.name} is out. On the basket."
        else:
            message = f"{item.name} needs more. On the basket."
    elif action == "consume":
        if status == STATUS_WANT or (prev_qty is not None and clamp_qty(prev_qty) <= 0 and not ever_had(g)):
            message = f"We don't have {item.name} yet. It's on the want list."
        elif prev_qty is not None and clamp_qty(prev_qty) <= 0:
            message = f"Already out of {item.name}. Count stays at 0."
        elif status == STATUS_OUT:
            message = f"Just used the last {item.name}. We're out."
        elif status == STATUS_LOW:
            message = f"Just used {item.name}. {qty} {unit} left — need more."
        else:
            message = f"Just used {item.name}. {qty} {unit} left."
    else:
        if status == STATUS_WANT:
            message = f"We don't have {item.name} yet."
        elif status == STATUS_OUT:
            message = f"We're out of {item.name}."
        elif status == STATUS_LOW:
            message = f"{item.name} needs more. {qty} {unit} left."
        else:
            message = f"{item.name}: {qty} {unit} on hand."

    listed = "shopping list" in message.lower() or "want list" in message.lower() or "basket" in message.lower()
    if on_list and not listed:
        if status == STATUS_WANT:
            message = message.rstrip(".") + ". On the want list."
        else:
            message = message.rstrip(".") + ". On the basket."

    return {
        "quantity": float(clamp_qty(g.quantity)),
        "quantity_label": qty,
        "unit": unit,
        "threshold": float(clamp_qty(g.restock_threshold, "1")),
        "is_in_stock": status in (STATUS_OK, STATUS_LOW),
        "needs_restock": status != STATUS_OK,
        "status": status,
        "headline": HEADLINES[status],
        "on_list": bool(on_list),
        "message": message,
        "location": loc or None,
        "brand": (g.brand or "").strip() or None,
        "image_url": (g.image_url or "").strip() or None,
        "allergens": (g.allergens or "").strip() or None,
        "ingredients": (g.ingredients or "").strip() or None,
        "facts": ((g.extra_data or {}).get("product") if isinstance(g.extra_data, dict) else None) or {},
        "ai_report": ((g.extra_data or {}).get("ai") if isinstance(g.extra_data, dict) else None) or None,
        "places": _places_for(item),
        "needs_place": not bool(loc),
        "ai_ready": _ai_ready(item),
    }


def apply_grocery_stock(g: GroceryItem, item: Item, action: str, amount, user_id):
    prev = clamp_qty(g.quantity)
    was_needed = bool(g.needs_restock)
    amt = clamp_qty(amount, "1")
    if amt <= 0:
        amt = Decimal("1")
    thresh = clamp_qty(g.restock_threshold, "1")
    if action == "set":
        qty = set_quantity(g, amt)
        g.last_restocked_at = datetime.utcnow()
        g.needs_restock = qty <= thresh
    elif action == "restock":
        qty = set_quantity(g, prev + amt)
        g.last_restocked_at = datetime.utcnow()
        g.needs_restock = qty <= thresh
    else:
        qty = set_quantity(g, prev - amt)
        if prev > 0:
            g.last_consumed_at = datetime.utcnow()
            g.consume_count = int(g.consume_count or 0) + 1
        g.needs_restock = qty <= thresh or was_needed or qty <= 0
    on_list = _sync_grocery_list(g, item, user_id)
    try:
        from app.utils.activity import log_grocery

        log_grocery(item, g, action, prev, qty, amt, user_id=user_id)
    except Exception:
        pass
    return grocery_payload(g, item, action=action, on_list=on_list, amount=amt, prev_qty=prev)


def flag_need_more(g: GroceryItem, item: Item, user_id):
    set_quantity(g, g.quantity)
    g.needs_restock = True
    prev = clamp_qty(g.quantity)
    on_list = _sync_grocery_list(g, item, user_id)
    action = "want" if stock_status(g) == STATUS_WANT else "need_more"
    try:
        from app.utils.activity import log_grocery

        log_grocery(item, g, action, prev, prev, 0, user_id=user_id)
    except Exception:
        pass
    return grocery_payload(g, item, action=action, on_list=on_list)


def _lookup_name(code: str) -> tuple[str, dict]:
    from app.utils.barcode_lookup import lookup_upc

    lookup = lookup_upc(code) or {}
    name = (lookup.get("name") or "").strip()
    brand = (lookup.get("brand") or "").strip()
    if name and brand and brand.lower() not in name.lower():
        name = f"{brand} {name}"
    elif not name and brand:
        name = brand
    if not name:
        tail = code[-8:] if len(code) >= 8 else code
        name = f"Scanned {tail}"
    return name[:200], lookup


def _classify_payload(household_id: int, lookup: dict, name: str) -> dict:
    from app.builddb.table_households import Household
    from app.utils.classify import classify, household_anchors

    household = Household.query.get(household_id)
    guess = classify(lookup, household=household, extra=name, use_ai=True)
    anchors = household_anchors(household_id)
    attach = guess.get("attach_to")
    return {
        "kind": guess.get("kind"),
        "kind_label": guess.get("kind_label"),
        "suggested_type": guess.get("item_type") or "grocery",
        "attach_to": attach,
        "location_hint": guess.get("location_hint"),
        "questions": guess.get("questions") or [],
        "confidence": guess.get("confidence"),
        "classify_source": guess.get("source"),
        "vehicles": anchors["vehicles"] if attach == "vehicle" else [],
        "tools": anchors["tools"] if attach == "tool" else [],
        "message": guess.get("message") or f"{name} isn't in the house yet.",
        "image_url": (lookup.get("image_url") or "").strip() or None,
        "brand": (lookup.get("brand") or "").strip() or None,
        "facts": lookup.get("facts") or {},
    }


def ensure_wanted_item(household_id: int, user_id: int, barcode: str):
    """Create a catalog row for something we don't have yet (qty 0, never stocked)."""
    existing = find_item(household_id, barcode)
    if existing:
        g = GroceryItem.query.filter_by(household_id=household_id, item_id=existing.id).first()
        if g is None and existing.item_type == "grocery":
            g = GroceryItem(item_id=existing.id, household_id=household_id, quantity=0)
            db.session.add(g)
            db.session.flush()
            set_quantity(g, 0)
            g.needs_restock = True
        return existing, g, False
    name, lookup = _lookup_name(barcode)
    item = None
    g = None
    try:
        with db.session.begin_nested():
            item = Item(
                household_id=household_id,
                name=name,
                item_type="grocery",
                category=(lookup.get("category") or "").strip() or None,
                barcode=barcode,
                created_by=user_id,
            )
            db.session.add(item)
            db.session.flush()
            g = GroceryItem(
                item_id=item.id,
                household_id=household_id,
                quantity=0,
                restock_threshold=1,
                is_in_stock=False,
                needs_restock=True,
                brand=(lookup.get("brand") or "").strip() or None,
                size=(lookup.get("size") or lookup.get("quantity") or "").strip() or None,
                unit="each",
            )
            db.session.add(g)
            db.session.flush()
            try:
                from app.utils.barcode_lookup import apply_product_lookup

                apply_product_lookup(g, item, lookup)
            except Exception:
                pass
    except IntegrityError:
        existing = find_item(household_id, barcode)
        if existing:
            g = GroceryItem.query.filter_by(household_id=household_id, item_id=existing.id).first()
            return existing, g, False
        raise
    try:
        from app.builddb.table_households import Household
        from app.utils.classify import place_new_grocery

        place_new_grocery(item, g, lookup, Household.query.get(household_id))
    except Exception:
        pass
    return item, g, True


def consumption_hint(g: GroceryItem) -> str | None:
    extra = g.extra_data or {}
    if not g.last_consumed_at or not g.consume_count:
        return None
    first = extra.get("first_consumed_at")
    try:
        if first:
            start = datetime.fromisoformat(str(first).replace("Z", ""))
        else:
            start = g.last_consumed_at
        days = max((datetime.utcnow() - start).total_seconds() / 86400.0, 1.0 / 24)
        rate = max(days / max(int(g.consume_count), 1), 1.0 / 24)
        qty = float(clamp_qty(g.quantity))
        every = max(int(round(rate)), 1)
        if qty <= 0:
            return f"You typically use this every {every} days."
        left = max(int(round(rate * qty)), 1)
        return f"Usually lasts about {every} days each. Roughly {left} days left."
    except Exception:
        return None


def _normalize_action(action: str) -> str:
    action = (action or "check").strip().lower().replace(" ", "_")
    return _ACTION_ALIASES.get(action, action)


def process_scan(household_id: int, user_id: int, barcode: str, action: str, amount=1, location=None, skip_place=False):
    code = (barcode or "").strip()
    action = _normalize_action(action)
    item = find_item(household_id, code)
    if action == "check":
        recent = (
            ScanEvent.query.filter_by(
                household_id=household_id, user_id=user_id, barcode=code, action="check"
            )
            .order_by(ScanEvent.id.desc())
            .first()
        )
        if recent and recent.created_at and (datetime.utcnow() - recent.created_at).total_seconds() < 12:
            if item and item.item_type == "grocery":
                g = GroceryItem.query.filter_by(household_id=household_id, item_id=item.id).first()
                if g:
                    payload = grocery_payload(g, item, action="check")
                    payload["found"] = True
                    payload["create"] = False
                    return payload
    event = ScanEvent(
        household_id=household_id,
        user_id=user_id,
        barcode=code,
        action=action,
        amount=clamp_qty(amount, "1"),
        item_id=item.id if item else None,
    )
    db.session.add(event)

    if item is None:
        item, g, created = ensure_wanted_item(household_id, user_id, code)
        event.item_id = item.id
        payload = {
            "found": True,
            "barcode": code,
            "item_id": item.id,
            "item_type": item.item_type,
            "name": item.name,
            "create": False,
            "looked_up": created,
        }
        if g is None:
            stock = {"message": f"{item.name} is in the house.", "status": STATUS_OK}
        elif action == "restock":
            stock = apply_grocery_stock(g, item, "restock", amount, user_id)
        elif action in ("consume", "just_used"):
            stock = apply_grocery_stock(g, item, "consume", amount, user_id)
        elif action == "set":
            stock = apply_grocery_stock(g, item, "set", amount, user_id)
        elif action == "into":
            stock = apply_grocery_stock(g, item, "restock", amount, user_id)
            loc = (g.default_location or "").strip()
            qlab = stock.get("quantity_label") or stock.get("quantity")
            stock["message"] = (
                f"{item.name} is in the house"
                + (f" · {loc}" if loc else "")
                + f". {qlab} on hand."
            )
        elif action in ("need_more", "want"):
            stock = flag_need_more(g, item, user_id)
        else:
            stock = grocery_payload(g, item, action="check")
            looked = created and not (item.name or "").startswith("Scanned ")
            stock["message"] = (
                f"{item.name}."
                + (" That's the barcode lookup." if looked else " New here — rename it if the name is wrong.")
                + " Tap Got more if it's on the shelf."
            )
        if g is not None:
            payload.update(apply_place(g, item, location=location, skip_place=skip_place))
        payload.update(stock)
        payload["hint"] = consumption_hint(g) if g is not None else None
        event.action = action if action in ("restock", "consume", "need_more", "want", "set", "into") else "check"
        event.result_json = {
            "name": item.name,
            "type": item.item_type,
            "status": payload.get("status"),
            "quantity": payload.get("quantity"),
        }
        db.session.commit()
        payload["action"] = event.action
        return payload

    payload = {
        "found": True,
        "barcode": code,
        "item_id": item.id,
        "item_type": item.item_type,
        "name": item.name,
        "create": False,
    }

    if item.item_type == "grocery":
        g = (
            GroceryItem.query.filter_by(household_id=household_id, item_id=item.id)
            .with_for_update()
            .first()
        )
        if g is None:
            g = GroceryItem(item_id=item.id, household_id=household_id, quantity=0)
            db.session.add(g)
            db.session.flush()
        set_quantity(g, g.quantity)
        extra_g = g.extra_data if isinstance(g.extra_data, dict) else {}
        if item.barcode and not extra_g.get("product"):
            try:
                from app.utils.barcode_lookup import lookup_product, apply_product_lookup

                apply_product_lookup(g, item, lookup_product(item.barcode))
            except Exception:
                pass
        if action in ("consume", "restock", "set", "into"):
            extra = dict(g.extra_data or {})
            if action == "consume" and not extra.get("first_consumed_at") and clamp_qty(g.quantity) > 0:
                extra["first_consumed_at"] = datetime.utcnow().isoformat()
                g.extra_data = extra
            stock_action = "restock" if action == "into" else action
            stock = apply_grocery_stock(g, item, stock_action, amount, user_id)
            if action == "into":
                loc = (g.default_location or "").strip()
                qlab = stock.get("quantity_label") or stock.get("quantity")
                stock["message"] = (
                    f"{item.name} is in the house"
                    + (f" · {loc}" if loc else "")
                    + f". {qlab} on hand."
                )
            payload.update(stock)
            payload.update(apply_place(g, item, location=location, skip_place=skip_place))
            payload["hint"] = consumption_hint(g)
        elif action in ("need_more", "want"):
            stock = flag_need_more(g, item, user_id)
            payload.update(stock)
            payload["hint"] = consumption_hint(g)
            action = stock.get("action") or action
        else:
            action = "check"
            if clamp_qty(g.quantity) <= 0:
                g.needs_restock = True
            on_list = _sync_grocery_list(g, item, user_id)
            payload.update(grocery_payload(g, item, action="check", on_list=on_list))
            payload["hint"] = consumption_hint(g)
    else:
        payload["message"] = f"Opened {item.name}."
        payload["status"] = "ok"
        payload["headline"] = item.item_type
        if item.item_type == "tool":
            t = Tool.query.filter_by(household_id=household_id, item_id=item.id).first()
            if t:
                payload["oil_type"] = t.oil_type
                payload["fuel_type"] = t.fuel_type
                payload["hours_used"] = float(t.hours_used) if t.hours_used is not None else None
                payload["last_maintenance_at"] = (
                    t.last_maintenance_at.isoformat() if t.last_maintenance_at else None
                )
                if action == "hours":
                    try:
                        hours = float(str(amount).replace(",", "").strip())
                    except Exception:
                        hours = None
                    if hours is not None:
                        t.hours_used = hours
                        payload["hours_used"] = hours
                        payload["message"] = f"{item.name} is at {hours:g} hours."
                        action = "hours"
        if item.item_type == "vehicle":
            v = Vehicle.query.filter_by(household_id=household_id, item_id=item.id).first()
            if v:
                payload["oil_type"] = v.oil_type
                payload["current_mileage"] = v.current_mileage
                if action == "mileage":
                    try:
                        miles = int(str(amount).replace(",", "").strip())
                    except Exception:
                        miles = None
                    if miles is not None:
                        v.current_mileage = miles
                        payload["current_mileage"] = miles
                        payload["message"] = f"{item.name} is at {miles:,} miles."
                        action = "mileage"
        if item.item_type in ("vehicle", "tool", "house"):
            payload["stay"] = True

    event.item_id = item.id
    event.action = action
    event.result_json = {
        "name": item.name,
        "type": item.item_type,
        "status": payload.get("status"),
        "quantity": payload.get("quantity"),
    }
    db.session.commit()
    payload["action"] = action
    return payload
