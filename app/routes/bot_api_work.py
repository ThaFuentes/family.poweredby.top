"""The rest of the household work a house key is allowed to finish.

Tools, house things, oil, parts, cases, and reminder edits. Same account
permissions as the pages. No delete. A vault key never reaches these routes.
"""
from __future__ import annotations

from datetime import datetime

from app.builddb.builddb import db
from app.routes.bot_api import (
    BOT,
    as_dec,
    as_int,
    as_str,
    bot_api_bp,
    limit_arg,
    note_activity,
    offset_arg,
    ok,
    page,
)
from app.utils.bot_api_access import gate
from app.utils.bot_api_auth import (
    api_error,
    api_household_id,
    api_scope,
    api_user,
    body,
    bot_api,
    iso,
)


def _item(item_id: int, kind: str | None = None):
    from app.builddb.table_items import Item

    q = api_scope(Item).filter_by(id=item_id)
    if kind:
        q = q.filter_by(item_type=kind)
    return q.first()


def _tool_out(item) -> dict:
    tool = item.tool
    out = {
        "id": item.id,
        "name": item.name,
        "category": item.category,
        "notes": item.notes or "",
    }
    if tool is not None:
        out.update(
            {
                "type": tool.type,
                "model": tool.model,
                "serial_number": tool.serial_number,
                "asset_id": tool.asset_id,
                "power_source": tool.power_source,
                "oil_needs": tool.oil_needs,
                "oil_capacity": tool.oil_capacity,
                "hours_used": str(tool.hours_used or ""),
            }
        )
    return out


@bot_api_bp.route("/tools/<int:item_id>")
@bot_api(BOT)
def tools_get(item_id):
    blocked = gate("view")
    if blocked:
        return blocked
    item = _item(item_id, "tool")
    if item is None:
        return api_error("No such tool in this household.", 404, "not_found")
    return ok({"tool": _tool_out(item)})


@bot_api_bp.route("/tools", methods=["POST"])
@bot_api(BOT, write=True)
def tools_create():
    blocked = gate("maintain", "edit_meta")
    if blocked:
        return blocked
    from app.builddb.table_items import Item
    from app.builddb.table_tools import Tool

    data = body()
    name = as_str(data, "name", 200)
    if not name:
        return api_error("name is required.", 400, "bad_request")
    item = Item(
        household_id=api_household_id(),
        item_type="tool",
        name=name,
        category=as_str(data, "category", 100),
        notes=as_str(data, "notes", 5000),
        created_by=getattr(api_user(), "id", None),
    )
    db.session.add(item)
    db.session.flush()
    tool = Tool(
        item_id=item.id,
        household_id=api_household_id(),
        type=as_str(data, "type", 80),
        model=as_str(data, "model", 120),
        serial_number=as_str(data, "serial_number", 120),
        asset_id=as_str(data, "asset_id", 80),
        power_source=as_str(data, "power_source", 40),
        oil_needs=as_str(data, "oil_needs", 200),
        oil_capacity=as_str(data, "oil_capacity", 40),
    )
    db.session.add(tool)
    db.session.commit()
    note_activity(
        "bot.tool.add",
        f"A bot added the tool {item.name}",
        target_table="items",
        target_id=item.id,
        item_id=item.id,
        old={"undo": "hide_item"},
    )
    return ok({"tool": _tool_out(item)}, 201)


@bot_api_bp.route("/tools/<int:item_id>", methods=["PATCH"])
@bot_api(BOT, write=True)
def tools_update(item_id):
    blocked = gate("maintain", "edit_meta")
    if blocked:
        return blocked
    from app.builddb.table_tools import Tool

    item = _item(item_id, "tool")
    if item is None:
        return api_error("No such tool in this household.", 404, "not_found")
    from app.utils.activity_undo import fields_undo, snap_item, snap_tool

    before = fields_undo(item=snap_item(item), tool=snap_tool(item.tool))
    data = body()
    if "name" in data:
        item.name = as_str(data, "name", 200) or item.name
    if "category" in data:
        item.category = as_str(data, "category", 100)
    if "notes" in data:
        item.notes = as_str(data, "notes", 5000)
    tool = item.tool or Tool(item_id=item.id, household_id=api_household_id())
    for key, cap in (
        ("type", 80),
        ("model", 120),
        ("serial_number", 120),
        ("asset_id", 80),
        ("power_source", 40),
        ("oil_needs", 200),
        ("oil_capacity", 40),
    ):
        if key in data:
            setattr(tool, key, as_str(data, key, cap))
    db.session.add(tool)
    db.session.add(item)
    db.session.commit()
    note_activity(
        "bot.tool.update",
        f"A bot updated the tool {item.name}",
        target_table="items",
        target_id=item.id,
        item_id=item.id,
        old=before,
    )
    return ok({"tool": _tool_out(item)})


def _house_out(item) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "category": item.category,
        "notes": item.notes or "",
    }


@bot_api_bp.route("/house/<int:item_id>")
@bot_api(BOT)
def house_get(item_id):
    blocked = gate("view")
    if blocked:
        return blocked
    item = _item(item_id, "house")
    if item is None:
        return api_error("No such house thing in this household.", 404, "not_found")
    return ok({"place": _house_out(item)})


@bot_api_bp.route("/house", methods=["POST"])
@bot_api(BOT, write=True)
def house_create():
    blocked = gate("maintain", "edit_meta")
    if blocked:
        return blocked
    from app.builddb.table_items import Item

    data = body()
    name = as_str(data, "name", 200)
    if not name:
        return api_error("name is required.", 400, "bad_request")
    item = Item(
        household_id=api_household_id(),
        item_type="house",
        name=name,
        category=as_str(data, "category", 100),
        notes=as_str(data, "notes", 5000),
        created_by=getattr(api_user(), "id", None),
    )
    db.session.add(item)
    db.session.commit()
    note_activity(
        "bot.house.add",
        f"A bot added {item.name} to the house",
        target_table="items",
        target_id=item.id,
        item_id=item.id,
        old={"undo": "hide_item"},
    )
    return ok({"place": _house_out(item)}, 201)


@bot_api_bp.route("/house/<int:item_id>", methods=["PATCH"])
@bot_api(BOT, write=True)
def house_update(item_id):
    blocked = gate("maintain", "edit_meta")
    if blocked:
        return blocked
    item = _item(item_id, "house")
    if item is None:
        return api_error("No such house thing in this household.", 404, "not_found")
    from app.utils.activity_undo import fields_undo, snap_item

    before = fields_undo(item=snap_item(item))
    data = body()
    if "name" in data:
        item.name = as_str(data, "name", 200) or item.name
    if "category" in data:
        item.category = as_str(data, "category", 100)
    if "notes" in data:
        item.notes = as_str(data, "notes", 5000)
    db.session.add(item)
    db.session.commit()
    note_activity(
        "bot.house.update",
        f"A bot updated {item.name}",
        target_table="items",
        target_id=item.id,
        item_id=item.id,
        old=before,
    )
    return ok({"place": _house_out(item)})


@bot_api_bp.route("/items/<int:item_id>/oil", methods=["POST"])
@bot_api(BOT, write=True)
def oil_save(item_id):
    blocked = gate("maintain", "edit_meta")
    if blocked:
        return blocked
    from app.utils.oil import (
        apply_fluids_payload,
        get_fluids,
        normalize_oil_payload,
        oil_payload_has_fields,
        save_item_oil,
    )

    item = _item(item_id)
    if item is None:
        return api_error("No such item in this household.", 404, "not_found")
    if item.vehicle is None and item.tool is None:
        return api_error("That item does not keep an oil record.", 400, "bad_request")
    from app.utils.activity_undo import oil_snap

    host_before = item.vehicle or item.tool
    oil_before = oil_snap(host_before)
    oil_on = "vehicle" if item.vehicle is not None else "tool"
    data = body()
    payload = normalize_oil_payload(data)
    if not oil_payload_has_fields(payload):
        return api_error("Say the oil it needs, such as 5W-30, or a fluid spec.", 400, "bad_request")
    engine_keys = (
        "needs", "oil_needs", "capacity", "oil_capacity", "in_it", "oil_type",
        "filter", "filter_type", "last_date", "last_miles", "last_hours",
        "interval_miles", "interval_months", "interval_hours",
        "next_date", "next_miles", "next_hours",
    )
    if not any(str(payload.get(key) or "").strip() for key in engine_keys):
        payload = {key: value for key, value in payload.items() if key in ("fluid", "fluids", "value")}
    try:
        save_item_oil(item, payload, clear=False)
    except ValueError:
        db.session.rollback()
        return api_error("That item does not keep an oil record.", 400, "bad_request")
    host = item.vehicle or item.tool
    apply_fluids_payload(host, payload)
    db.session.commit()
    note_activity(
        "bot.oil.save",
        f"A bot saved oil on {item.name}",
        target_table="items",
        target_id=item.id,
        item_id=item.id,
        old={"undo": "fields", "oil": oil_before, "oil_on": oil_on},
    )
    return ok(
        {
            "item_id": item.id,
            "name": item.name,
            "needs": getattr(host, "oil_needs", None) or "",
            "capacity": getattr(host, "oil_capacity", None) or "",
            "in_it": getattr(host, "oil_type", None) or "",
            "fluids": get_fluids(host),
        }
    )


def _part_out(row) -> dict:
    return {
        "id": row.id,
        "item_id": row.vehicle_item_id,
        "name": row.name,
        "system": row.system,
        "slot": row.slot,
        "status": row.status,
        "part_number": row.part_number,
        "brand": row.brand,
        "spec": row.spec,
    }


@bot_api_bp.route("/items/<int:item_id>/parts")
@bot_api(BOT)
def parts_list(item_id):
    from app.builddb.table_vehicle_parts import VehiclePart

    blocked = gate("view")
    if blocked:
        return blocked
    item = _item(item_id, "vehicle")
    if item is None:
        return api_error("No such vehicle in this household.", 404, "not_found")
    q = api_scope(VehiclePart).filter_by(vehicle_item_id=item.id).order_by(VehiclePart.id.desc())
    total = q.count()
    rows = q.offset(offset_arg()).limit(limit_arg()).all()
    return ok({"parts": [_part_out(row) for row in rows], **page(rows, total)})


@bot_api_bp.route("/items/<int:item_id>/parts", methods=["POST"])
@bot_api(BOT, write=True)
def parts_add(item_id):
    blocked = gate("maintain", "edit_meta")
    if blocked:
        return blocked
    from app.utils.vehicle_systems import install_part

    item = _item(item_id, "vehicle")
    if item is None:
        return api_error("No such vehicle in this household.", 404, "not_found")
    data = body()
    name = as_str(data, "name", 200)
    if not name:
        return api_error("name is required.", 400, "bad_request")
    row = install_part(
        hid=api_household_id(),
        vehicle_item_id=item.id,
        user_id=getattr(api_user(), "id", None),
        system=as_str(data, "system", 40) or "other",
        slot=as_str(data, "slot", 40) or "misc",
        name=name,
        brand=as_str(data, "brand", 120),
        spec=as_str(data, "spec", 160),
        part_number=as_str(data, "part_number", 80),
        model=as_str(data, "model", 120),
        serial_number=as_str(data, "serial_number", 120),
        asset_id=as_str(data, "asset_id", 80),
        status=as_str(data, "status", 20) or "installed",
        installed_on=as_str(data, "installed_on", 40),
        installed_mileage=as_int(data, "installed_mileage"),
        notes=as_str(data, "notes", 2000),
        source=as_str(data, "source", 200),
        cost=as_dec(data, "cost"),
    )
    db.session.commit()
    note_activity(
        "bot.part.add",
        f"A bot put {row.name} on {item.name}",
        target_table="vehicle_parts",
        target_id=row.id,
        item_id=item.id,
        old={"undo": "retire_part"},
    )
    return ok({"part": _part_out(row)}, 201)


def _case_out(case) -> dict:
    from app.builddb.table_legal_cases import case_label
    from app.utils.crypto import decrypt_text

    return {
        "id": case.id,
        "number": case.number,
        "label": case_label(case),
        "title": decrypt_text(case.title) or "",
        "status": case.status,
        "summary": decrypt_text(case.summary) or "",
    }


@bot_api_bp.route("/cases/<int:case_id>")
@bot_api(BOT)
def cases_get(case_id):
    from app.builddb.table_legal_cases import LegalCase

    blocked = gate("legal")
    if blocked:
        return blocked
    case = api_scope(LegalCase).filter_by(id=case_id).first()
    if case is None:
        return api_error("No such case in this household.", 404, "not_found")
    return ok({"case": _case_out(case)})


@bot_api_bp.route("/cases", methods=["POST"])
@bot_api(BOT, write=True)
def cases_create():
    blocked = gate("legal")
    if blocked:
        return blocked
    from app.builddb.table_legal_cases import CASE_STATUSES, LegalCase, next_case_number

    data = body()
    title = as_str(data, "title", 500)
    if not title:
        return api_error("title is required.", 400, "bad_request")
    status = (as_str(data, "status", 20) or "open").lower()
    if status not in CASE_STATUSES:
        status = "open"
    case = LegalCase(
        household_id=api_household_id(),
        number=next_case_number(api_household_id()),
        title=title,
        status=status,
        summary=as_str(data, "summary", 8000),
        created_by=getattr(api_user(), "id", None),
    )
    db.session.add(case)
    db.session.commit()
    note_activity(
        "bot.case.add",
        f"A bot opened {case.number} {title}",
        target_table="legal_cases",
        target_id=case.id,
        old={"undo": "status", "status": "closed"},
    )
    return ok({"case": _case_out(case)}, 201)


@bot_api_bp.route("/cases/<int:case_id>", methods=["PATCH"])
@bot_api(BOT, write=True)
def cases_update(case_id):
    from app.builddb.table_legal_cases import LegalCase
    from app.services.legal import edit_case

    blocked = gate("legal")
    if blocked:
        return blocked
    case = api_scope(LegalCase).filter_by(id=case_id).first()
    if case is None:
        return api_error("No such case in this household.", 404, "not_found")
    from app.utils.activity_undo import fields_undo, snap_case

    before = fields_undo(case=snap_case(case))
    data = body()
    fields = {}
    if "title" in data:
        fields["title"] = as_str(data, "title", 500) or ""
    if "status" in data:
        fields["status"] = as_str(data, "status", 20) or ""
    if "summary" in data:
        fields["summary"] = as_str(data, "summary", 8000) or ""
    edit_case(case, fields)
    db.session.commit()
    note_activity(
        "bot.case.update",
        f"A bot updated {case.number}",
        target_table="legal_cases",
        target_id=case.id,
        old=before,
    )
    return ok({"case": _case_out(case)})


@bot_api_bp.route("/cases/<int:case_id>/followups", methods=["POST"])
@bot_api(BOT, write=True)
def cases_followup(case_id):
    from app.builddb.table_legal_cases import LegalCase
    from app.services.legal import add_followup
    from app.utils.crypto import decrypt_text

    blocked = gate("legal")
    if blocked:
        return blocked
    case = api_scope(LegalCase).filter_by(id=case_id).first()
    if case is None:
        return api_error("No such case in this household.", 404, "not_found")
    data = body()
    kind = (as_str(data, "kind", 20) or "note").lower()
    if kind == "file":
        return api_error(
            "Attach the photo or PDF to the record with POST /api/v1/records/<id>/files.",
            400,
            "bad_request",
        )
    fu, err = add_followup(
        case,
        user_id=getattr(api_user(), "id", None),
        kind=kind,
        title=as_str(data, "title", 500),
        body=as_str(data, "body", 8000),
        url=as_str(data, "url", 2000),
        email_from=as_str(data, "email_from", 200),
    )
    if err:
        db.session.rollback()
        return api_error(err, 400, "bad_request")
    db.session.commit()
    sent_mail = (fu.kind or "") == "email"
    note_activity(
        "bot.case.followup",
        f"A bot added a {fu.kind} on case {case.number}",
        target_table="legal_followups",
        target_id=fu.id,
        old=None if sent_mail else {"undo": "trash", "ids": [fu.id]},
        reversible=False if sent_mail else None,
    )
    return ok(
        {
            "followup": {
                "id": fu.id,
                "case_id": case.id,
                "kind": fu.kind,
                "title": decrypt_text(fu.title) or "",
                "body": decrypt_text(fu.body) or "",
                "url": decrypt_text(fu.url) or "",
            }
        },
        201,
    )


@bot_api_bp.route("/items/<int:item_id>/trips", methods=["POST"])
@bot_api(BOT, write=True)
def trips_add(item_id):
    from app.utils.item_log import end_trip, start_trip, trip_extra

    blocked = gate("scan", "maintain", "edit_meta")
    if blocked:
        return blocked
    item = _item(item_id, "vehicle")
    if item is None:
        return api_error("No such vehicle in this household.", 404, "not_found")
    from app.utils.activity_undo import living_snap, snap_log
    from app.utils.item_log import open_trip

    before_living = living_snap(item)
    open_row = open_trip(item)
    before_log = snap_log(open_row)
    data = body()
    action = (as_str(data, "action", 20) or "start").lower()
    if action in ("begin", "start", "open"):
        action = "start"
    elif action in ("end", "home", "done", "close", "finish"):
        action = "end"
    else:
        return api_error("action is start or end.", 400, "bad_request")
    happened = None
    if as_str(data, "happened_on", 20):
        try:
            happened = datetime.strptime(as_str(data, "happened_on", 10), "%Y-%m-%d").date()
        except ValueError:
            return api_error("happened_on must be YYYY-MM-DD.", 400, "bad_request")
    user_id = getattr(api_user(), "id", None)
    try:
        if action == "start":
            row, status = start_trip(
                item,
                user_id=user_id,
                start_miles=data.get("reading") or data.get("miles"),
                origin=as_str(data, "origin", 80) or as_str(data, "from", 80) or "",
                dest=as_str(data, "dest", 80) or as_str(data, "to", 80) or "",
                happened_on=happened,
                notes=as_str(data, "notes", 2000),
            )
            if status == "open":
                db.session.rollback()
                return api_error("A trip is already open on this vehicle.", 409, "conflict")
        else:
            row, _miles = end_trip(
                item,
                user_id=user_id,
                end_miles=data.get("reading") or data.get("miles"),
                happened_on=happened,
                notes=as_str(data, "notes", 2000),
            )
    except ValueError as exc:
        db.session.rollback()
        return api_error(str(exc), 400, "bad_request")
    db.session.commit()
    extra = trip_extra(row)
    if action == "start":
        trip_old = {
            "undo": "trash",
            "ids": [row.id],
            "living": before_living,
            "maintenance_id": row.maintenance_id,
        }
    else:
        trip_old = {"undo": "fields", "log": before_log, "living": before_living}
    note_activity(
        "bot.trip." + action,
        f"A bot {action}ed a trip on {item.name}",
        target_table="item_logs",
        target_id=row.id,
        item_id=item.id,
        old=trip_old if action == "start" or before_log else None,
    )
    return ok(
        {
            "trip": {
                "id": row.id,
                "item_id": item.id,
                "action": action,
                "reading": extra.get("end_miles") if action == "end" else extra.get("start_miles"),
                "origin": extra.get("origin") or "",
                "dest": extra.get("dest") or "",
            }
        },
        201,
    )


@bot_api_bp.route("/reminders/<int:reminder_id>", methods=["PATCH"])
@bot_api(BOT, write=True)
def reminders_update(reminder_id):
    from app.builddb.table_reminders import Reminder
    from app.utils.reminders_copy import REMINDER_TYPES, parse_recurrence

    blocked = gate("maintain")
    if blocked:
        return blocked
    row = api_scope(Reminder).filter_by(id=reminder_id).first()
    if row is None:
        return api_error("No such reminder in this household.", 404, "not_found")
    from app.utils.activity_undo import fields_undo, snap_reminder

    before = fields_undo(reminder=snap_reminder(row))
    data = body()
    if "title" in data:
        row.title = as_str(data, "title", 200) or row.title
    if "type" in data:
        rtype = (as_str(data, "type", 80) or "").lower()
        if rtype in {key for key, _label in REMINDER_TYPES}:
            row.type = rtype
    if "notes" in data:
        row.notes = as_str(data, "notes", 2000)
    if "item_id" in data:
        row.linked_item_id = as_int(data, "item_id")
    if "recurrence" in data:
        row.recurrence = parse_recurrence(as_str(data, "recurrence", 40))
    if "due_at" in data:
        raw_due = as_str(data, "due_at", 40)
        if raw_due:
            try:
                row.due_at = datetime.fromisoformat(raw_due.replace("Z", ""))
            except ValueError:
                db.session.rollback()
                return api_error("due_at must be a date-time.", 400, "bad_request")
    if "status" in data:
        status = (as_str(data, "status", 20) or "").lower()
        if status in ("open", "done"):
            row.status = status
    db.session.commit()
    note_activity(
        "bot.reminder.update",
        f"A bot updated the reminder {row.title}",
        target_table="reminders",
        target_id=row.id,
        old=before,
    )
    return ok(
        {
            "reminder": {
                "id": row.id,
                "title": row.title,
                "type": row.type,
                "due_at": iso(row.due_at),
                "status": row.status,
                "recurrence": row.recurrence or "",
            }
        }
    )
