"""What this household needs right now — home is not a launcher."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import joinedload

from app.builddb.builddb import db
from app.builddb.table_grocery_items import GroceryItem
from app.builddb.table_grocery_list import GroceryListEntry
from app.builddb.table_items import Item
from app.builddb.table_legal_records import LegalRecord
from app.builddb.table_notes import Note
from app.builddb.table_reminders import Reminder
from app.builddb.table_scan_events import ScanEvent
from app.builddb.table_users import User
from app.utils.hot_cache import get as cache_get, put as cache_put
from app.utils.scan import STATUS_WANT

ACTION_SAID = {
    "consume": "just used",
    "restock": "got more",
    "need_more": "needs more",
    "want": "wants",
    "check": "scanned",
    "mileage": "logged miles",
    "miles": "logged miles",
    "hours": "logged hours",
}

HOME_TTL = 30


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _expires_on(g: GroceryItem):
    extra = g.extra_data if isinstance(getattr(g, "extra_data", None), dict) else {}
    raw = extra.get("expires_on")
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def activity_line(event: ScanEvent, people: dict[int, User]) -> str:
    who = "Someone"
    uid = event.user_id
    if uid and uid in people:
        u = people[uid]
        who = (u.name or u.username or "Someone").split()[0]
    verb = ACTION_SAID.get((event.action or "").strip().lower(), "scanned")
    name = None
    if isinstance(event.result_json, dict):
        name = (event.result_json.get("name") or "").strip() or None
    if not name and event.barcode:
        name = event.barcode
    name = name or "something"
    return f"{who} {verb} {name}"


def _had_stock() -> object:
    return or_(
        GroceryItem.last_restocked_at.isnot(None),
        GroceryItem.last_consumed_at.isnot(None),
        GroceryItem.consume_count > 0,
    )


def _snap_item(item) -> SimpleNamespace | None:
    if item is None:
        return None
    return SimpleNamespace(
        id=item.id,
        name=item.name,
        item_type=getattr(item, "item_type", None),
    )


def _snapshot_needs(needs: dict) -> dict:
    out = dict(needs)
    out["expiring"] = [
        {
            "item": _snap_item(row.get("item")),
            "expires_on": row.get("expires_on"),
            "gone": row.get("gone"),
        }
        for row in needs.get("expiring") or []
    ]
    out["out_items"] = [_snap_item(i) for i in needs.get("out_items") or []]
    out["low_items"] = [_snap_item(i) for i in needs.get("low_items") or []]
    return out


def household_needs(household_id: int, *, is_child: bool = False) -> dict:
    now = _utcnow()
    hid = int(household_id)
    had_filter = _had_stock()

    stock_row = (
        db.session.query(
            func.coalesce(
                func.sum(
                    case((and_(GroceryItem.is_in_stock.is_(False), had_filter), 1), else_=0)
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            and_(
                                GroceryItem.is_in_stock.is_(False),
                                GroceryItem.last_restocked_at.is_(None),
                                GroceryItem.last_consumed_at.is_(None),
                                GroceryItem.consume_count == 0,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            and_(
                                GroceryItem.is_in_stock.is_(True),
                                GroceryItem.needs_restock.is_(True),
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .filter(GroceryItem.household_id == hid)
        .one()
    )
    out_n, want_n, low_n = (int(stock_row[0] or 0), int(stock_row[1] or 0), int(stock_row[2] or 0))

    due_rows = (
        Reminder.query.filter_by(household_id=hid, status="open")
        .order_by(Reminder.due_at.asc())
        .limit(12)
        .all()
    )
    soon = now + timedelta(days=7)
    due = []
    for row in due_rows:
        when = row.due_at
        overdue = bool(when and when < now)
        upcoming = when is None or when <= soon
        if overdue or upcoming:
            due.append(
                {
                    "id": row.id,
                    "title": row.title or row.type,
                    "due_at": when,
                    "overdue": overdue,
                    "item_id": row.linked_item_id,
                }
            )

    expiring = []
    horizon = (now + timedelta(days=7)).date()
    pantry_rows = (
        GroceryItem.query.options(joinedload(GroceryItem.item))
        .filter_by(household_id=hid)
        .limit(400)
        .all()
    )
    for g in pantry_rows:
        exp = _expires_on(g)
        if exp is None or exp > horizon:
            continue
        item = g.item
        if not item or int(getattr(item, "household_id", 0) or 0) != hid:
            continue
        expiring.append({"item": item, "expires_on": exp, "gone": exp < now.date()})

    since = now - timedelta(hours=48)
    events = (
        ScanEvent.query.filter_by(household_id=hid)
        .filter(ScanEvent.created_at >= since)
        .order_by(ScanEvent.created_at.desc())
        .limit(12)
        .all()
    )
    uids = {e.user_id for e in events if e.user_id}
    people = {}
    if uids:
        people = {
            u.id: u
            for u in User.query.filter(User.household_id == hid, User.id.in_(uids)).all()
        }
    activity = [
        {
            "id": e.id,
            "line": activity_line(e, people),
            "item_id": e.item_id,
            "at": e.created_at,
            "action": e.action,
        }
        for e in events
    ]

    out_items = []
    low_items = []
    if not is_child:
        out_items = (
            Item.query.join(GroceryItem, GroceryItem.item_id == Item.id)
            .filter(
                Item.household_id == hid,
                Item.item_type == "grocery",
                GroceryItem.is_in_stock.is_(False),
                had_filter,
            )
            .order_by(Item.name.asc())
            .limit(8)
            .all()
        )
        low_items = (
            Item.query.join(GroceryItem, GroceryItem.item_id == Item.id)
            .filter(
                Item.household_id == hid,
                Item.item_type == "grocery",
                GroceryItem.is_in_stock.is_(True),
                or_(
                    GroceryItem.needs_restock.is_(True),
                    GroceryItem.quantity <= GroceryItem.restock_threshold,
                ),
            )
            .order_by(Item.name.asc())
            .limit(8)
            .all()
        )

    return {
        "out": out_n,
        "low": low_n,
        "want": want_n,
        "due": due,
        "expiring": expiring[:8],
        "activity": activity,
        "out_items": out_items[:8],
        "low_items": low_items[:8],
        "want_status": STATUS_WANT,
    }


def home_dashboard(household_id: int, *, is_child: bool = False, user_id: int | None = None) -> dict:
    """Counts + needs for Home. Cached briefly; writes bump the household key."""
    hid = int(household_id)
    role = "c" if is_child else "a"
    uid = int(user_id) if user_id else 0
    key = f"home:{hid}:{role}:{uid}"
    hit = cache_get(key)
    if hit is not None:
        return hit

    needs = household_needs(hid, is_child=is_child)
    type_rows = (
        db.session.query(Item.item_type, func.count(Item.id))
        .filter(
            Item.household_id == hid,
            Item.item_type.in_(("grocery", "tool", "vehicle", "house")),
        )
        .group_by(Item.item_type)
        .all()
    )
    type_counts = {k: int(v) for k, v in type_rows}
    grocery_open = (
        GroceryListEntry.query.filter_by(household_id=hid, status="open").count()
    )
    reminders_open = Reminder.query.filter_by(household_id=hid, status="open").count()
    notes_q = Note.query.filter_by(household_id=hid)
    if uid:
        notes_q = notes_q.filter(or_(Note.visibility == "household", Note.user_id == uid))
    notes_open = notes_q.count()
    legal_open = 0
    if not is_child:
        try:
            legal_open = LegalRecord.query.filter_by(household_id=hid, status="open").count()
        except Exception:
            legal_open = 0
    house = (
        Item.query.filter_by(household_id=hid, item_type="house")
        .order_by(Item.id.asc())
        .first()
    )
    payload = {
        "needs": _snapshot_needs(needs),
        "counts": {
            "groceries": type_counts.get("grocery", 0),
            "tools": type_counts.get("tool", 0),
            "vehicles": type_counts.get("vehicle", 0),
            "list": grocery_open,
            "reminders": reminders_open,
            "out": needs["out"],
            "low": needs["low"],
            "want": needs["want"],
            "notes": notes_open,
            "legal": legal_open,
        },
        "house": _snap_item(house),
    }
    cache_put(key, payload, HOME_TTL)
    return payload
