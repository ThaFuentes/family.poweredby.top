"""Maya's API: ``/api/v1/maya/...`` — the app's own backend, for one bot.

Same sign-in as the rest of the bot API (present -> exchange -> ``fos_s1_``
session, ``POST /api/v1/auth/reset`` to rotate the login key). On top of the
normal gates (HTTPS, live session, scope, rate limits, audit row) every route
here also requires:

1. the session's bot account is the household's designated **Maya** account;
2. the route's permission is switched on **right now** on the owner's Maya
   permissions page (read live from the DB on every call).

For the request, Maya's account is bound as ``current_user`` so the shared
services in ``app/services`` (the same functions the web pages call) see her
exactly like a signed-in person: ``scoped()`` filters her household, Happened
rows carry her name, and the result shows in the app as done by Maya.

Removals never hard-delete: rows go to the household recycle bin and files
to the archive outside the docroot. ``GET /api/v1/maya/capabilities`` lists
every route and whether its permission is on.
"""
from __future__ import annotations

import functools

from flask import g, request
from werkzeug.datastructures import MultiDict

from app.builddb.builddb import db
from app.routes.bot_api import BOT, bot_api_bp, limit_arg, offset_arg, ok, page
from app.utils import maya_perms
from app.utils.bot_api_auth import api_error, api_household_id, api_scope, api_user, audit, bot_api, body, iso

MAYA_ROUTES: list[dict] = []
TYPE_AREA = {"grocery": "inventory", "custom": "inventory", "vehicle": "vehicles", "tool": "tools", "house": "house"}


# ------------------------------------------------------------------ gate


def _deny(code: str, message: str, perm: str | None = None):
    user = api_user()
    sess = getattr(g, "bot_session", None)
    audit(
        event="maya.denied",
        status=403,
        outcome=code,
        user_id=getattr(user, "id", None),
        session_id=getattr(sess, "id", None),
        scope=getattr(sess, "scope", None),
        detail={"perm": perm} if perm else None,
    )
    g.bot_api_audited = True
    extra = {"permission": perm} if perm else {}
    return api_error(message, 403, code, **extra)


def need(perm: str):
    """Live check for a permission decided inside the view. None = allowed."""
    if perm in maya_perms.FORBIDDEN_IDS or perm not in maya_perms.CATALOG_BY_ID:
        return _deny("hard_limit", "That is never available to Maya.", perm)
    if not maya_perms.allowed(api_user(), perm):
        label = maya_perms.CATALOG_BY_ID[perm]["label"]
        return _deny("permission_off", f"The owner has '{label}' turned off for Maya.", perm)
    return None


def maya_route(rule: str, methods=("GET",), perm: str | None = None, what: str = "", write: bool | None = None):
    methods = tuple(m.upper() for m in methods)
    is_write = write if write is not None else any(m != "GET" for m in methods)
    for m in methods:
        MAYA_ROUTES.append({"method": m, "path": f"/api/v1/maya{rule}", "perm": perm, "what": what})

    def deco(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            user = api_user()
            if not maya_perms.is_maya(user):
                return _deny("not_maya", "This bot is not Maya. The owner picks Maya on the Maya permissions page.")
            if perm:
                blocked = need(perm)
                if blocked:
                    return blocked
            # Same identity the web pages use, for this request only (no cookie).
            g._login_user = user
            g.maya_perm = perm
            return fn(*args, **kwargs)

        gated = bot_api(BOT, write=is_write)(inner)
        bot_api_bp.add_url_rule(f"/maya{rule}", endpoint="maya_" + fn.__name__, view_func=gated, methods=list(methods))
        return fn

    return deco


def write_audit(outcome: str, target=None, target_id=None):
    user = api_user()
    sess = getattr(g, "bot_session", None)
    audit(
        event="maya.write",
        status=200,
        outcome=outcome[:40],
        user_id=user.id,
        key_id=getattr(g, "bot_key_id", None),
        session_id=getattr(sess, "id", None),
        scope=getattr(sess, "scope", None),
        detail={"perm": getattr(g, "maya_perm", None), "target": target, "id": target_id},
    )


def done(action: str, summary: str, *, target_table=None, target_id=None, item_id=None, detail=None,
         reversible=False):
    """Happened row as Maya + commit + one bot_api_audit row for the write."""
    from app.utils.activity import record

    record(
        action=action if action.startswith(("part.",)) else f"maya.{action}"[:40],
        summary=summary,
        target_table=target_table,
        target_id=target_id,
        item_id=item_id,
        new_json=detail if isinstance(detail, dict) else None,
        reversible=reversible,
        user_id=api_user().id,
    )
    db.session.commit()
    write_audit(action, target_table, target_id)


def who() -> str:
    u = api_user()
    return (getattr(u, "name", None) or getattr(u, "username", None) or "Maya").split()[0]


def form_of(data: dict) -> MultiDict:
    out = MultiDict()
    for k, v in (data or {}).items():
        if isinstance(v, list) and k != "tags":
            for one in v:
                out.add(k, "" if one is None else str(one))
        elif isinstance(v, list):
            out[k] = ", ".join(str(x) for x in v)
        elif isinstance(v, bool):
            out[k] = "1" if v else ""
        else:
            out[k] = "" if v is None else str(v)
    return out


def payload() -> dict:
    data = body()
    if not data and request.form:
        data = {k: request.form.get(k) for k in request.form.keys()}
    return data


def not_found():
    return api_error("Not found.", 404, "not_found")


def trashed(entry):
    return {"removed": True, "trash_id": entry.id, "restore": f"POST /api/v1/maya/trash/{entry.id}/restore"}


# ---------------------------------------------------------- serializers


def _item_json(item) -> dict:
    from app.routes.bot_api_content import _place_json, _tool_json
    from app.routes.bot_api_house import _inventory_json, _vehicle_json

    if item.item_type == "vehicle":
        out = _vehicle_json(item)
    elif item.item_type == "tool":
        out = _tool_json(item)
    elif item.item_type == "house":
        out = _place_json(item)
    else:
        out = _inventory_json(item)
    out = dict(out)
    out.setdefault("id", item.id)
    out["item_type"] = item.item_type
    out["removed"] = item.removed_at is not None
    return out


def _part_json(p) -> dict:
    return {
        "id": p.id, "item_id": p.vehicle_item_id, "system": p.system, "slot": p.slot, "name": p.name,
        "brand": p.brand, "spec": p.spec, "part_number": p.part_number, "model": p.model,
        "serial_number": p.serial_number, "asset_id": p.asset_id, "status": p.status,
        "is_current": bool(p.is_current),
        "installed_on": p.installed_on.isoformat() if p.installed_on else None,
        "installed_mileage": p.installed_mileage, "notes": p.notes, "source": p.source,
        "cost": str(p.cost) if p.cost is not None else None,
        "warranty_until": p.warranty_until.isoformat() if p.warranty_until else None,
    }


def _reminder_json(r) -> dict:
    return {
        "id": r.id, "title": r.title, "type": r.type, "status": r.status, "due_at": iso(r.due_at),
        "recurrence": r.recurrence, "notify_via": r.notify_via, "linked_item_id": r.linked_item_id,
        "notes": r.notes, "created_by": r.created_by,
    }


def _case_json(c, followups=False) -> dict:
    out = {"id": c.id, "number": c.number, "title": c.title, "status": c.status, "summary": c.summary,
           "updated_at": iso(c.updated_at)}
    if followups:
        out["followups"] = [
            {"id": f.id, "kind": f.kind, "title": f.title, "body": f.body, "url": f.url,
             "created_at": iso(f.created_at)} for f in (c.followups or [])
        ]
        out["records"] = [{"id": r.id, "title": r.title, "kind": r.kind} for r in (c.records or [])]
    return out


def _trash_json(t) -> dict:
    return {"id": t.id, "table": t.target_table, "target_id": t.target_id, "label": t.label,
            "via": t.via, "deleted_by": t.deleted_by, "deleted_at": iso(t.deleted_at),
            "restored_at": iso(t.restored_at), "purged_at": iso(t.purged_at),
            "files": len(t.files_json or [])}


def _version_json(v) -> dict:
    return {"id": v.id, "kind": v.kind, "row_id": v.row_id, "original_name": v.original_name,
            "mime": v.mime, "reason": v.reason, "created_at": iso(v.created_at),
            "restored_at": iso(v.restored_at)}


# -------------------------------------------------------------- discovery


@maya_route("/capabilities", perm=None, what="Every Maya route, its permission, and whether it is on now.")
def capabilities():
    user = api_user()
    caps = maya_perms.capabilities(user)
    state = {p["id"]: p["on"] for grp in caps["groups"] for p in grp["permissions"]}
    routes = [dict(r, allowed=(r["perm"] is None or bool(state.get(r["perm"])))) for r in MAYA_ROUTES]
    return ok({
        "maya": {"id": user.id, "username": user.username, "household": getattr(user.household, "handle", None)},
        "permissions": caps["groups"],
        "on": caps["on"],
        "hard_limits": caps["hard_limits"],
        "routes": routes,
        "checklist": "Read-only here. Only the owner can change it, on /maya-permissions in the app.",
        "dynamic_permissions": "Routes with perm null check <area>.<action> from the item type: grocery/custom=inventory, vehicle=vehicles, tool=tools, house=house.",
        "auth": {
            "present": "POST /api/v1/auth/present", "exchange": "POST /api/v1/auth/exchange",
            "revoke": "POST /api/v1/auth/revoke", "reset_login_key": "POST /api/v1/auth/reset",
        },
    })


# ------------------------------------------------------------- items


def _item(item_id, include_removed=False):
    from app.builddb.table_items import Item

    return api_scope(Item, include_removed=include_removed).filter_by(id=item_id).first()


def _area(item_type: str) -> str:
    return TYPE_AREA.get((item_type or "custom").lower(), "inventory")


@maya_route("/items", what="List items. ?type=grocery|custom|vehicle|tool|house, ?q=, ?removed=1. Needs <area>.read.")
def items_list():
    from app.builddb.table_items import Item

    kind = (request.args.get("type") or "grocery").strip().lower()
    if kind not in TYPE_AREA:
        return api_error("type must be grocery, custom, vehicle, tool or house.", 400, "bad_request")
    blocked = need(f"{_area(kind)}.read")
    if blocked:
        return blocked
    removed = request.args.get("removed") == "1"
    q = api_scope(Item, include_removed=removed).filter_by(item_type=kind)
    if removed:
        q = q.filter(Item.removed_at.isnot(None))
    term = (request.args.get("q") or "").strip()
    if term:
        q = q.filter(Item.name.ilike(f"%{term[:80]}%"))
    total = q.count()
    rows = q.order_by(Item.name.asc()).offset(offset_arg()).limit(limit_arg()).all()
    return ok({"items": [_item_json(i) for i in rows], **page(rows, total)})


@maya_route("/items/<int:item_id>", what="One item (any type). Needs <area>.read.")
def items_get(item_id):
    item = _item(item_id, include_removed=True)
    if item is None:
        return not_found()
    return need(f"{_area(item.item_type)}.read") or ok({"item": _item_json(item)})


@maya_route("/items", methods=("POST",),
            what="Add an item: {name, item_type, ...same fields as the Add form}. lookup=true runs product/VIN lookup. Needs <area>.create.")
def items_create():
    from app.services.items import create_item

    data = payload()
    blocked = need(f"{_area(data.get('item_type') or 'custom')}.create")
    if blocked:
        return blocked
    item, err, status = create_item(hid=api_household_id(), user_id=api_user().id, form=form_of(data),
                                    photo=None, lookup=bool(data.get("lookup")))
    if status == "invalid":
        return api_error(err, 400, "bad_request")
    if status == "forbidden":
        return api_error(err, 403, "forbidden")
    if status == "exists":
        return api_error(err, 409, "exists", item_id=item.id)
    done("item.add", f"{who()} added {item.name}", target_table="items", target_id=item.id, item_id=item.id)
    return ok({"item": _item_json(item)}, 201)


@maya_route("/items/<int:item_id>", methods=("PATCH",), what="Edit an item. Only the keys you send change. Needs <area>.edit.")
def items_edit(item_id):
    from app.services.items import edit_item, merged_form

    item = _item(item_id)
    if item is None:
        return not_found()
    blocked = need(f"{_area(item.item_type)}.edit")
    if blocked:
        return blocked
    data = payload()
    data.pop("item_type", None)
    err = edit_item(item, form_of(merged_form(item, data)), lookup=bool(data.get("lookup")))
    if err:
        db.session.rollback()
        return api_error(err, 409, "conflict")
    done("item.edit", f"{who()} edited {item.name}", target_table="items", target_id=item.id, item_id=item.id,
         detail={"fields": sorted(data.keys())[:40]})
    return ok({"item": _item_json(item)})


@maya_route("/items/<int:item_id>/stock", methods=("POST",), perm="inventory.stock",
            what="{action: consume|restock|plus|minus|need_more|freeze|fridge, amount, place}. Groceries only.")
def items_stock(item_id):
    from decimal import Decimal

    from app.services.items import stock_action

    item = _item(item_id)
    if item is None or item.item_type != "grocery" or not item.grocery:
        return api_error("Not a grocery in this house.", 404, "not_found")
    data = payload()
    result = stock_action(item, data.get("action") or "consume", data.get("amount") or 1,
                          user_id=api_user().id, place=(data.get("place") or None))
    db.session.commit()
    write_audit("grocery.stock", "items", item.id)
    clean = {}
    for k, v in (result or {}).items():
        if isinstance(v, Decimal):
            clean[k] = float(v)
        elif isinstance(v, (str, int, float, bool, type(None))):
            clean[k] = v
    return ok({"result": clean, "item": _item_json(item)})


@maya_route("/items/<int:item_id>/reading", methods=("POST",), perm="vehicles.reading",
            what="{reading}: odometer miles (vehicle) or hours (tool). Writes the log row.")
def items_reading(item_id):
    from app.services.items import set_reading

    item = _item(item_id)
    if item is None:
        return not_found()
    ok_, msg = set_reading(item, payload().get("reading"), user_id=api_user().id)
    if not ok_:
        return api_error(msg, 400, "bad_request")
    done("reading", f"{who()}: {msg}", target_table="items", target_id=item.id, item_id=item.id)
    return ok({"message": msg, "item": _item_json(item)})


@maya_route("/items/<int:item_id>", methods=("DELETE",), what="Remove an item (soft: Happened can put it back). Needs <area>.delete.")
def items_remove(item_id):
    from app.services.items import remove_item

    item = _item(item_id)
    if item is None:
        return not_found()
    blocked = need(f"{_area(item.item_type)}.delete")
    if blocked:
        return blocked
    remove_item(item, actor=api_user())
    db.session.commit()
    write_audit("item.remove", "items", item.id)
    return ok({"removed": True, "restore": f"POST /api/v1/maya/items/{item.id}/restore"})


@maya_route("/items/<int:item_id>/restore", methods=("POST",), what="Put a removed item back. Needs <area>.restore.")
def items_restore(item_id):
    from app.services.items import restore_item

    item = _item(item_id, include_removed=True)
    if item is None:
        return not_found()
    blocked = need(f"{_area(item.item_type)}.restore")
    if blocked:
        return blocked
    ok_, msg = restore_item(item, actor=api_user())
    if not ok_:
        return api_error(msg, 409, "conflict")
    write_audit("item.restore", "items", item.id)
    return ok({"restored": True, "message": msg, "item": _item_json(item)})


# --------------------------------------------------------------- logs


@maya_route("/items/<int:item_id>/logs", perm="logs.read", what="Log rows on a vehicle, tool or house.")
def logs_list(item_id):
    from app.builddb.table_item_logs import ItemLog
    from app.routes.bot_api_content import _log_json

    item = _item(item_id)
    if item is None:
        return not_found()
    q = api_scope(ItemLog).filter_by(item_id=item.id)
    total = q.count()
    rows = q.order_by(ItemLog.happened_on.desc(), ItemLog.id.desc()).offset(offset_arg()).limit(limit_arg()).all()
    return ok({"logs": [_log_json(r) for r in rows], **page(rows, total)})


@maya_route("/items/<int:item_id>/logs", methods=("POST",), perm="logs.create",
            what="{kind: miles|hours|fuel|repair|oil|note|code|..., happened_on, reading, gallons, cost, title, notes}.")
def logs_add(item_id):
    from app.builddb.table_item_logs import LOG_KINDS
    from app.routes.bot_api_content import _log_json
    from app.services.reminders import parse_due
    from app.utils.item_log import add_item_log
    from app.utils.log_apply import is_oil_kind

    item = _item(item_id)
    if item is None or item.item_type not in ("vehicle", "tool", "house"):
        return api_error("Logs are for vehicles, tools and the house.", 404, "not_found")
    data = payload()
    kind = (str(data.get("kind") or "note")).strip().lower()
    if kind not in LOG_KINDS and not is_oil_kind(kind):
        return api_error(f"kind must be one of {', '.join(LOG_KINDS)} or oil.", 400, "bad_request")
    day = parse_due(data.get("happened_on"))
    extra = {k: str(data[k])[:120] for k in ("station", "octane") if data.get(k)}
    row = add_item_log(
        item, kind=kind, user_id=api_user().id, reading=data.get("reading"),
        gallons=data.get("gallons"), cost=data.get("cost"), title=data.get("title"),
        notes=data.get("notes"), happened_on=day.date() if day else None, extra=extra or None,
    )
    if row is None:
        db.session.rollback()
        return api_error("That log row was not saved.", 400, "bad_request")
    done("log.add", f"{who()} logged {kind} on {item.name}", target_table="item_logs", target_id=row.id, item_id=item.id)
    return ok({"log": _log_json(row)}, 201)


@maya_route("/logs/<int:log_id>", methods=("DELETE",), perm="logs.delete", what="Remove a log row (recycle bin).")
def logs_remove(log_id):
    from app.builddb.table_item_logs import ItemLog
    from app.services.items import remove_log

    row = api_scope(ItemLog).filter_by(id=log_id).first()
    if row is None:
        return not_found()
    item_id = row.item_id
    entry = remove_log(row, actor_id=api_user().id, via="maya")
    done("log.remove", f"{who()} removed a log row", target_table="household_trash", target_id=entry.id, item_id=item_id)
    return ok(trashed(entry))


# -------------------------------------------------------------- parts


def _part(part_id):
    from app.builddb.table_vehicle_parts import VehiclePart

    return VehiclePart.query.filter_by(id=part_id, household_id=api_household_id()).first()


@maya_route("/items/<int:item_id>/parts", perm="parts.read", what="Parts on a vehicle or house slot. ?all=1 includes retired.")
def parts_list(item_id):
    from app.builddb.table_vehicle_parts import VehiclePart

    item = _item(item_id)
    if item is None:
        return not_found()
    q = VehiclePart.query.filter_by(household_id=api_household_id(), vehicle_item_id=item.id)
    if request.args.get("all") != "1":
        q = q.filter_by(is_current=True)
    rows = q.order_by(VehiclePart.system.asc(), VehiclePart.slot.asc()).all()
    return ok({"parts": [_part_json(p) for p in rows], "count": len(rows)})


@maya_route("/items/<int:item_id>/parts", methods=("POST",), perm="parts.create",
            what="{system, slot, name, brand, spec, status, installed_on, installed_mileage, part_number, model, serial_number, asset_id, source, cost, warranty_until, notes, replace_current}.")
def parts_add(item_id):
    item = _item(item_id)
    if item is None or item.item_type not in ("vehicle", "house"):
        return api_error("Parts go on a vehicle or the house.", 404, "not_found")
    data = payload()
    common = dict(
        hid=api_household_id(), vehicle_item_id=item.id, user_id=api_user().id,
        name=(data.get("name") or "").strip(), brand=data.get("brand"), spec=data.get("spec"),
        status=(str(data.get("status") or "installed")).strip().lower(),
        installed_on=data.get("installed_on"),
        source=(str(data.get("source") or "")).strip()[:200] or None, cost=data.get("cost"),
        warranty_until=data.get("warranty_until"), notes=(data.get("notes") or None),
        model=data.get("model"), serial_number=data.get("serial_number"), asset_id=data.get("asset_id"),
        part_number=data.get("part_number"),
        replace_current=bool(data.get("replace_current", item.item_type != "house")),
    )
    if not common["name"]:
        return api_error("name is required.", 400, "bad_request")
    if item.item_type == "house":
        from app.utils.house_systems import HOUSE_SLOTS, install_house_part
        from app.utils.vehicle_systems import valid_slot, valid_system

        system = valid_system(data.get("system"), HOUSE_SLOTS)
        row = install_house_part(system=system, slot=valid_slot(system, data.get("slot"), HOUSE_SLOTS),
                                 installed_mileage=data.get("installed_mileage"), **common)
    else:
        from app.utils.vehicle_systems import install_part, valid_slot, valid_system

        system = valid_system(data.get("system"))
        miles = data.get("installed_mileage") or (item.vehicle.current_mileage if item.vehicle else None)
        row = install_part(system=system, slot=valid_slot(system, data.get("slot")), installed_mileage=miles, **common)
    if row is None:
        db.session.rollback()
        return api_error("That part was not saved.", 400, "bad_request")
    done("part.add", f"{who()} put {row.name} on {item.name}", target_table="vehicle_parts", target_id=row.id,
         item_id=item.id, detail={"name": row.name, "system": row.system, "slot": row.slot}, reversible=True)
    return ok({"part": _part_json(row)}, 201)


@maya_route("/parts/<int:part_id>", methods=("PATCH",), perm="parts.edit", what="Edit a part. Only keys you send change.")
def parts_edit(part_id):
    from app.services.items import update_part

    row = _part(part_id)
    if row is None:
        return not_found()
    update_part(row, payload())
    done("part.edit", f"{who()} edited {row.name}", target_table="vehicle_parts", target_id=row.id, item_id=row.vehicle_item_id)
    return ok({"part": _part_json(row)})


@maya_route("/parts/<int:part_id>/retire", methods=("POST",), perm="parts.retire", what="Take a part off (Happened can put it back).")
def parts_retire(part_id):
    from app.services.items import retire_part

    row = _part(part_id)
    item = _item(row.vehicle_item_id) if row else None
    if row is None or item is None:
        return not_found()
    retire_part(item, row, actor=api_user())
    db.session.commit()
    write_audit("part.off", "vehicle_parts", row.id)
    return ok({"part": _part_json(row), "restore": f"POST /api/v1/maya/parts/{row.id}/restore"})


@maya_route("/parts/<int:part_id>/restore", methods=("POST",), perm="parts.restore", what="Put a retired part back on.")
def parts_restore(part_id):
    from app.services.items import restore_part

    row = _part(part_id)
    item = _item(row.vehicle_item_id) if row else None
    if row is None or item is None:
        return not_found()
    ok_, msg = restore_part(item, row, actor=api_user())
    if not ok_:
        return api_error(msg, 409, "conflict")
    write_audit("part.restore", "vehicle_parts", row.id)
    return ok({"part": _part_json(row), "message": msg})


# ------------------------------------------------------------- basket


def _basket(entry_id):
    from app.builddb.table_grocery_list import GroceryListEntry

    return api_scope(GroceryListEntry).filter_by(id=entry_id).first()


@maya_route("/basket", perm="basket.read", what="Basket lines. ?status=open|done|all.")
def basket_list():
    from app.builddb.table_grocery_list import GroceryListEntry
    from app.routes.bot_api_content import _basket_json

    status = (request.args.get("status") or "open").lower()
    q = api_scope(GroceryListEntry)
    if status in ("open", "done"):
        q = q.filter_by(status=status)
    total = q.count()
    rows = q.order_by(GroceryListEntry.created_at.desc()).offset(offset_arg()).limit(limit_arg()).all()
    return ok({"basket": [_basket_json(r) for r in rows], **page(rows, total)})


@maya_route("/basket", methods=("POST",), perm="basket.create", what="{names: [..] or 'a, b', note, item_id, quantity}.")
def basket_add():
    from app.routes.bot_api_content import _basket_json
    from app.services.basket import add_names

    data = payload()
    item_id = None
    if data.get("item_id") not in (None, ""):
        item = _item(int(data["item_id"])) if str(data["item_id"]).isdigit() else None
        if item is None:
            return api_error("item_id is not in this house.", 404, "not_found")
        item_id = item.id
    rows = add_names(hid=api_household_id(), user_id=api_user().id, raw=data.get("names") or data.get("name"),
                     note=data.get("note"), item_id=item_id, quantity=data.get("quantity"))
    if not rows:
        return api_error("names is required.", 400, "bad_request")
    done("basket.add", f"{who()} put {len(rows)} on the basket", target_table="grocery_list", target_id=rows[0].id)
    return ok({"added": [_basket_json(r) for r in rows]}, 201)


@maya_route("/basket/<int:entry_id>/check", methods=("POST",), perm="basket.check", what="Got it: check off (restocks a matched item).")
def basket_check(entry_id):
    from app.routes.bot_api_content import _basket_json
    from app.services.basket import check_off

    row = _basket(entry_id)
    if row is None:
        return not_found()
    check_off(row, user_id=api_user().id, restock=payload().get("restock", True) is not False)
    done("basket.check", f"{who()} got {row.name}", target_table="grocery_list", target_id=row.id)
    return ok({"line": _basket_json(row)})


@maya_route("/basket/<int:entry_id>/reopen", methods=("POST",), perm="basket.check", what="Put a checked-off line back on the list.")
def basket_reopen(entry_id):
    from app.routes.bot_api_content import _basket_json
    from app.services.basket import reopen

    row = _basket(entry_id)
    if row is None:
        return not_found()
    reopen(row)
    done("basket.reopen", f"{who()} put {row.name} back on the basket", target_table="grocery_list", target_id=row.id)
    return ok({"line": _basket_json(row)})


@maya_route("/basket/<int:entry_id>", methods=("DELETE",), perm="basket.delete", what="Take a line off (recycle bin; stock unchanged).")
def basket_remove(entry_id):
    from app.services.basket import remove_entry

    row = _basket(entry_id)
    if row is None:
        return not_found()
    name = row.name
    entry = remove_entry(row, actor_id=api_user().id, via="maya")
    done("basket.remove", f"{who()} took {name} off the basket", target_table="household_trash", target_id=entry.id)
    return ok(trashed(entry))


# ---------------------------------------------------------- reminders


def _reminder(rid):
    from app.builddb.table_reminders import Reminder

    return api_scope(Reminder).filter_by(id=rid).first()


@maya_route("/reminders", perm="reminders.read", what="Reminders / calendar items. ?status=open|done|all.")
def reminders_list():
    from app.builddb.table_reminders import Reminder

    status = (request.args.get("status") or "open").lower()
    q = api_scope(Reminder)
    if status in ("open", "done"):
        q = q.filter_by(status=status)
    total = q.count()
    rows = q.order_by(Reminder.due_at.asc()).offset(offset_arg()).limit(limit_arg()).all()
    return ok({"reminders": [_reminder_json(r) for r in rows], **page(rows, total)})


@maya_route("/reminders", methods=("POST",), perm="reminders.create",
            what="{title, type, due_at (ISO), recurrence, notify_via, linked_item_id, notes, announce}. Emails/calendar like the Due page.")
def reminders_add():
    from app.services.reminders import create_reminder

    data = payload()
    row, err = create_reminder(
        hid=api_household_id(), user_id=api_user().id, title=data.get("title"), rtype=data.get("type"),
        due_at=data.get("due_at"), linked_item_id=data.get("linked_item_id"),
        recurrence=data.get("recurrence"), notify_via=data.get("notify_via"), notes=data.get("notes"),
        announce=data.get("announce", True) is not False,
    )
    if err:
        return api_error(err, 400, "bad_request")
    done("reminder.add", f"{who()} added reminder {row.title}", target_table="reminders", target_id=row.id)
    return ok({"reminder": _reminder_json(row)}, 201)


@maya_route("/reminders/<int:rid>", methods=("PATCH",), perm="reminders.edit", what="Edit a reminder. Only keys you send change.")
def reminders_edit(rid):
    from app.services.reminders import update_reminder

    row = _reminder(rid)
    if row is None:
        return not_found()
    err = update_reminder(row, payload())
    if err:
        db.session.rollback()
        return api_error(err, 400, "bad_request")
    done("reminder.edit", f"{who()} edited reminder {row.title}", target_table="reminders", target_id=row.id)
    return ok({"reminder": _reminder_json(row)})


@maya_route("/reminders/<int:rid>/done", methods=("POST",), perm="reminders.complete", what="Mark done.")
def reminders_done(rid):
    from app.services.reminders import complete

    row = _reminder(rid)
    if row is None:
        return not_found()
    complete(row)
    done("reminder.done", f"{who()} checked off {row.title}", target_table="reminders", target_id=row.id)
    return ok({"reminder": _reminder_json(row)})


@maya_route("/reminders/<int:rid>/reopen", methods=("POST",), perm="reminders.complete", what="Open again.")
def reminders_reopen(rid):
    from app.services.reminders import reopen

    row = _reminder(rid)
    if row is None:
        return not_found()
    reopen(row)
    done("reminder.reopen", f"{who()} reopened {row.title}", target_table="reminders", target_id=row.id)
    return ok({"reminder": _reminder_json(row)})


@maya_route("/reminders/<int:rid>", methods=("DELETE",), perm="reminders.delete", what="Remove (recycle bin).")
def reminders_remove(rid):
    from app.services.reminders import remove_reminder

    row = _reminder(rid)
    if row is None:
        return not_found()
    title = row.title
    entry = remove_reminder(row, actor_id=api_user().id, via="maya")
    done("reminder.remove", f"{who()} removed reminder {title}", target_table="household_trash", target_id=entry.id)
    return ok(trashed(entry))


# -------------------------------------------------------------- notes


def _visible_note(note_id):
    from app.builddb.table_notes import Note
    from app.services.notes import can_see

    note = api_scope(Note).filter_by(id=note_id).first()
    return note if note is not None and can_see(note, api_user()) else None


@maya_route("/notes", perm="notes.read", what="Household notes + Maya's own. ?item_id=")
def notes_list():
    from sqlalchemy import or_

    from app.builddb.table_notes import Note
    from app.routes.bot_api_house import _note_json

    user = api_user()
    q = api_scope(Note).filter(or_(Note.visibility == "household", Note.user_id == user.id))
    if (request.args.get("item_id") or "").isdigit():
        q = q.filter_by(item_id=int(request.args["item_id"]))
    total = q.count()
    rows = q.order_by(Note.updated_at.desc()).offset(offset_arg()).limit(limit_arg()).all()
    return ok({"notes": [_note_json(n, with_files=False) for n in rows], **page(rows, total)})


@maya_route("/notes/<int:note_id>", perm="notes.read", what="One note with its files.")
def notes_get(note_id):
    from app.routes.bot_api_house import _note_json

    note = _visible_note(note_id)
    return ok({"note": _note_json(note)}) if note else not_found()


@maya_route("/notes", methods=("POST",), perm="notes.create", what="{title, body, visibility: personal|household (default household), item_id}.")
def notes_create():
    from app.routes.bot_api_house import _note_json
    from app.services.notes import create_note, resolve_item_id

    data = payload()
    note, err = create_note(hid=api_household_id(), user_id=api_user().id, title=data.get("title"),
                            body=data.get("body"), visibility=data.get("visibility") or "household",
                            item_id=resolve_item_id(data.get("item_id")))
    if err:
        return api_error(err, 400, "bad_request")
    done("note.add", f"{who()} wrote note {note.title}", target_table="notes", target_id=note.id, item_id=note.item_id)
    return ok({"note": _note_json(note)}, 201)


@maya_route("/notes/<int:note_id>", methods=("PATCH",), perm="notes.edit", what="Edit a note Maya may edit (hers, or any if her account is admin).")
def notes_edit(note_id):
    from app.routes.bot_api_house import _note_json
    from app.services.notes import KEEP, can_edit, resolve_item_id, update_note

    note = _visible_note(note_id)
    if note is None:
        return not_found()
    if not can_edit(note, api_user()):
        return api_error("Only the author or an admin can edit that note.", 403, "forbidden")
    data = payload()
    err = update_note(
        note,
        title=data["title"] if "title" in data else KEEP,
        body=data["body"] if "body" in data else KEEP,
        visibility=data["visibility"] if "visibility" in data else KEEP,
        item_id=resolve_item_id(data.get("item_id")) if "item_id" in data else KEEP,
    )
    if err:
        db.session.rollback()
        return api_error(err, 400, "bad_request")
    done("note.edit", f"{who()} edited note {note.title}", target_table="notes", target_id=note.id, item_id=note.item_id)
    return ok({"note": _note_json(note)})


@maya_route("/notes/<int:note_id>", methods=("DELETE",), perm="notes.delete", what="Remove a note and its files (recycle bin).")
def notes_remove(note_id):
    from app.services.notes import can_edit, remove_note

    note = _visible_note(note_id)
    if note is None:
        return not_found()
    if not can_edit(note, api_user()):
        return api_error("Only the author or an admin can remove that note.", 403, "forbidden")
    title = note.title
    entry = remove_note(note, actor_id=api_user().id, via="maya")
    done("note.remove", f"{who()} removed note {title}", target_table="household_trash", target_id=entry.id)
    return ok(trashed(entry))


# -------------------------------------------------------- files/photos

FILE_KINDS = ("note_file", "photo", "legal_file")


def _file_row(kind: str, row_id: int):
    from app.utils import maya_store

    if kind not in FILE_KINDS:
        return None
    model, _attr = maya_store.kind_model(kind)
    row = model.query.filter_by(id=row_id, household_id=api_household_id()).first()
    if row is None:
        return None
    if kind == "note_file" and _visible_note(row.note_id) is None:
        return None
    if kind == "legal_file":
        from app.utils.bot_api_access import account_can

        if not account_can("legal") or not maya_perms.allowed(api_user(), "records.read"):
            return None
    return row


def _file_json(kind, row) -> dict:
    return {"kind": kind, "id": row.id, "name": getattr(row, "original_name", None),
            "mime": getattr(row, "mime", None), "caption": getattr(row, "caption", None),
            "note_id": getattr(row, "note_id", None), "item_id": getattr(row, "item_id", None),
            "photo_kind": getattr(row, "kind", None) if kind == "photo" else None,
            "download": f"/api/v1/maya/files/{kind}/{row.id}"}


@maya_route("/items/<int:item_id>/photos", perm="files.read", what="Photos and receipts on an item.")
def photos_list(item_id):
    from app.builddb.table_photo_notes import PhotoNote

    item = _item(item_id)
    if item is None:
        return not_found()
    rows = api_scope(PhotoNote).filter_by(item_id=item.id).order_by(PhotoNote.id.desc()).all()
    return ok({"files": [_file_json("photo", r) for r in rows], "count": len(rows)})


@maya_route("/notes/<int:note_id>/files", perm="files.read", what="Files on a note.")
def note_files_list(note_id):
    note = _visible_note(note_id)
    if note is None:
        return not_found()
    return ok({"files": [_file_json("note_file", f) for f in (note.files or [])]})


@maya_route("/files/<kind>/<int:row_id>", perm="files.read", what="Download a file. kind = note_file | photo | legal_file.")
def files_get(kind, row_id):
    from app.utils import maya_store
    from app.utils.crypto import read_decrypted_file, send_bytes

    row = _file_row(kind, row_id)
    if row is None:
        return not_found()
    _m, attr = maya_store.kind_model(kind)
    path = maya_store._safe_upload_path(row.household_id, getattr(row, attr))
    if path is None or not path.is_file():
        return not_found()
    import mimetypes

    name = getattr(row, "original_name", None) or path.name.replace(".enc", "")
    mime = getattr(row, "mime", None) or mimetypes.guess_type(name)[0] or "application/octet-stream"
    data = read_decrypted_file(str(path))
    if not data:
        return not_found()
    return send_bytes(data, mime, name)


@maya_route("/notes/<int:note_id>/files", methods=("POST",), perm="files.upload",
            what="multipart 'file' (+ caption). JPG/PNG/WEBP/GIF/PDF, size-capped, EXIF stripped.")
def note_files_add(note_id):
    from app.routes.notes import save_note_file
    from app.services.notes import can_edit
    from app.utils import maya_store

    note = _visible_note(note_id)
    if note is None:
        return not_found()
    if not can_edit(note, api_user()):
        return api_error("Only the author or an admin can attach to that note.", 403, "forbidden")
    clean, err = maya_store.clean_upload(request.files.get("file"), allowed=maya_store.DOC_EXTS)
    if err:
        return api_error(err, 400, "bad_file")
    row = save_note_file(note, clean, api_user().id, request.form.get("caption"))
    if row is None:
        db.session.rollback()
        return api_error("That file was not saved.", 400, "bad_file")
    done("file.add", f"{who()} attached {row.original_name} to {note.title}", target_table="note_files", target_id=row.id)
    return ok({"file": _file_json("note_file", row)}, 201)


@maya_route("/items/<int:item_id>/photos", methods=("POST",), perm="files.upload",
            what="multipart 'file' (+ caption, kind photo|receipt|serial|connector, warranty_until). EXIF stripped.")
def photos_add(item_id):
    from app.routes.items import save_item_photo
    from app.utils import maya_store

    item = _item(item_id)
    if item is None:
        return not_found()
    clean, err = maya_store.clean_upload(request.files.get("file"), allowed=maya_store.PHOTO_EXTS)
    if err:
        return api_error(err, 400, "bad_file")
    row = save_item_photo(item, clean, request.form.get("caption"), api_user().id,
                          kind=request.form.get("kind"), warranty_until=request.form.get("warranty_until"))
    if row is None:
        db.session.rollback()
        return api_error("That picture was not saved.", 400, "bad_file")
    done("photo.add", f"{who()} added a photo to {item.name}", target_table="photo_notes", target_id=row.id, item_id=item.id)
    return ok({"file": _file_json("photo", row)}, 201)


@maya_route("/files/<kind>/<int:row_id>", methods=("PUT",), perm="files.replace",
            what="Replace the bytes (multipart 'file'). The old version is archived outside the docroot.")
def files_replace(kind, row_id):
    from app.utils import maya_store

    row = _file_row(kind, row_id)
    if row is None:
        return not_found()
    clean, err = maya_store.clean_upload(request.files.get("file"), allowed=maya_store.DOC_EXTS)
    if err:
        return api_error(err, 400, "bad_file")
    ok_, msg = maya_store.write_replacement(hid=row.household_id, kind=kind, row=row, upload=clean,
                                            actor_id=api_user().id)
    if not ok_:
        db.session.rollback()
        return api_error(msg, 400, "bad_file")
    done("file.replace", f"{who()} replaced a file", target_table=kind, target_id=row.id)
    return ok({"file": _file_json(kind, row), "versions": f"/api/v1/maya/files/{kind}/{row.id}/versions"})


@maya_route("/files/<kind>/<int:row_id>", methods=("DELETE",), perm="files.delete",
            what="Remove a file (row to recycle bin, bytes archived outside the docroot).")
def files_remove(kind, row_id):
    from app.services.items import remove_photo
    from app.services.notes import remove_note_file

    row = _file_row(kind, row_id)
    if row is None:
        return not_found()
    if kind == "note_file":
        entry = remove_note_file(row, actor_id=api_user().id, via="maya")
    elif kind == "photo":
        entry = remove_photo(row, actor_id=api_user().id, via="maya")
    else:
        from app.builddb.table_legal_files import LegalFile
        from app.utils import maya_store

        entry = maya_store.trash(hid=row.household_id, label=f"File: {row.original_name or row.id}",
                                 rows=[(LegalFile, row)], files=[row.stored_path], actor_id=api_user().id, via="maya")
    done("file.remove", f"{who()} removed a file", target_table="household_trash", target_id=entry.id)
    return ok(trashed(entry))


@maya_route("/files/<kind>/<int:row_id>/versions", perm="files.read", what="Archived old versions of a file.")
def files_versions(kind, row_id):
    from app.builddb.table_maya_bot import HouseholdFileVersion

    row = _file_row(kind, row_id)
    if row is None:
        return not_found()
    rows = (HouseholdFileVersion.query.filter_by(household_id=api_household_id(), kind=kind, row_id=row.id)
            .order_by(HouseholdFileVersion.id.desc()).all())
    return ok({"versions": [_version_json(v) for v in rows]})


@maya_route("/files/<kind>/<int:row_id>/versions/<int:version_id>/restore", methods=("POST",), perm="files.restore",
            what="Make an archived version current again (the current one is archived first).")
def files_version_restore(kind, row_id, version_id):
    from app.builddb.table_maya_bot import HouseholdFileVersion
    from app.utils import maya_store

    row = _file_row(kind, row_id)
    ver = HouseholdFileVersion.query.filter_by(id=version_id, household_id=api_household_id(), kind=kind,
                                               row_id=row_id).first()
    if row is None or ver is None:
        return not_found()
    ok_, msg = maya_store.restore_version(ver, row, actor_id=api_user().id)
    if not ok_:
        return api_error(msg, 409, "conflict")
    done("file.version_restore", f"{who()} restored an old file version", target_table=kind, target_id=row.id)
    return ok({"file": _file_json(kind, row), "message": msg})


# ------------------------------------------------------- records/cases


def _legal_ok():
    from app.utils.bot_api_access import account_can

    if not account_can("legal"):
        return api_error("This account cannot open Records.", 403, "forbidden")
    return None


def _record(record_id):
    from app.builddb.table_legal_records import LegalRecord

    return api_scope(LegalRecord).filter_by(id=record_id).first()


def _amount_guard(data: dict):
    if "amount" in data:
        return need("records.amounts")
    return None


@maya_route("/records", perm="records.read", what="Records (notices, tickets, letters).")
def records_list():
    from app.builddb.table_legal_records import LegalRecord
    from app.routes.bot_api_house import _record_json

    blocked = _legal_ok()
    if blocked:
        return blocked
    q = api_scope(LegalRecord)
    total = q.count()
    rows = q.order_by(LegalRecord.id.desc()).offset(offset_arg()).limit(limit_arg()).all()
    return ok({"records": [_record_json(r, with_files=False) for r in rows], **page(rows, total)})


@maya_route("/records/<int:record_id>", perm="records.read", what="One record with files.")
def records_get(record_id):
    from app.routes.bot_api_house import _record_json

    blocked = _legal_ok()
    if blocked:
        return blocked
    row = _record(record_id)
    return ok({"record": _record_json(row)}) if row else not_found()


@maya_route("/records", methods=("POST",), perm="records.create",
            what="{title, kind, status, agency, case_number, location, issued_on, due_on, body, outcome, kind_detail}. amount needs records.amounts.")
def records_create():
    from app.routes.bot_api_house import _record_json
    from app.services.legal import create_record, form_record

    data = payload()
    blocked = _legal_ok() or _amount_guard(data)
    if blocked:
        return blocked
    fields, err = form_record(form_of(data))
    if err:
        return api_error(err, 400, "bad_request")
    row = create_record(hid=api_household_id(), user_id=api_user().id, fields=fields)
    done("record.add", f"{who()} filed a record", target_table="legal_records", target_id=row.id)
    return ok({"record": _record_json(row)}, 201)


@maya_route("/records/<int:record_id>", methods=("PATCH",), perm="records.edit", what="Edit a record. Only keys you send change. amount needs records.amounts.")
def records_edit(record_id):
    from app.routes.bot_api_house import _record_json
    from app.services.legal import form_record, record_form_values, update_record

    data = payload()
    blocked = _legal_ok() or _amount_guard(data)
    if blocked:
        return blocked
    row = _record(record_id)
    if row is None:
        return not_found()
    merged = record_form_values(row)
    merged.update({k: ("" if v is None else str(v)) for k, v in data.items()})
    fields, err = form_record(form_of(merged), row)
    if err:
        return api_error(err, 400, "bad_request")
    update_record(row, fields)
    done("record.edit", f"{who()} edited a record", target_table="legal_records", target_id=row.id)
    return ok({"record": _record_json(row)})


@maya_route("/records/<int:record_id>", methods=("DELETE",), perm="records.delete", what="Remove a record and its files (recycle bin).")
def records_remove(record_id):
    from app.services.legal import remove_record

    blocked = _legal_ok()
    if blocked:
        return blocked
    row = _record(record_id)
    if row is None:
        return not_found()
    entry = remove_record(row, actor_id=api_user().id, via="maya")
    done("record.remove", f"{who()} removed a record", target_table="household_trash", target_id=entry.id)
    return ok(trashed(entry))


@maya_route("/records/<int:record_id>/files", methods=("POST",), perm="files.upload", what="Attach a photo/PDF to a record (needs records.edit too).")
def records_file_add(record_id):
    from app.routes.legal import save_legal_file
    from app.utils import maya_store

    blocked = _legal_ok() or need("records.edit")
    if blocked:
        return blocked
    row = _record(record_id)
    if row is None:
        return not_found()
    clean, err = maya_store.clean_upload(request.files.get("file"), allowed=maya_store.DOC_EXTS)
    if err:
        return api_error(err, 400, "bad_file")
    f = save_legal_file(row, clean, api_user().id, request.form.get("caption"))
    if f is None:
        db.session.rollback()
        return api_error("That file was not saved.", 400, "bad_file")
    done("record.file", f"{who()} attached a file to a record", target_table="legal_files", target_id=f.id)
    return ok({"file": _file_json("legal_file", f)}, 201)


def _case(case_id):
    from app.builddb.table_legal_cases import LegalCase

    return api_scope(LegalCase).filter_by(id=case_id).first()


@maya_route("/cases", perm="cases.read", what="Cases.")
def cases_list():
    from app.builddb.table_legal_cases import LegalCase

    blocked = _legal_ok()
    if blocked:
        return blocked
    rows = api_scope(LegalCase).order_by(LegalCase.number.desc()).limit(limit_arg()).all()
    return ok({"cases": [_case_json(c) for c in rows], "count": len(rows)})


@maya_route("/cases/<int:case_id>", perm="cases.read", what="One case with records and follow-ups.")
def cases_get(case_id):
    blocked = _legal_ok()
    if blocked:
        return blocked
    c = _case(case_id)
    return ok({"case": _case_json(c, followups=True)}) if c else not_found()


@maya_route("/cases", methods=("POST",), perm="cases.create", what="{title, summary, record_id}.")
def cases_create():
    from app.services.legal import open_case

    blocked = _legal_ok()
    if blocked:
        return blocked
    data = payload()
    rec = _record(int(data["record_id"])) if str(data.get("record_id") or "").isdigit() else None
    case, err = open_case(hid=api_household_id(), user_id=api_user().id, title=data.get("title"),
                          summary=data.get("summary"), record=rec)
    if err:
        return api_error(err, 400, "bad_request")
    done("case.add", f"{who()} opened a case", target_table="legal_cases", target_id=case.id)
    return ok({"case": _case_json(case)}, 201)


@maya_route("/cases/<int:case_id>", methods=("PATCH",), perm="cases.edit",
            what="{title, status: open|closed, summary, attach_record_id, detach_record_id}.")
def cases_edit(case_id):
    from app.services.legal import edit_case

    blocked = _legal_ok()
    if blocked:
        return blocked
    case = _case(case_id)
    if case is None:
        return not_found()
    data = payload()
    edit_case(case, data)
    if str(data.get("attach_record_id") or "").isdigit():
        rec = _record(int(data["attach_record_id"]))
        if rec is not None:
            rec.case_id = case.id
    if str(data.get("detach_record_id") or "").isdigit():
        rec = _record(int(data["detach_record_id"]))
        if rec is not None and rec.case_id == case.id:
            rec.case_id = None
    done("case.edit", f"{who()} updated a case", target_table="legal_cases", target_id=case.id)
    return ok({"case": _case_json(case, followups=True)})


@maya_route("/cases/<int:case_id>/followups", methods=("POST",), perm="cases.followup",
            what="{kind: note|link|email, title, body, url, email_from}.")
def cases_followup(case_id):
    from app.services.legal import add_followup

    blocked = _legal_ok()
    if blocked:
        return blocked
    case = _case(case_id)
    if case is None:
        return not_found()
    data = payload()
    if (data.get("kind") or "note") == "file":
        return api_error("Use kind note/link/email; attach files to a record.", 400, "bad_request")
    fu, err = add_followup(case, user_id=api_user().id, kind=data.get("kind"), title=data.get("title"),
                           body=data.get("body"), url=data.get("url"), email_from=data.get("email_from"))
    if err:
        return api_error(err, 400, "bad_request")
    done("case.followup", f"{who()} added a follow-up", target_table="legal_followups", target_id=fu.id)
    return ok({"followup_id": fu.id, "case": _case_json(case, followups=True)}, 201)


@maya_route("/followups/<int:followup_id>", methods=("DELETE",), perm="cases.delete", what="Remove a follow-up (recycle bin).")
def followups_remove(followup_id):
    from app.builddb.table_legal_followups import LegalFollowup
    from app.services.legal import remove_followup

    blocked = _legal_ok()
    if blocked:
        return blocked
    fu = api_scope(LegalFollowup).filter_by(id=followup_id).first()
    if fu is None:
        return not_found()
    entry = remove_followup(fu, actor_id=api_user().id, via="maya")
    done("case.followup_remove", f"{who()} removed a follow-up", target_table="household_trash", target_id=entry.id)
    return ok(trashed(entry))


# ------------------------------------------------------------ recycle bin


def _trash_entry(trash_id):
    from app.builddb.table_maya_bot import HouseholdTrash

    return HouseholdTrash.query.filter_by(id=trash_id, household_id=api_household_id()).first()


@maya_route("/trash", perm="trash.read", what="Recycle bin. ?state=live|restored|purged|all (default live).")
def trash_list():
    from app.builddb.table_maya_bot import HouseholdTrash

    state = (request.args.get("state") or "live").lower()
    q = HouseholdTrash.query.filter_by(household_id=api_household_id())
    if state == "live":
        q = q.filter(HouseholdTrash.restored_at.is_(None), HouseholdTrash.purged_at.is_(None))
    elif state == "restored":
        q = q.filter(HouseholdTrash.restored_at.isnot(None))
    elif state == "purged":
        q = q.filter(HouseholdTrash.purged_at.isnot(None))
    total = q.count()
    rows = q.order_by(HouseholdTrash.id.desc()).offset(offset_arg()).limit(limit_arg()).all()
    return ok({"trash": [_trash_json(t) for t in rows], **page(rows, total)})


@maya_route("/trash/<int:trash_id>/restore", methods=("POST",), perm="trash.restore", what="Put a removed row (and its files) back.")
def trash_restore(trash_id):
    from app.utils import maya_store

    entry = _trash_entry(trash_id)
    if entry is None:
        return not_found()
    ok_, msg = maya_store.restore(entry, actor_id=api_user().id)
    if not ok_:
        db.session.rollback()
        return api_error(msg, 409, "conflict")
    done("trash.restore", f"{who()} put back {entry.label}", target_table=entry.target_table, target_id=entry.target_id)
    return ok({"restored": True, "message": msg, "entry": _trash_json(entry)})


@maya_route("/trash/<int:trash_id>", methods=("DELETE",), perm="trash.purge",
            what="HIGH RISK. Permanently delete one recycle-bin entry and its archived files. Body {confirm: 'PURGE'}.")
def trash_purge(trash_id):
    from app.utils import maya_store

    entry = _trash_entry(trash_id)
    if entry is None:
        return not_found()
    if str(payload().get("confirm") or "") != "PURGE":
        return api_error("Send {\"confirm\": \"PURGE\"} to permanently delete.", 400, "confirm_required")
    label = entry.label
    ok_, msg = maya_store.purge(entry, actor_id=api_user().id)
    if not ok_:
        return api_error(msg, 409, "conflict")
    done("trash.purge", f"{who()} permanently deleted {label}", target_table="household_trash", target_id=trash_id)
    return ok({"purged": True, "message": msg})


# ------------------------------------------------------- activity/search


@maya_route("/activity", perm="activity.read", what="Happened (household activity). ?hours=48")
def activity_list():
    from app.utils.activity import recent

    try:
        hours = int(request.args.get("hours") or 48)
    except (TypeError, ValueError):
        hours = 48
    rows = recent(api_household_id(), limit=limit_arg(default=40, ceiling=80), hours=hours or None)
    for row in rows:
        row["when"] = iso(row.get("when"))
        row["reversed_at"] = iso(row.get("reversed_at"))
    return ok({"activity": rows, "count": len(rows), "window_hours": hours})


@maya_route("/activity/<int:aid>/undo", methods=("POST",), perm="activity.undo", what="The Put back button on Happened.")
def activity_undo(aid):
    from app.builddb.table_household_activity import HouseholdActivity
    from app.utils.activity import reverse_row

    row = HouseholdActivity.query.filter_by(id=aid, household_id=api_household_id()).first()
    if row is None:
        return not_found()
    if (row.action or "").startswith("maya.perms"):
        return _deny("hard_limit", "Maya cannot undo changes to her own permissions.")
    ok_, msg = reverse_row(row, by_id=api_user().id)
    if not ok_:
        db.session.rollback()
        return api_error(msg, 409, "conflict")
    write_audit("ok", "household_activity", aid)
    return ok({"undone": True, "message": msg})


@maya_route("/find", perm="search.read", what="Search. ?q=&scope=all|items|notes|parts|records")
def find():
    from app.utils.bot_api_access import account_can
    from app.utils.crypto import decrypt_text
    from app.utils.search import search_household

    q = (request.args.get("q") or "").strip()
    if not q:
        return api_error("q is required.", 400, "bad_request")
    hit = search_household(api_household_id(), q, user_id=int(api_user().id),
                           limit=min(limit_arg(default=20, ceiling=40), 40),
                           scope=(request.args.get("scope") or "all").strip().lower())
    legal_ok = account_can("legal") and maya_perms.allowed(api_user(), "records.read")
    return ok({
        "q": hit.get("q") or q,
        "items": [{"id": i.id, "name": i.name, "item_type": i.item_type} for i in hit.get("item_rows") or []],
        "notes": [{"id": n.id, "title": decrypt_text(n.title) or ""} for n in hit.get("note_rows") or []],
        "parts": [{"id": p.id, "name": p.name, "item_id": p.vehicle_item_id} for p in hit.get("part_rows") or []],
        "records": [{"id": r.id, "kind": r.kind, "title": decrypt_text(r.title) or ""}
                    for r in (hit.get("legal_rows") or [])] if legal_ok else [],
        "cases": [{"id": c.id, "number": c.number, "title": decrypt_text(c.title) or "", "status": c.status}
                  for c in (hit.get("case_rows") or [])] if legal_ok else [],
    })


@maya_route("/ask", perm="ask.read", what="Maya's own Ask turns. ?room=")
def ask_history():
    from app.builddb.table_ask_turns import AskTurn

    q = api_scope(AskTurn).filter_by(user_id=int(api_user().id)).order_by(AskTurn.id.desc())
    room = (request.args.get("room") or "").strip().lower()
    if room:
        q = q.filter_by(room=room[:20])
    total = q.count()
    rows = q.offset(offset_arg()).limit(limit_arg()).all()
    return ok({"turns": [{"id": t.id, "role": t.role, "room": t.room, "body": t.body or "",
                          "created_at": iso(t.created_at)} for t in rows], **page(rows, total)})


# --------------------------------------------------------------- people


def _person(user_id):
    from app.builddb.table_users import User

    return User.query.filter_by(id=user_id, household_id=api_household_id(), is_active=True).first()


def _not_self(target):
    if target is not None and int(target.id) == int(api_user().id):
        return _deny("hard_limit", "Maya cannot change her own account.")
    return None


@maya_route("/people", perm="people.read", what="Members: name, username, role, leader/bot flags. No emails, no keys.")
def people_list():
    from app.builddb.table_users import User

    rows = User.query.filter_by(household_id=api_household_id(), is_active=True).order_by(User.name.asc()).all()
    return ok({"people": [{"id": u.id, "name": u.name or "", "username": u.username or "", "role": u.role or "",
                           "is_leader": bool(u.is_leader), "is_bot": bool(u.is_bot),
                           "is_maya": maya_perms.is_maya(u)} for u in rows]})


@maya_route("/people/<int:user_id>/role", methods=("POST",), perm="people.role",
            what="HIGH RISK. {role: admin|member|child}. Never Maya herself, never leader flags.")
def people_role(user_id):
    from app.services.people import set_member_role

    target = _person(user_id)
    if target is None:
        return not_found()
    blocked = _not_self(target)
    if blocked:
        return blocked
    if target.is_leader:
        return _deny("hard_limit", "Maya cannot change a household leader's role.")
    old = target.role
    ok_, msg = set_member_role(target, payload().get("role"), actor=api_user())
    if not ok_:
        db.session.rollback()
        return api_error(msg, 400, "bad_request")
    done("user.role", f"{who()} set {target.name} to {target.role}", target_table="users", target_id=target.id,
         detail={"old": old, "new": target.role})
    return ok({"message": msg, "user_id": target.id, "role": target.role})


@maya_route("/people/<int:user_id>/remove", methods=("POST",), perm="people.remove",
            what="HIGH RISK. Take someone off People (Put back on Happened). Never Maya, never the last leader.")
def people_remove(user_id):
    from app.utils.people import remove_member

    target = _person(user_id)
    if target is None:
        return not_found()
    blocked = _not_self(target)
    if blocked:
        return blocked
    if target.is_leader:
        return _deny("hard_limit", "Maya cannot remove a household leader.")
    ok_, msg = remove_member(target, by=api_user())
    if not ok_:
        db.session.rollback()
        return api_error(msg, 400, "bad_request")
    write_audit("ok", "users", target.id)
    return ok({"message": msg, "undo": "POST /api/v1/maya/activity/<id>/undo (see /activity)"})


@maya_route("/people/<int:user_id>/reset-password", methods=("POST",), perm="people.reset_password",
            what="HIGH RISK. Email the person a reset link. Maya never sees the link or a password.")
def people_reset(user_id):
    from app.utils.passwords import issue_reset, send_reset_email

    target = _person(user_id)
    if target is None:
        return not_found()
    blocked = _not_self(target)
    if blocked:
        return _deny("hard_limit", "Maya rotates her own login key with POST /api/v1/auth/reset only.")
    if target.is_bot:
        return _deny("hard_limit", "Bot logins are managed by the owner on People.")
    token = issue_reset(target, requested_by=api_user().id)
    if not token:
        return api_error(f"{target.name} needs an email on this household first.", 400, "no_email")
    sent, msg = send_reset_email(target, token)
    done("user.reset_sent", f"{who()} sent {target.name} a password reset", target_table="users", target_id=target.id)
    return ok({"sent": bool(sent), "message": "Reset link handed to the mail server." if sent else msg})


# ------------------------------------------------------------- settings


@maya_route("/settings/household", methods=("PATCH",), perm="settings.household",
            what="HIGH RISK. {name, places: 'Kitchen, Garage, ...'}.")
def settings_household():
    from app.builddb.table_households import Household
    from app.services.people import rename_household
    from app.utils.places import save_places

    h = Household.query.get(api_household_id())
    data = payload()
    changed = {}
    if "name" in data:
        old = h.name
        ok_, msg = rename_household(h, data.get("name"))
        if not ok_:
            db.session.rollback()
            return api_error(msg, 400, "bad_request")
        changed["name"] = {"old": old, "new": h.name}
    if "places" in data:
        changed["places"] = save_places(h, data.get("places") or "")
    if not changed:
        return api_error("Send name and/or places.", 400, "bad_request")
    done("household.settings", f"{who()} changed household settings", target_table="households", target_id=h.id,
         detail=changed)
    return ok({"changed": changed})


@maya_route("/settings/reminders", methods=("PATCH",), perm="settings.reminders",
            what="HIGH RISK. {reminders_via: email|calendar|both}.")
def settings_reminders():
    from app.builddb.table_households import Household
    from app.utils.calendar import set_household_reminders_via

    h = Household.query.get(api_household_id())
    set_household_reminders_via(h, payload().get("reminders_via") or "both")
    done("household.reminders_via", f"{who()} changed reminder delivery", target_table="households", target_id=h.id)
    return ok({"reminders_via": (h.settings_json or {}).get("reminders_via")})


# --------------------------------------------------------------- vault


@maya_route("/vault", perm="vault.read", what="HIGH RISK. Vault card names/kinds only. Never passwords or numbers.")
def vault_meta():
    from app.routes.bot_api_vault import _card_meta, _may_see, _visible_entries

    rows = [e for e in _visible_entries().offset(offset_arg()).limit(limit_arg()).all() if _may_see(e)]
    cards = []
    for e in rows:
        meta = _card_meta(e)
        meta.pop("open_url", None)
        cards.append(meta)
    return ok({"entries": cards, "secrets": "never sent to Maya", **page(rows)})
