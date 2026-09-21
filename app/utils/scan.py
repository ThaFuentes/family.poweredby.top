"""Scan is a truth event. Kids scan, then tap Just used / Needs more / Got more."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.builddb.builddb import db
from app.builddb.table_items import Item
from app.builddb.table_grocery_items import GroceryItem
from app.builddb.table_grocery_list import GroceryListEntry
from app.utils.places import rooms_map
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
    "in": "into",
    "out": "consume",
    "buy": "buy",
    "basket": "buy",
    "miles": "mileage",
    "odometer": "mileage",
    "hours": "hours",
    "freeze": "freeze",
    "freezer": "freeze",
    "frozen": "freeze",
    "fridge": "fridge",
    "refrigerator": "fridge",
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
    prev = clamp_qty(g.quantity)
    q = clamp_qty(val)
    g.quantity = q
    g.is_in_stock = q > 0
    if q != prev:
        try:
            from app.utils.lots import align_quantity

            align_quantity(g, prev, q)
        except Exception:
            pass
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
    try:
        from app.utils.vehicle_lookup import looks_like_vin
        from app.builddb.table_vehicles import Vehicle

        if looks_like_vin(code):
            vin = code.replace(" ", "").upper()
            row = Vehicle.query.filter_by(household_id=household_id, vin=vin).first()
            if row:
                return Item.query.filter_by(id=row.item_id, household_id=household_id).first()
    except Exception:
        pass
    return None


def _open_list_row(g: GroceryItem, item: Item):
    return GroceryListEntry.query.filter_by(
        household_id=g.household_id, item_id=item.id, status="open"
    ).first()


def put_on_list(g: GroceryItem, item: Item, user_id, reason="buy", amount=None) -> bool:
    open_row = _open_list_row(g, item)
    need = clamp_qty(amount) if amount not in (None, "") else None
    if need is None or need <= 0:
        need = max(clamp_qty(g.restock_threshold, "1"), Decimal("1"))
    if open_row:
        open_row.added_reason = reason
        open_row.name = item.name
        open_row.quantity_needed = need
        return True
    db.session.add(
        GroceryListEntry(
            household_id=g.household_id,
            item_id=item.id,
            name=item.name,
            quantity_needed=need,
            status="open",
            added_reason=reason,
            created_by=user_id,
        )
    )
    return True


def _sync_grocery_list(g: GroceryItem, item: Item, user_id) -> bool:
    """Basket stays a shopping list. Auto-add only when this item is opted in."""
    open_row = _open_list_row(g, item)
    status = stock_status(g)
    needs = bool(g.needs_restock) or status != STATUS_OK
    auto = bool(getattr(g, "auto_basket", False))
    if auto and needs:
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
    if open_row and not needs:
        open_row.status = "done"
        open_row.completed_at = datetime.utcnow()
        return False
    return bool(open_row)


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
            message = f"{item.name} — tap how many to put in."
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
        "ask_list": False,
        "auto_basket": bool(getattr(g, "auto_basket", False)),
        "ask_frozen": bool(isinstance(g.extra_data, dict) and g.extra_data.get("ask_frozen")),
        "usual_into": usual_amount(g, "into"),
        "usual_out": usual_amount(g, "out"),
        "qty_choices_in": qty_choices(g, "into"),
        "qty_choices_out": qty_choices(g, "out"),
        "qty_choices": qty_choices(g, "into" if action in ("into", "restock", "check", "buy") else "out"),
        "rooms": {k: float(v) for k, v in rooms_map(g).items()},
        **_lots_payload(g, item),
    }


def _lots_payload(g: GroceryItem, item: Item | None = None) -> dict:
    try:
        from app.utils.lots import payload as lots_payload

        data = lots_payload(g)
        data["item_id"] = getattr(item, "id", None)
        return data
    except Exception:
        return {}


def _usual_key(action: str) -> str:
    if action in ("into", "restock"):
        return "into"
    if action == "consume":
        return "out"
    return action or "into"


def remember_usual(g: GroceryItem, action: str, amount) -> None:
    """Remember pack sizes (30-count chips). Ignore 1 so inventory +/- does not wipe them."""
    try:
        amt = int(clamp_qty(amount))
    except Exception:
        return
    if amt < 2:
        return
    extra = dict(g.extra_data or {}) if isinstance(g.extra_data, dict) else {}
    usual = dict(extra.get("usual") or {})
    key = _usual_key(action)
    hist = []
    for x in usual.get(f"{key}_hist") or []:
        try:
            n = int(x)
        except (TypeError, ValueError):
            continue
        if n >= 2:
            hist.append(n)
    hist.append(amt)
    hist = hist[-12:]
    counts: dict[int, int] = {}
    for n in hist:
        counts[n] = counts.get(n, 0) + 1
    best = hist[-1]
    best_n = 0
    for n, c in counts.items():
        if c > best_n or (c == best_n and n == hist[-1]):
            best, best_n = n, c
    usual[f"{key}_hist"] = hist
    usual[key] = best
    extra["usual"] = usual
    g.extra_data = extra


def usual_amount(g: GroceryItem | None, action: str) -> int | None:
    if g is None:
        return None
    extra = g.extra_data if isinstance(g.extra_data, dict) else {}
    usual = extra.get("usual") or {}
    try:
        n = int(usual.get(_usual_key(action)) or 0)
    except (TypeError, ValueError):
        n = 0
    return n if n >= 2 else None


def qty_choices(g: GroceryItem | None, action: str = "into") -> list[int]:
    usual = usual_amount(g, action)
    out: list[int] = []
    if usual:
        out.append(usual)
    for d in (1, 5, 10):
        if d not in out:
            out.append(d)
    return out


def apply_grocery_stock(
    g: GroceryItem, item: Item, action: str, amount, user_id, *, sync_list=True, remember=True, place=None
):
    from app.utils.places import bump_room, rooms_map, take_from_rooms

    prev = clamp_qty(g.quantity)
    was_needed = bool(g.needs_restock)
    amt = clamp_qty(amount, "1")
    if amt <= 0:
        amt = Decimal("1")
    thresh = clamp_qty(g.restock_threshold, "1")
    loc = (place or "").strip()
    if action == "set":
        qty = set_quantity(g, amt)
        g.last_restocked_at = datetime.utcnow()
        g.needs_restock = qty <= thresh
    elif action == "restock":
        if loc or rooms_map(g):
            bump_room(g, loc or g.default_location or "No room yet", amt)
            qty = clamp_qty(g.quantity)
        else:
            qty = set_quantity(g, prev + amt)
        g.last_restocked_at = datetime.utcnow()
        g.needs_restock = qty <= thresh
        if remember:
            remember_usual(g, "into", amt)
        try:
            from app.utils.shelf_life import apply_shelf_life

            extra = g.extra_data if isinstance(g.extra_data, dict) else {}
            if not extra.get("expires_on") or extra.get("expires_guessed"):
                apply_shelf_life(item, g, force=bool(extra.get("expires_guessed")))
        except Exception:
            pass
    else:
        if loc:
            bump_room(g, loc, -amt)
            qty = clamp_qty(g.quantity)
        elif rooms_map(g):
            take_from_rooms(g, amt)
            qty = clamp_qty(g.quantity)
        else:
            qty = set_quantity(g, max(Decimal("0"), prev - amt))
        if prev > 0:
            g.last_consumed_at = datetime.utcnow()
            g.consume_count = int(g.consume_count or 0) + 1
        g.needs_restock = qty <= thresh or was_needed or qty <= 0
        if remember:
            remember_usual(g, "out", amt)
    on_list = _sync_grocery_list(g, item, user_id) if sync_list else bool(_open_list_row(g, item))
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
    action = "want" if stock_status(g) == STATUS_WANT else "need_more"
    put_on_list(g, item, user_id, action)
    try:
        from app.utils.activity import log_grocery

        log_grocery(item, g, action, prev, prev, 0, user_id=user_id)
    except Exception:
        pass
    return grocery_payload(g, item, action=action, on_list=True)


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
        name = f"Needs a name · {tail}"
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
            try:
                from app.utils.shelf_life import apply_shelf_life

                apply_shelf_life(item, g)
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


def fill_placeholder_names(items, *, limit=3, force=False) -> int:
    """Retry barcode lookup for rows still named Scanned / Needs a name."""
    from app.utils.barcode_lookup import lookup_product, apply_product_lookup, is_placeholder_name

    filled = 0
    tried = 0
    for item in items or []:
        if tried >= limit:
            break
        if not is_placeholder_name(getattr(item, "name", None)):
            continue
        code = (getattr(item, "barcode", None) or "").strip()
        if len(code) < 8:
            continue
        g = getattr(item, "grocery", None)
        if g is None:
            continue
        extra = g.extra_data if isinstance(g.extra_data, dict) else {}
        if not force:
            tried_at = extra.get("lookup_tried_at")
            if tried_at:
                try:
                    t = datetime.fromisoformat(str(tried_at).replace("Z", ""))
                    if (datetime.utcnow() - t).total_seconds() < 6 * 3600:
                        continue
                except Exception:
                    pass
        tried += 1
        lookup = lookup_product(code, force=True)
        extra = dict(extra)
        extra["lookup_tried_at"] = datetime.utcnow().isoformat()
        g.extra_data = extra
        if lookup.get("ok") and (lookup.get("name") or lookup.get("brand")):
            apply_product_lookup(g, item, lookup)
            filled += 1
    return filled


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


def _resolve_host(household_id: int, host_item_id):
    if not host_item_id:
        return None
    try:
        hid = int(host_item_id)
    except (TypeError, ValueError):
        return None
    item = (
        Item.query.filter_by(id=hid, household_id=household_id)
        .filter(Item.removed_at.is_(None))
        .first()
    )
    if item and item.item_type in ("vehicle", "tool", "house"):
        return item
    return None


def _vin_result(item, v, decoded, diffs, *, created=False, asked=False) -> dict:
    name = item.name if item else (decoded.get("name") or "Vehicle")
    msg = f"Added {name} from the VIN sticker."
    if asked and diffs:
        msg = f"NHTSA has different info for {name}. Here's what would change."
    elif asked:
        msg = f"{name} already matches the sticker."
    elif not created:
        msg = f"{name} is already in the house."
    return {
        "found": True,
        "create": False,
        "created": created,
        "barcode": (decoded or {}).get("vin") or (v.vin if v else ""),
        "item_id": item.id if item else None,
        "item_type": "vehicle",
        "name": name,
        "vin": (decoded or {}).get("vin") or (v.vin if v else ""),
        "ask_update": bool(asked and diffs),
        "diffs": diffs or [],
        "facts": (decoded or {}).get("facts") or {},
        "message": msg,
    }


def ingest_vin(
    household_id: int,
    user_id: int,
    vin: str,
    *,
    host_item=None,
    apply: bool = False,
    fields=None,
    force_new: bool = False,
) -> dict:
    """Door-sticker VIN. Open vehicle gets it. Add-vehicle creates a new one."""
    from app.builddb.table_items import Item
    from app.builddb.table_vehicles import Vehicle
    from app.utils.vehicle_lookup import (
        lookup_vehicle,
        apply_vehicle_lookup,
        looks_like_vin,
        extract_vin,
        diff_vehicle,
    )
    from app.utils.qr_labels import item_payload

    code = extract_vin(vin) or (vin or "").replace(" ", "").upper()
    if not looks_like_vin(code):
        return {"found": False, "create": False, "error": "Not a VIN."}
    decoded = lookup_vehicle(vin=code)
    target = None
    if not force_new and host_item is not None and host_item.item_type == "vehicle":
        target = host_item
    row = Vehicle.query.filter_by(household_id=household_id, vin=code).first()
    if target is None and row:
        target = Item.query.get(row.item_id)
    if target is None and not force_new:
        blanks = (
            Vehicle.query.filter_by(household_id=household_id)
            .filter((Vehicle.vin.is_(None)) | (Vehicle.vin == ""))
            .all()
        )
        live = []
        for vrow in blanks:
            it = Item.query.filter_by(id=vrow.item_id, household_id=household_id).filter(Item.removed_at.is_(None)).first()
            if it is not None:
                live.append(it)
        if len(live) == 1:
            target = live[0]

    if target is not None and target.item_type == "vehicle":
        v = target.vehicle or Vehicle.query.filter_by(item_id=target.id, household_id=household_id).first()
        if v is None:
            v = Vehicle(item_id=target.id, household_id=household_id, vin=code)
            db.session.add(v)
            db.session.flush()
        diffs = diff_vehicle(v, target, decoded)
        our_vin = (v.vin or "").replace(" ", "").upper()
        same_or_empty = (not our_vin) or our_vin == code
        if apply or (same_or_empty and not force_new):
            apply_vehicle_lookup(v, target, decoded, fields=fields, overwrite=bool(apply))
            v.vin = code
            filled = [d for d in diffs if d.get("kind") == "fill" or apply]
            msg = f"Posted the VIN to {target.name}."
            if filled and not apply:
                bits = ", ".join(d["label"] for d in filled[:6])
                msg = f"Posted the VIN to {target.name}. Filled {bits}."
            elif apply:
                msg = f"Updated {target.name} from the VIN sticker."
            return _vin_result(target, v, decoded, [], created=False, asked=False) | {
                "message": msg,
                "ask_update": False,
            }
        if diffs:
            return _vin_result(target, v, decoded, diffs, asked=True)
        return _vin_result(target, v, decoded, [], asked=True)

    name = decoded.get("name") or f"VIN {code[:8]}"
    item = Item(
        household_id=household_id,
        name=str(name)[:200],
        item_type="vehicle",
        created_by=user_id,
    )
    db.session.add(item)
    db.session.flush()
    item.barcode = item_payload(household_id, item.id)
    v = Vehicle(item_id=item.id, household_id=household_id, vin=code)
    db.session.add(v)
    apply_vehicle_lookup(v, item, decoded)
    v.vin = code
    return _vin_result(item, v, decoded, [], created=True)


def _host_wants_scan(host, item, g) -> bool:
    """Any UPC on an open vehicle/tool/house belongs to that host. Undo if it was a miss."""
    if host is None or item is None:
        return False
    if item.id == host.id:
        return False
    return host.item_type in ("vehicle", "tool", "house")


def _install_prompt(item, g, host) -> dict:
    from app.utils.vehicle_systems import guess_slot, system_label, slot_label

    extra = g.extra_data if g is not None and isinstance(g.extra_data, dict) else {}
    kind = extra.get("kind") or item.category or ""
    system, slot = guess_slot(kind, name=item.name or "", category=item.category or "")
    house_slots = None
    sys_lab = None
    if host.item_type == "house":
        from app.utils.house_systems import HOUSE_SLOTS, guess_house_slot, house_system_label

        house_slots = HOUSE_SLOTS
        system, slot = guess_house_slot(item.name or "", kind)
        sys_lab = house_system_label(system)
    payload = grocery_payload(g, item, action="check") if g is not None else {
        "message": f"{item.name} — add to {host.name}?",
        "name": item.name,
        "image_url": None,
    }
    payload.update(
        {
            "found": True,
            "create": False,
            "barcode": item.barcode,
            "item_id": item.id,
            "item_type": item.item_type,
            "name": item.name,
            "ask_install": True,
            "host": {"id": host.id, "name": host.name, "item_type": host.item_type},
            "kind": kind,
            "system": system,
            "slot": slot,
            "system_label": sys_lab or system_label(system),
            "slot_label": slot_label(system, slot, house_slots),
            "message": f"{item.name} — did you install it on {host.name}?",
        }
    )
    return payload


def _do_host_attach(household_id, user_id, item, g, host, *, installed: bool) -> dict:
    linked_was = item.linked_item_id
    item.linked_item_id = host.id
    part_row = None
    extra = g.extra_data if g is not None and isinstance(g.extra_data, dict) else {}
    if host.item_type in ("vehicle", "house", "tool"):
        try:
            from app.utils.vehicle_systems import attach_scanned_part

            part_row = attach_scanned_part(
                hid=household_id,
                user_id=user_id,
                vehicle_item_id=host.id,
                catalog_item=item,
                kind=extra.get("kind"),
                name=item.name,
                brand=(g.brand if g is not None else None),
                status="installed" if installed else "spare",
            )
        except Exception:
            part_row = None
        if installed and g is not None and clamp_qty(g.quantity) > 0:
            apply_grocery_stock(g, item, "consume", 1, user_id, sync_list=False)
    undo_id = None
    try:
        from app.utils.activity import record

        kind = "vehicle" if host.item_type == "vehicle" else "equipment"
        act = record(
            action="scan.host_attach",
            summary=f"{item.name} on {host.name}",
            target_table="vehicle_parts" if part_row is not None else "items",
            target_id=part_row.id if part_row is not None else item.id,
            item_id=item.id,
            old_json={"linked_item_id": linked_was},
            new_json={
                "linked_item_id": host.id,
                "part_id": part_row.id if part_row is not None else None,
                "host_id": host.id,
                "consumed": bool(installed),
            },
            user_id=user_id,
        )
        undo_id = act.id if act is not None else None
    except Exception:
        undo_id = None
    payload = grocery_payload(g, item, action="check") if g is not None else {"name": item.name}
    kind_word = "vehicle" if host.item_type == "vehicle" else "equipment"
    payload.update(
        {
            "found": True,
            "create": False,
            "barcode": item.barcode,
            "item_id": item.id,
            "item_type": item.item_type,
            "name": item.name,
            "ask_install": False,
            "attached": True,
            "ask_installed": not installed,
            "undo_id": undo_id,
            "host": {"id": host.id, "name": host.name, "item_type": host.item_type},
            "message": (
                f"Installed {item.name} on {host.name}."
                if installed
                else f"{item.name} is on {host.name} ({kind_word})."
            ),
        }
    )
    return payload


def process_scan(
    household_id: int,
    user_id: int,
    barcode: str,
    action: str,
    amount=1,
    location=None,
    skip_place=False,
    host_item_id=None,
    fields=None,
    skip_host=False,
    force_new=False,
):
    code = (barcode or "").strip()
    action = _normalize_action(action)
    host = None if skip_host or force_new else _resolve_host(household_id, host_item_id)
    # Camera is a UPC scanner. VIN decode is typed on the vehicle form, not here.
    vin_scan = False
    vin_code = code
    if action == "apply_vin":
        try:
            from app.utils.vehicle_lookup import looks_like_vin, extract_vin

            vin_scan = looks_like_vin(code)
            vin_code = extract_vin(code) or code
        except Exception:
            vin_scan = False
            vin_code = code
    if vin_scan:
        payload = ingest_vin(
            household_id,
            user_id,
            vin_code,
            host_item=host if host and host.item_type == "vehicle" else None,
            apply=True,
            fields=fields,
            force_new=bool(force_new),
        )
        event = ScanEvent(
            household_id=household_id,
            user_id=user_id,
            barcode=code,
            action="apply_vin" if action == "apply_vin" else "check",
            amount=clamp_qty(amount, "1"),
            item_id=payload.get("item_id"),
        )
        db.session.add(event)
        event.result_json = {"name": payload.get("name"), "type": "vehicle"}
        db.session.commit()
        payload["action"] = event.action
        return payload
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
            if item and item.item_type == "grocery" and host is None:
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

    if action in ("install", "stash"):
        g = None
        if item is None:
            item, g, _created = ensure_wanted_item(household_id, user_id, code)
        elif item.item_type == "grocery":
            g = GroceryItem.query.filter_by(household_id=household_id, item_id=item.id).first()
        event.item_id = item.id if item else None
        if host is None or item is None:
            payload = {
                "found": bool(item),
                "error": "Scan this from the vehicle or tool page.",
                "message": "Open the vehicle or tool first, then scan the part.",
            }
        else:
            payload = _do_host_attach(
                household_id, user_id, item, g, host, installed=action == "install"
            )
        event.result_json = {"name": payload.get("name"), "type": payload.get("item_type")}
        db.session.commit()
        payload["action"] = action
        return payload

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
            stock = apply_grocery_stock(g, item, "consume", amount, user_id, sync_list=False)
            if clamp_qty(g.quantity) <= 0:
                stock["ask_list"] = not bool(_open_list_row(g, item))
                stock["message"] = f"{item.name} is at 0." + (
                    " Add to the list?" if stock["ask_list"] else " Already on the list."
                )
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
        elif action == "buy":
            put_on_list(g, item, user_id, "buy", amount)
            stock = grocery_payload(g, item, action="buy", on_list=True)
            stock["message"] = f"{item.name} on the basket."
        elif action in ("freeze", "fridge"):
            from app.utils.shelf_life import set_meat_storage

            exp = set_meat_storage(item, g, frozen=action == "freeze")
            stock = grocery_payload(g, item, action=action, on_list=bool(_open_list_row(g, item)))
            where = "the freezer" if action == "freeze" else "the fridge"
            stock["message"] = f"{item.name} in {where}." + (f" Use by {exp}." if exp else "")
        elif action in ("need_more", "want"):
            stock = flag_need_more(g, item, user_id)
        else:
            stock = grocery_payload(g, item, action="check")
            from app.utils.barcode_lookup import is_placeholder_name as _ph

            looked = created and not _ph(item.name)
            stock["message"] = (
                f"{item.name}."
                + (" That's the barcode lookup." if looked else " New here — rename it if the name is wrong.")
                + " Tap Got more if it's on the shelf."
            )
        if g is not None and action == "into":
            payload.update(apply_place(g, item, location=location, skip_place=skip_place))
        payload.update(stock)
        payload["hint"] = consumption_hint(g) if g is not None else None
        if host and action in ("check", "into", "restock") and _host_wants_scan(host, item, g):
            payload = _do_host_attach(household_id, user_id, item, g, host, installed=False)
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
        from app.utils.barcode_lookup import is_placeholder_name as _ph

        if item.barcode and (
            _ph(item.name) or not extra_g.get("product") or not (g.image_url or "").strip()
        ):
            try:
                from app.utils.barcode_lookup import lookup_product, apply_product_lookup

                apply_product_lookup(g, item, lookup_product(item.barcode, force=_ph(item.name)))
            except Exception:
                pass
        if action == "buy":
            put_on_list(g, item, user_id, "buy", amount)
            stock = grocery_payload(g, item, action="buy", on_list=True)
            stock["message"] = f"{item.name} on the basket."
            payload.update(stock)
            payload["hint"] = consumption_hint(g)
        elif action in ("consume", "restock", "set", "into"):
            extra = dict(g.extra_data or {})
            if action == "consume" and not extra.get("first_consumed_at") and clamp_qty(g.quantity) > 0:
                extra["first_consumed_at"] = datetime.utcnow().isoformat()
                g.extra_data = extra
            stock_action = "restock" if action == "into" else action
            sync = action != "consume"
            stock = apply_grocery_stock(g, item, stock_action, amount, user_id, sync_list=sync)
            if action == "into":
                loc = (g.default_location or "").strip()
                qlab = stock.get("quantity_label") or stock.get("quantity")
                stock["message"] = (
                    f"{item.name} is in the house"
                    + (f" · {loc}" if loc else "")
                    + f". {qlab} on hand."
                )
            if action == "consume":
                left = clamp_qty(g.quantity)
                if left <= 0:
                    stock["quantity"] = 0
                    stock["ask_list"] = not bool(_open_list_row(g, item))
                    stock["message"] = f"{item.name} is at 0." + (
                        " Add to the list?" if stock["ask_list"] else " Already on the list."
                    )
            payload.update(stock)
            if action == "into":
                payload.update(apply_place(g, item, location=location, skip_place=skip_place))
            payload["hint"] = consumption_hint(g)
        elif action in ("freeze", "fridge"):
            from app.utils.shelf_life import set_meat_storage

            exp = set_meat_storage(item, g, frozen=action == "freeze")
            stock = grocery_payload(g, item, action=action, on_list=bool(_open_list_row(g, item)))
            where = "the freezer" if action == "freeze" else "the fridge"
            stock["message"] = f"{item.name} in {where}." + (f" Use by {exp}." if exp else "")
            payload.update(stock)
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

    if item.item_type == "grocery" and host and action in ("check", "into", "restock"):
        if _host_wants_scan(host, item, g):
            payload = _do_host_attach(household_id, user_id, item, g, host, installed=False)

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
