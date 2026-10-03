"""House content the account can already open, beyond the first five lists.

Basket, due dates, tools, the house, logs, photos, search, people, cases,
Ask history, and the leader activity log. Each route still requires the
house key, then the same permission that page uses.
"""
from __future__ import annotations

import os
from datetime import datetime

from flask import request

from app.builddb.builddb import db
from app.routes.bot_api import (
    BOT,
    as_dec,
    as_int,
    as_num,
    as_str,
    bot_api_bp,
    limit_arg,
    note_activity,
    offset_arg,
    ok,
    page,
)
from app.utils.bot_api_access import account_can, gate
from app.utils.bot_api_auth import (
    api_error,
    api_household_id,
    api_scope,
    api_user,
    body,
    bot_api,
    iso,
    iso_date,
)


def _blocked_view():
    return gate("view", "scan")


@bot_api_bp.route("/basket")
@bot_api(BOT)
def basket_list():
    from app.builddb.table_grocery_list import GroceryListEntry

    blocked = _blocked_view()
    if blocked:
        return blocked
    status = (request.args.get("status") or "open").strip().lower()
    q = api_scope(GroceryListEntry).order_by(GroceryListEntry.created_at.desc())
    if status and status != "all":
        q = q.filter_by(status=status)
    total = q.count()
    rows = q.offset(offset_arg()).limit(limit_arg()).all()
    return ok({"basket": [_basket_json(r) for r in rows], **page(rows, total)})


@bot_api_bp.route("/basket", methods=["POST"])
@bot_api(BOT, write=True)
def basket_add():
    from app.builddb.table_grocery_list import GroceryListEntry

    blocked = gate("scan", "edit_grocery")
    if blocked:
        return blocked
    data = body()
    name = as_str(data, "name", 200)
    if not name:
        return api_error("name is required.", 400, "bad_request")
    item_id = as_int(data, "item_id")
    if item_id is not None:
        from app.builddb.table_items import Item

        if api_scope(Item).filter_by(id=item_id).first() is None:
            return api_error("No such item in this household.", 404, "not_found")
    row = GroceryListEntry(
        household_id=api_household_id(),
        item_id=item_id,
        name=name,
        quantity_needed=as_dec(data, "quantity_needed"),
        status="open",
        added_reason=(as_str(data, "reason", 80) or "want"),
        note=as_str(data, "note", 120),
        created_by=getattr(api_user(), "id", None),
    )
    db.session.add(row)
    db.session.commit()
    note_activity(
        "bot.basket.add",
        f"A bot added {row.name} to the basket",
        target_table="grocery_list",
        target_id=row.id,
        item_id=row.item_id,
    )
    return ok({"entry": _basket_json(row)}, 201)


@bot_api_bp.route("/basket/<int:entry_id>/done", methods=["POST"])
@bot_api(BOT, write=True)
def basket_done(entry_id):
    from app.builddb.table_grocery_list import GroceryListEntry

    blocked = gate("scan", "edit_grocery")
    if blocked:
        return blocked
    row = api_scope(GroceryListEntry).filter_by(id=entry_id).first()
    if row is None:
        return api_error("No such basket line in this household.", 404, "not_found")
    row.status = "done"
    row.completed_at = datetime.utcnow()
    db.session.commit()
    note_activity(
        "bot.basket.done",
        f"A bot checked off {row.name}",
        target_table="grocery_list",
        target_id=row.id,
    )
    return ok({"entry": _basket_json(row)})


def _basket_json(row) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "item_id": row.item_id,
        "quantity_needed": as_num(row.quantity_needed),
        "status": row.status,
        "reason": row.added_reason or "",
        "note": row.note or "",
        "created_at": iso(row.created_at),
    }


@bot_api_bp.route("/reminders")
@bot_api(BOT)
def reminders_list():
    from app.builddb.table_reminders import Reminder
    from app.utils.reminders_copy import recurrence_label, type_label

    blocked = _blocked_view()
    if blocked:
        return blocked
    q = api_scope(Reminder).order_by(Reminder.due_at.asc())
    status = (request.args.get("status") or "").strip().lower()
    if status:
        q = q.filter_by(status=status)
    total = q.count()
    rows = q.offset(offset_arg()).limit(limit_arg()).all()
    return ok(
        {
            "reminders": [
                {
                    "id": r.id,
                    "title": r.title,
                    "type": r.type,
                    "type_label": type_label(r.type),
                    "due_at": iso(r.due_at),
                    "recurrence": r.recurrence or "",
                    "recurrence_label": recurrence_label(r.recurrence),
                    "status": r.status,
                    "notes": r.notes or "",
                    "item_id": r.linked_item_id,
                }
                for r in rows
            ],
            **page(rows, total),
        }
    )


@bot_api_bp.route("/reminders", methods=["POST"])
@bot_api(BOT, write=True)
def reminders_add():
    from app.builddb.table_reminders import Reminder
    from app.utils.reminders_copy import REMINDER_TYPES, parse_recurrence

    blocked = gate("maintain")
    if blocked:
        return blocked
    data = body()
    title = as_str(data, "title", 200)
    if not title:
        return api_error("title is required.", 400, "bad_request")
    rtype = (as_str(data, "type", 80) or "custom").lower()
    if rtype not in {key for key, _label in REMINDER_TYPES}:
        rtype = "custom"
    due_at = None
    raw_due = as_str(data, "due_at", 40)
    if raw_due:
        try:
            due_at = datetime.fromisoformat(raw_due.replace("Z", ""))
        except ValueError:
            return api_error("due_at must be a date-time.", 400, "bad_request")
    row = Reminder(
        household_id=api_household_id(),
        title=title,
        type=rtype,
        due_at=due_at,
        linked_item_id=as_int(data, "item_id"),
        recurrence=parse_recurrence(as_str(data, "recurrence", 40)),
        notes=as_str(data, "notes", 2000),
        status="open",
        created_by=getattr(api_user(), "id", None),
    )
    db.session.add(row)
    db.session.commit()
    note_activity(
        "bot.reminder.add",
        f"A bot added the reminder {title}",
        target_table="reminders",
        target_id=row.id,
        item_id=row.linked_item_id,
    )
    return ok({"reminder": {"id": row.id, "title": row.title, "due_at": iso(row.due_at)}}, 201)


@bot_api_bp.route("/reminders/<int:reminder_id>/done", methods=["POST"])
@bot_api(BOT, write=True)
def reminders_done(reminder_id):
    from app.builddb.table_reminders import Reminder

    blocked = gate("maintain")
    if blocked:
        return blocked
    row = api_scope(Reminder).filter_by(id=reminder_id).first()
    if row is None:
        return api_error("No such reminder in this household.", 404, "not_found")
    row.status = "done"
    db.session.commit()
    return ok({"reminder": {"id": row.id, "status": row.status}})


@bot_api_bp.route("/tools")
@bot_api(BOT)
def tools_list():
    from app.builddb.table_items import Item

    blocked = _blocked_view()
    if blocked:
        return blocked
    q = api_scope(Item).filter_by(item_type="tool").order_by(Item.name.asc())
    total = q.count()
    rows = q.offset(offset_arg()).limit(limit_arg()).all()
    return ok({"tools": [_tool_json(r) for r in rows], **page(rows, total)})


@bot_api_bp.route("/house")
@bot_api(BOT)
def house_list():
    from app.builddb.table_items import Item

    blocked = _blocked_view()
    if blocked:
        return blocked
    q = api_scope(Item).filter_by(item_type="house").order_by(Item.name.asc())
    total = q.count()
    rows = q.offset(offset_arg()).limit(limit_arg()).all()
    return ok({"house": [_place_json(r) for r in rows], **page(rows, total)})


def _tool_json(item) -> dict:
    tool = item.tool
    out = {"id": item.id, "name": item.name, "notes": item.notes or ""}
    if tool is not None:
        out.update(
            {
                "type": tool.type,
                "model": tool.model,
                "serial_number": tool.serial_number,
                "asset_id": tool.asset_id,
                "oil_needs": tool.oil_needs,
                "hours_used": as_num(tool.hours_used),
            }
        )
    return out


def _place_json(item) -> dict:
    return {"id": item.id, "name": item.name, "category": item.category, "notes": item.notes or ""}


@bot_api_bp.route("/items/<int:item_id>/logs")
@bot_api(BOT)
def logs_list(item_id):
    from app.builddb.table_item_logs import ItemLog
    from app.builddb.table_items import Item

    blocked = _blocked_view()
    if blocked:
        return blocked
    if api_scope(Item).filter_by(id=item_id).first() is None:
        return api_error("No such item in this household.", 404, "not_found")
    q = api_scope(ItemLog).filter_by(item_id=item_id).order_by(ItemLog.id.desc())
    total = q.count()
    rows = q.offset(offset_arg()).limit(limit_arg()).all()
    return ok({"logs": [_log_json(r) for r in rows], **page(rows, total)})


@bot_api_bp.route("/items/<int:item_id>/logs", methods=["POST"])
@bot_api(BOT, write=True)
def logs_add(item_id):
    from app.builddb.table_item_logs import LOG_KINDS, ItemLog
    from app.builddb.table_items import Item

    blocked = gate("maintain", "edit_meta")
    if blocked:
        return blocked
    item = api_scope(Item).filter_by(id=item_id).first()
    if item is None:
        return api_error("No such item in this household.", 404, "not_found")
    data = body()
    kind = (as_str(data, "kind", 20) or "note").lower()
    if kind not in LOG_KINDS:
        kind = "note"
    row = ItemLog(
        household_id=api_household_id(),
        item_id=item.id,
        kind=kind,
        happened_on=_as_day(data, "happened_on"),
        reading=as_dec(data, "reading"),
        gallons=as_dec(data, "gallons"),
        cost=as_dec(data, "cost"),
        title=as_str(data, "title", 200),
        notes=as_str(data, "notes", 5000),
        created_by=getattr(api_user(), "id", None),
    )
    db.session.add(row)
    db.session.commit()
    note_activity(
        "bot.log.add",
        f"A bot logged {kind} on {item.name}",
        target_table="item_logs",
        target_id=row.id,
        item_id=item.id,
    )
    return ok({"log": _log_json(row)}, 201)


def _as_day(data, key):
    raw = as_str(data, key, 10)
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _log_json(row) -> dict:
    return {
        "id": row.id,
        "item_id": row.item_id,
        "kind": row.kind,
        "happened_on": iso_date(row.happened_on),
        "reading": as_num(row.reading),
        "gallons": as_num(row.gallons),
        "cost": as_num(row.cost),
        "title": row.title or "",
        "notes": row.notes or "",
        "created_at": iso(row.created_at),
    }


@bot_api_bp.route("/photos")
@bot_api(BOT)
def photos_list():
    from app.builddb.table_photo_notes import PhotoNote

    blocked = _blocked_view()
    if blocked:
        return blocked
    q = api_scope(PhotoNote).order_by(PhotoNote.id.desc())
    item_id = request.args.get("item_id")
    if item_id:
        try:
            q = q.filter_by(item_id=int(item_id))
        except (TypeError, ValueError):
            return api_error("item_id must be a number.", 400, "bad_request")
    total = q.count()
    rows = q.offset(offset_arg()).limit(limit_arg()).all()
    return ok({"photos": [_photo_json(r) for r in rows], **page(rows, total)})


@bot_api_bp.route("/photos/<int:photo_id>")
@bot_api(BOT)
def photos_get(photo_id):
    from app.builddb.table_photo_notes import PhotoNote
    from app.routes.items import resolve_photo_file
    from app.utils.crypto import sendable_image

    blocked = _blocked_view()
    if blocked:
        return blocked
    row = api_scope(PhotoNote).filter_by(id=photo_id).first()
    if row is None:
        return api_error("No such photo in this household.", 404, "not_found")
    path = resolve_photo_file(row)
    ext = os.path.splitext(str(path.name).replace(".enc", ""))[1].lower()
    path = str(path)
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".pdf": "application/pdf",
    }.get(ext, "application/octet-stream")
    return sendable_image(path, mime)


def _photo_json(row) -> dict:
    return {
        "id": row.id,
        "item_id": row.item_id,
        "part_id": row.part_id,
        "log_id": row.log_id,
        "kind": row.kind,
        "caption": row.caption or "",
        "download": f"/api/v1/photos/{row.id}",
        "created_at": iso(row.created_at),
    }


@bot_api_bp.route("/find")
@bot_api(BOT)
def find_search():
    from app.utils.crypto import decrypt_text
    from app.utils.search import search_household

    blocked = _blocked_view()
    if blocked:
        return blocked
    q = (request.args.get("q") or "").strip()
    if not q:
        return api_error("q is required.", 400, "bad_request")
    scope = (request.args.get("scope") or "all").strip().lower()
    hit = search_household(
        api_household_id(),
        q,
        user_id=int(getattr(api_user(), "id", 0) or 0),
        limit=min(limit_arg(default=20, ceiling=40), 40),
        scope=scope,
    )
    legal = []
    cases = []
    if account_can("legal"):
        legal = [
            {"id": r.id, "kind": r.kind, "title": decrypt_text(r.title) or ""}
            for r in hit.get("legal_rows") or []
        ]
        cases = [
            {"id": c.id, "number": c.number, "title": decrypt_text(c.title) or "", "status": c.status}
            for c in hit.get("case_rows") or []
        ]
    return ok(
        {
            "q": hit.get("q") or q,
            "items": [
                {"id": i.id, "name": i.name, "item_type": i.item_type} for i in hit.get("item_rows") or []
            ],
            "notes": [
                {"id": n.id, "title": decrypt_text(n.title) or ""} for n in hit.get("note_rows") or []
            ],
            "parts": [
                {
                    "id": p.id,
                    "name": p.name,
                    "item_id": p.vehicle_item_id,
                    "where": (hit.get("part_where") or {}).get(p.id) or "",
                }
                for p in hit.get("part_rows") or []
            ],
            "records": legal,
            "cases": cases,
        }
    )


@bot_api_bp.route("/people")
@bot_api(BOT)
def people_list():
    from app.builddb.table_users import User
    from app.utils.permissions import role_of

    blocked = _blocked_view()
    if blocked:
        return blocked
    user = api_user()
    if role_of(user) == "child":
        return api_error("This account cannot do that.", 403, "forbidden")
    rows = (
        User.query.filter_by(household_id=api_household_id())
        .order_by(User.name.asc())
        .all()
    )
    return ok(
        {
            "people": [
                {
                    "id": u.id,
                    "name": u.name or "",
                    "username": u.username or "",
                    "role": u.role or "",
                    "is_leader": bool(u.is_leader),
                    "is_bot": bool(u.is_bot),
                    "is_active": bool(u.is_active),
                    "email": u.email or "",
                }
                for u in rows
            ]
        }
    )


@bot_api_bp.route("/cases")
@bot_api(BOT)
def cases_list():
    from app.builddb.table_legal_cases import LegalCase
    from app.utils.crypto import decrypt_text

    blocked = gate("legal")
    if blocked:
        return blocked
    q = api_scope(LegalCase).order_by(LegalCase.number.desc())
    total = q.count()
    rows = q.offset(offset_arg()).limit(limit_arg()).all()
    return ok(
        {
            "cases": [
                {
                    "id": c.id,
                    "number": c.number,
                    "title": decrypt_text(c.title) or "",
                    "status": c.status,
                    "summary": decrypt_text(c.summary) or "",
                }
                for c in rows
            ],
            **page(rows, total),
        }
    )


@bot_api_bp.route("/ask")
@bot_api(BOT)
def ask_history():
    from app.builddb.table_ask_turns import AskTurn
    from app.utils.permissions import role_of

    blocked = _blocked_view()
    if blocked:
        return blocked
    user = api_user()
    if role_of(user) == "child":
        return api_error("This account cannot do that.", 403, "forbidden")
    room = (request.args.get("room") or "").strip().lower()
    q = api_scope(AskTurn).filter_by(user_id=int(user.id)).order_by(AskTurn.id.desc())
    if room:
        q = q.filter_by(room=room[:20])
    total = q.count()
    rows = q.offset(offset_arg()).limit(limit_arg()).all()
    return ok(
        {
            "turns": [
                {"id": t.id, "role": t.role, "room": t.room, "body": t.body or "", "created_at": iso(t.created_at)}
                for t in rows
            ],
            **page(rows, total),
        }
    )


@bot_api_bp.route("/activity")
@bot_api(BOT)
def activity_list():
    from app.utils.activity import newest_at, recent

    blocked = gate("override")
    if blocked:
        return blocked
    try:
        hours = int(request.args.get("hours") or 48)
    except (TypeError, ValueError):
        hours = 48
    hid = api_household_id()
    rows = recent(hid, limit=limit_arg(default=40, ceiling=80), hours=hours or None)
    for row in rows:
        row["when"] = iso(row.get("when"))
        row["reversed_at"] = iso(row.get("reversed_at"))
    last = newest_at(hid)
    return ok({
        "activity": rows,
        "count": len(rows),
        "window_hours": hours,
        "newest_at": iso(last),
        "recording": True,
    })
