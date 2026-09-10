"""What this household needs right now — home is not a launcher."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_

from app.builddb.table_grocery_items import GroceryItem
from app.builddb.table_items import Item
from app.builddb.table_reminders import Reminder
from app.builddb.table_scan_events import ScanEvent
from app.builddb.table_users import User
from app.utils.scan import stock_status, STATUS_OUT, STATUS_LOW, STATUS_WANT

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


def household_needs(household_id: int, *, is_child: bool = False) -> dict:
    now = _utcnow()
    pantry = GroceryItem.query.filter_by(household_id=household_id)
    had_filter = or_(
        GroceryItem.last_restocked_at.isnot(None),
        GroceryItem.last_consumed_at.isnot(None),
        GroceryItem.consume_count > 0,
    )
    out_n = pantry.filter(GroceryItem.is_in_stock.is_(False), had_filter).count()
    want_n = pantry.filter(
        GroceryItem.is_in_stock.is_(False),
        GroceryItem.last_restocked_at.is_(None),
        GroceryItem.last_consumed_at.is_(None),
        GroceryItem.consume_count == 0,
    ).count()
    low_n = pantry.filter_by(is_in_stock=True, needs_restock=True).count()

    due_rows = (
        Reminder.query.filter_by(household_id=household_id, status="open")
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
    for g in pantry.limit(400).all():
        exp = _expires_on(g)
        if exp is None or exp > horizon:
            continue
        item = Item.query.filter_by(id=g.item_id, household_id=household_id).first()
        if not item:
            continue
        expiring.append({"item": item, "expires_on": exp, "gone": exp < now.date()})

    people = {u.id: u for u in User.query.filter_by(household_id=household_id).all()}
    since = now - timedelta(hours=48)
    events = (
        ScanEvent.query.filter_by(household_id=household_id)
        .filter(ScanEvent.created_at >= since)
        .order_by(ScanEvent.created_at.desc())
        .limit(12)
        .all()
    )
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
        grocery_items = (
            Item.query.filter_by(household_id=household_id, item_type="grocery")
            .order_by(Item.name.asc())
            .all()
        )
        for item in grocery_items:
            g = item.grocery
            if g is None:
                continue
            st = stock_status(g)
            if st == STATUS_OUT:
                out_items.append(item)
            elif st == STATUS_LOW:
                low_items.append(item)
            if len(out_items) + len(low_items) >= 16:
                break

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
