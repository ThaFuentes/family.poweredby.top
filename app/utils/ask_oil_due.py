"""Local oil-maintenance checks and confirmation-backed reminder offers."""
from __future__ import annotations

import re
from datetime import date, datetime

from flask import has_request_context, session

PENDING_KEY = "family_ask_oil_reminder_pending"
OIL_ASK = re.compile(
    r"\b(?:oil|engine oil)\b.{0,50}\b(?:change|changes|service|due|needed|need|should|when)\b"
    r"|\b(?:need|needs|needed|due for|should i|time for)\b.{0,35}\b(?:an?\s+)?oil\s+change\b"
    r"|\bwhen\s+(?:is|should)\b.{0,35}\b(?:the\s+)?(?:engine\s+)?oil\b"
    r"|\bshould\s+(?:i|we)\s+(?:change|replace|service)\b.{0,20}\b(?:the\s+)?(?:engine\s+)?oil\b",
    re.I,
)
_YES = re.compile(
    r"^\s*(?:(?:yes|yeah|yep|yup|ok|okay|sure)(?:\s*,?\s*please)?|"
    r"add(?:\s+it|\s+them)?|do it|go ahead)\s*[.!]?\s*$",
    re.I,
)
_NO = re.compile(r"^\s*(?:no|nope|cancel|never mind|don't|do not)\b", re.I)


def _as_date(raw):
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if raw:
        try:
            return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None
    return None


def _date_label(day: date) -> str:
    return day.strftime("%B %d, %Y").replace(" 0", " ")


def _due_phrase(day: date, today: date) -> str:
    days = (day - today).days
    if days < 0:
        return f"overdue {abs(days)} days"
    if days == 0:
        return "due today"
    return f"due in {days} days"


def oil_schedule(item, today: date | None = None) -> dict:
    """Read saved due targets; derive targets from the last service and interval."""
    today = today or date.today()
    host = getattr(item, "vehicle", None) or getattr(item, "tool", None)
    if host is None:
        return {
            "scheduled": False,
            "has_date": False,
            "due": [],
            "next_date": None,
            "next_miles": None,
            "next_hours": None,
        }
    try:
        from app.utils.fluid_specs import engine_oil_for

        guide = engine_oil_for(item) or {}
    except Exception:
        guide = {}
    next_date = _as_date(getattr(host, "next_oil_due_date", None))
    last_date = _as_date(getattr(host, "last_oil_change_date", None) or getattr(host, "last_oil_date", None))
    months = getattr(host, "oil_interval_months", None) or guide.get("interval_months")
    if next_date is None and last_date and months:
        try:
            from app.utils.oil import add_months

            next_date = add_months(last_date, int(months))
        except (TypeError, ValueError):
            pass

    next_miles = getattr(host, "next_oil_due_mileage", None)
    last_miles = getattr(host, "last_oil_change_mileage", None)
    miles_interval = getattr(host, "oil_interval_miles", None) or guide.get("interval_miles")
    if next_miles is None and last_miles is not None and miles_interval:
        try:
            next_miles = int(last_miles) + int(miles_interval)
        except (TypeError, ValueError):
            pass

    next_hours = getattr(host, "next_oil_due_hours", None)
    last_hours = getattr(host, "last_oil_hours", None)
    hours_interval = getattr(host, "oil_interval_hours", None) or guide.get("interval_hours")
    if next_hours is None and last_hours is not None and hours_interval:
        try:
            next_hours = float(last_hours) + float(hours_interval)
        except (TypeError, ValueError):
            pass

    due = []
    if next_date:
        delta = (next_date - today).days
        if delta <= 45:
            due.append("overdue" if delta < 0 else "due today" if delta == 0 else f"due in {delta} days")
    current_miles = getattr(host, "current_mileage", None)
    if next_miles is not None and current_miles is not None:
        try:
            remaining = int(next_miles) - int(current_miles)
            if remaining <= 300:
                due.append("overdue" if remaining < 0 else "due now" if remaining == 0 else f"due in {remaining:,} miles")
        except (TypeError, ValueError):
            pass
    current_hours = getattr(host, "hours_used", None)
    if next_hours is not None and current_hours is not None:
        try:
            remaining = float(next_hours) - float(current_hours)
            if remaining <= 5:
                due.append("overdue" if remaining < 0 else "due now" if remaining == 0 else f"due in {remaining:g} hours")
        except (TypeError, ValueError):
            pass
    return {
        "scheduled": bool(next_date or next_miles is not None or next_hours is not None),
        "has_date": next_date is not None,
        "due": due,
        "next_date": next_date,
        "next_miles": next_miles,
        "next_hours": next_hours,
    }


def due_line(item, today: date | None = None) -> str | None:
    status = oil_schedule(item, today)
    if not status["due"]:
        return None
    return f"Oil change · {item.name} · {' / '.join(status['due'])} · /items/{item.id}"


def _open_reminders(items: list) -> dict[int, list]:
    from app.builddb.table_reminders import Reminder
    from app.utils.household import scoped

    rows = scoped(Reminder).filter_by(status="open").filter(
        Reminder.type.in_(("oil_change", "custom"))
    ).all()
    found = {}
    for item in items:
        name = (getattr(item, "name", "") or "").strip()
        legacy_match = re.compile(
            rf"(?:oil\s+change|engine\s+oil).{{0,40}}\b{re.escape(name)}\b"
            rf"|\b{re.escape(name)}\b.{{0,40}}(?:oil\s+change|engine\s+oil)",
            re.I,
        ) if name else None
        matches = [
            row for row in rows
            if (
                row.type == "oil_change" and row.linked_item_id == item.id
            ) or (
                row.type in ("oil_change", "custom")
                and row.linked_item_id is None
                and legacy_match
                and legacy_match.search(row.title or "")
            )
        ]
        if matches:
            found[int(item.id)] = matches
    return found


def _machines() -> list:
    from app.utils.ask import _find_items

    return [item for kind in ("vehicle", "tool") for item in _find_items("", kind, limit=40)]


def _has_other_pending() -> bool:
    return any(
        session.get(key)
        for key in (
            "family_ask_write_pending",
            "family_ask_research_pending",
            "family_ask_oil_pending",
            "family_ask_expire_pending",
            "family_ask_item_pending",
            "family_ask_remove_pending",
        )
    )


def _stage_offer(rows: list[tuple[object, object | None]], today: date) -> dict:
    from app.utils.oil import add_months

    due = add_months(today, 6)
    entries = []
    for item, reminder in rows:
        status = oil_schedule(item, today)
        targets = []
        if status.get("next_miles") is not None:
            targets.append(f"{int(status['next_miles']):,} miles")
        if status.get("next_hours") is not None:
            targets.append(f"{float(status['next_hours']):g} hours")
        entries.append({
            "item_id": int(item.id),
            "name": item.name,
            "due": due.isoformat(),
            "reminder_id": int(reminder.id) if reminder is not None else None,
            "action": "update" if reminder is not None else "add",
            "other_targets": targets,
        })
    session[PENDING_KEY] = {"items": entries}
    is_one = len(entries) == 1
    subject = entries[0]["name"] if is_one else ", ".join(entry["name"] for entry in entries)
    plural = "reminder" if is_one else "reminders"
    date_line = f"{subject}: {_date_label(due)}" if is_one else "; ".join(f"{entry['name']}: {_date_label(due)}" for entry in entries)
    updates = all(reminder is not None for _item, reminder in rows)
    verb = "update" if updates else "add"
    if updates:
        say = f"The oil-change reminder for {subject} has no due date. I can set it for six months from today ({date_line}). Update {plural}?"
    else:
        target_notes = []
        for item, _reminder in rows:
            status = oil_schedule(item, today)
            targets = []
            if status.get("next_miles") is not None:
                targets.append(f"{int(status['next_miles']):,} miles")
            if status.get("next_hours") is not None:
                targets.append(f"{float(status['next_hours']):g} hours")
            if targets:
                target_notes.append(f"{item.name} also has a target at {' / '.join(targets)}")
        note = (" " + "; ".join(target_notes) + ".") if target_notes else ""
        say = f"No oil-change due date is saved for {subject}.{note} I can {verb} {plural} for six months from today ({date_line}). {verb.capitalize()} {plural}?"
    return {"ok": True, "say": say, "confirm": True, "did": [], "vault_locked": False}


def oil_due_answer(text: str):
    """Answer due questions locally; offer a six-month reminder only when needed."""
    raw = (text or "").strip()
    if not raw:
        return None
    from app.utils.ask import _is_due_ask, _oil_targets, tool_due

    if not _is_due_ask(raw.lower()):
        return None
    today = date.today()
    targets = _oil_targets(raw)
    explicit_oil = bool(OIL_ASK.search(raw))
    names_a_machine = bool(re.search(r"\b(?:truck|vehicle|car|tool|equipment)\b", raw, re.I))
    if len(targets) > 1 and (explicit_oil or names_a_machine):
        return f"Which machine should I check for an oil change? {', '.join(item.name for item in targets[:6])}"

    due_result = tool_due()
    open_lines = list(due_result.get("open") or [])
    machines = targets if len(targets) == 1 else _machines()
    reminders = _open_reminders(machines) if machines else {}
    due_items, missing_items, scheduled_items = [], [], []
    for item in machines:
        status = oil_schedule(item, today)
        if status["due"]:
            due_items.append((item, status))
        elif status["has_date"]:
            scheduled_items.append((item, status))
        else:
            item_reminders = reminders.get(int(item.id), [])
            dated = [row for row in item_reminders if _as_date(getattr(row, "due_at", None))]
            if dated:
                row = min(dated, key=lambda reminder: _as_date(reminder.due_at))
                scheduled_items.append((item, {"reminder_date": _as_date(row.due_at), "reminder": row}))
            else:
                # Multiple undated legacy reminders are ambiguous; never select one.
                reminder = item_reminders[0] if len(item_reminders) == 1 else None
                missing_items.append((item, reminder))

    if len(targets) == 1:
        item = targets[0]
        item_due = next((status for machine, status in due_items if machine.id == item.id), None)
        if item_due:
            line = due_line(item, today)
            item_reminders = reminders.get(int(item.id), [])
            dated_reminders = [row for row in item_reminders if _as_date(getattr(row, "due_at", None))]
            if not item_due.get("has_date") and not dated_reminders:
                if len(item_reminders) > 1:
                    return f"{line} I found more than one open oil reminder for {item.name}; which one should I update? /reminders/"
                if has_request_context():
                    from app.utils.permissions import can

                    if can("maintain") and not _has_other_pending():
                        offer = _stage_offer([(item, item_reminders[0] if item_reminders else None)], today)
                        offer["say"] = f"{line} {offer['say']}"
                        return offer
            return line
        item_scheduled = next((status for machine, status in scheduled_items if machine.id == item.id), None)
        if item_scheduled:
            if item_scheduled.get("reminder_date"):
                day = item_scheduled["reminder_date"]
                delta = (day - today).days
                when = "overdue" if delta < 0 else "due today" if delta == 0 else f"due in {delta} days"
                return f"Oil-change reminder for {item.name}: {_date_label(day)} ({when}). /reminders/"
            bits = []
            if item_scheduled.get("next_date"):
                bits.append(f"date {_date_label(item_scheduled['next_date'])}")
            if item_scheduled.get("next_miles") is not None:
                bits.append(f"{int(item_scheduled['next_miles']):,} miles")
            if item_scheduled.get("next_hours") is not None:
                bits.append(f"{float(item_scheduled['next_hours']):g} hours")
            return f"I don’t see an oil change due yet for {item.name}; its saved next target is {' and '.join(bits)}. /items/{item.id}"
        if missing_items:
            reminder = missing_items[0][1]
            if reminder is None and reminders.get(int(item.id)):
                return f"I found more than one open oil reminder for {item.name}. Which one should I update? /reminders/"
            if has_request_context():
                from app.utils.permissions import can

                if can("maintain") and not _has_other_pending():
                    return _stage_offer([(item, reminder)], today)
            return f"No oil-change due date or reminder is saved for {item.name}. Ask a household maintainer to add a six-month reminder. /items/{item.id}"

    # “What’s due” keeps the combined bills, reminders, oil, and expiring-food view.
    # A specifically oil-only question does not clutter its answer with other categories.
    result = "Due:\n" + "\n".join(f"· {line}" for line in open_lines) if not explicit_oil and open_lines else ""
    if missing_items and explicit_oil and len(targets) == 1:
        if len(missing_items) > 1:
            who = ", ".join(item.name for item, _reminder in missing_items[:6])
            tail = f"No oil-change due date or reminder is saved for {who}. Which machine should I check?"
            return (result + "\n" + tail).strip() if result else tail
        item, reminder = missing_items[0]
        if reminder is None and reminders.get(int(item.id)):
            tail = f"I found more than one open oil reminder for {item.name}. Which one should I update?"
            return (result + "\n" + tail).strip() if result else tail
        if has_request_context():
            from app.utils.permissions import can

            if can("maintain") and not _has_other_pending():
                offer = _stage_offer([(item, reminder)], today)
                offer["say"] = (result + "\n" + offer["say"]).strip() if result else offer["say"]
                return offer
        item_names = ", ".join(item.name for item, _reminder in missing_items[:6])
        tail = f"No oil-change due date or reminder is saved for {item_names}; a maintainer can add a six-month reminder."
        return (result + "\n" + tail).strip() if result else tail

    if result:
        return result
    if explicit_oil:
        if not machines:
            return "I don’t see any vehicles or tools saved to check for an oil change yet."
        if due_items:
            lines = [due_line(item, today) for item, _status in due_items]
            return "Due:\n" + "\n".join(f"· {line}" for line in lines if line)
        return "No saved oil-change date or reminder shows as due right now."
    return "Nothing due right now. Oil changes, bills, and food show up here when their saved due dates get close. /reminders/"


def handle_pending_reply(text: str):
    """Consume yes/no for staged reminder offers; unrelated turns clear stale offers."""
    if not has_request_context() or not isinstance(session.get(PENDING_KEY), dict):
        return None
    raw = (text or "").strip()
    if not (_YES.match(raw) or _NO.match(raw)):
        return None
    if _has_other_pending():
        # Another confirmation owns this reply. Drop the stale oil offer so a later
        # unrelated "yes" cannot unexpectedly apply it.
        session.pop(PENDING_KEY, None)
        return None
    pending = session.get(PENDING_KEY) or {}
    if _NO.match(raw):
        session.pop(PENDING_KEY, None)
        entries = pending.get("items") if isinstance(pending.get("items"), list) else []
        updating = bool(entries) and all(
            isinstance(entry, dict) and entry.get("reminder_id") for entry in entries
        )
        verb = "change" if updating else "add"
        return {"ok": True, "say": f"Okay, I won’t {verb} an oil-change reminder.", "did": [], "vault_locked": False}
    if _YES.match(raw):
        session.pop(PENDING_KEY, None)
        return apply_pending_oil_reminders(pending)
    session.pop(PENDING_KEY, None)
    return None


def apply_pending_oil_reminders(pending: dict) -> dict:
    """Create/update approved reminders after rechecking household ownership."""
    from app.builddb.builddb import db
    from app.builddb.table_items import Item
    from app.builddb.table_reminders import Reminder
    from app.utils.ask import tool_reminder_save
    from app.utils.household import scoped
    from app.utils.permissions import can

    if not can("maintain"):
        return {"ok": False, "say": "You cannot add an oil-change reminder.", "did": [], "vault_locked": False}
    entries = pending.get("items") if isinstance(pending.get("items"), list) else []
    saved, skipped = [], []
    for entry in entries:
        if not isinstance(entry, dict) or not str(entry.get("item_id") or "").isdigit():
            continue
        due_day = _as_date(entry.get("due"))
        if due_day is None:
            skipped.append(str(entry.get("name") or "a machine"))
            continue
        item = scoped(Item).filter_by(id=int(entry["item_id"])).first()
        if item is None or item.item_type not in ("vehicle", "tool"):
            skipped.append(str(entry.get("name") or "a machine"))
            continue
        if oil_schedule(item)["has_date"]:
            skipped.append(item.name)
            continue
        reminder_id = entry.get("reminder_id")
        if reminder_id:
            try:
                reminder_ident = int(reminder_id)
            except (TypeError, ValueError):
                skipped.append(item.name)
                continue
            reminder = scoped(Reminder).filter_by(id=reminder_ident, status="open").first()
            if reminder is None:
                skipped.append(item.name)
                continue
            still_matches = (
                reminder.type == "oil_change" and reminder.linked_item_id == item.id
            ) or any(
                row.id == reminder.id
                for row in _open_reminders([item]).get(int(item.id), [])
            )
            if not still_matches or reminder.due_at is not None or reminder.linked_item_id not in (None, item.id):
                skipped.append(item.name)
                continue
            reminder.due_at = datetime.combine(due_day, datetime.min.time())
            reminder.recurrence = "180d"
            reminder.type = "oil_change"
            reminder.linked_item_id = item.id
            try:
                from app.utils.notify import announce_reminder

                announce_reminder(reminder)
            except Exception:
                pass
            db.session.commit()
            saved.append({"title": reminder.title, "due": due_day.isoformat(), "action": "Updated"})
            continue
        if _open_reminders([item]).get(int(item.id)):
            skipped.append(item.name)
            continue
        result = tool_reminder_save({
            "title": f"Oil change — {item.name}",
            "type": "oil_change",
            "due": due_day.isoformat(),
            "every": "180d",
            "linked_item_id": item.id,
            "confirmed": True,
        })
        if result.get("ok"):
            saved.append({**result, "action": "Added"})
        else:
            skipped.append(item.name)
    if not saved:
        return {"ok": False, "say": "I couldn’t add an oil-change reminder. Nothing new was scheduled.", "did": [], "vault_locked": False}
    action_words = {row.get("action") for row in saved}
    summary = "Updated" if action_words == {"Updated"} else "Added" if action_words == {"Added"} else "Scheduled"
    lines = [f"{row.get('action') or 'Added'} {row.get('title')}: {row.get('due')} · /reminders/" for row in saved]
    if skipped:
        lines.append("No reminder added for " + ", ".join(skipped) + " (it changed or is no longer in the household).")
    return {"ok": True, "say": summary + ":\n" + "\n".join(f"· {line}" for line in lines), "did": ["reminder"], "vault_locked": False}
