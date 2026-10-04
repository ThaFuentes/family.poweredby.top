"""Reminders (Due page) shared by the page and Maya's API."""
from __future__ import annotations

from datetime import datetime

from app.builddb.builddb import db


def parse_due(raw):
    if isinstance(raw, datetime):
        return raw
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", ""))
    except ValueError:
        return None


def clean_type(raw):
    from app.utils.reminders_copy import REMINDER_TYPES

    rtype = (str(raw or "custom")).strip()
    return rtype if rtype in {k for k, _ in REMINDER_TYPES} else "custom"


def clean_via(raw):
    from app.utils.calendar import NOTIFY_CHOICES

    via = (str(raw or "")).strip().lower()
    return via if via in NOTIFY_CHOICES else None


def linked_id(raw):
    from app.builddb.table_items import Item
    from app.utils.household import scoped

    text = str(raw if raw is not None else "").strip()
    if not text.isdigit():
        return None
    item = scoped(Item).filter_by(id=int(text)).first()
    return item.id if item else None


def create_reminder(*, hid: int, user_id: int, title, rtype="custom", due_at=None,
                    linked_item_id=None, recurrence=None, notify_via=None, notes=None, announce=True):
    """Save and announce (email/calendar) exactly like the Due page."""
    from app.builddb.table_reminders import Reminder
    from app.utils.reminders_copy import parse_recurrence

    title = (title or "").strip()
    if not title:
        return None, "Title required."
    row = Reminder(
        household_id=hid,
        title=title[:200],
        type=clean_type(rtype),
        due_at=parse_due(due_at),
        linked_item_id=linked_id(linked_item_id),
        recurrence=parse_recurrence(recurrence),
        notify_via=clean_via(notify_via),
        notes=(str(notes).strip() or None) if notes else None,
        status="open",
        created_by=user_id,
    )
    db.session.add(row)
    db.session.commit()
    if announce:
        try:
            from app.utils.notify import announce_reminder

            announce_reminder(row)
        except Exception as exc:
            print(f"[reminders] announce failed: {exc}", flush=True)
    return row, None


def update_reminder(row, data) -> str | None:
    from app.utils.reminders_copy import parse_recurrence

    if "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            return "Title required."
        row.title = title[:200]
    if "type" in data:
        row.type = clean_type(data.get("type"))
    if "due_at" in data:
        row.due_at = parse_due(data.get("due_at"))
    if "linked_item_id" in data:
        row.linked_item_id = linked_id(data.get("linked_item_id"))
    if "recurrence" in data:
        row.recurrence = parse_recurrence(data.get("recurrence"))
    if "notify_via" in data:
        row.notify_via = clean_via(data.get("notify_via"))
    if "notes" in data:
        row.notes = (str(data.get("notes") or "").strip() or None)
    row.updated_at = datetime.utcnow()
    return None


def complete(row):
    row.status = "done"


def reopen(row):
    row.status = "open"


def remove_reminder(row, *, actor_id, via="ui"):
    from app.builddb.table_reminders import Reminder
    from app.utils import maya_store

    return maya_store.trash(
        hid=row.household_id,
        label=f"Reminder: {row.title}",
        rows=[(Reminder, row)],
        actor_id=actor_id,
        via=via,
    )
