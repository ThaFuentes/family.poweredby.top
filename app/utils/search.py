"""Find anything in this household. Token AND across cars, house, tools, parts."""
from __future__ import annotations

from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload, selectinload

from app.builddb.table_grocery_items import GroceryItem
from app.builddb.table_items import Item
from app.builddb.table_legal_cases import LegalCase, case_label
from app.builddb.table_legal_records import LegalRecord
from app.builddb.table_item_logs import ItemLog
from app.builddb.table_notes import Note
from app.builddb.table_tools import Tool
from app.builddb.table_vehicle_parts import VehiclePart
from app.builddb.table_vehicles import Vehicle

SCOPES = ("all", "vehicles", "house", "tools", "groceries", "parts")


def _like(q: str) -> str:
    cleaned = (q or "").strip()[:80]
    if len(cleaned) < 2:
        return ""
    return "%" + cleaned.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"


def tokens(q: str) -> list[str]:
    raw = (q or "").strip()[:80]
    out = []
    for t in raw.lower().split():
        t = t.strip(".,#")
        if len(t) >= 2 and t not in out:
            out.append(t)
        if len(out) >= 6:
            break
    return out


def _token_clause(tok: str, columns):
    like = _like(tok)
    if not like:
        return None
    return or_(*[c.ilike(like, escape="\\") for c in columns])


def _all_tokens(toks: list[str], columns):
    parts = []
    for tok in toks:
        clause = _token_clause(tok, columns)
        if clause is not None:
            parts.append(clause)
    if not parts:
        return None
    return and_(*parts)


def _part_where(part, host) -> str:
    from app.utils.house_systems import HOUSE_SLOTS, house_system_label
    from app.utils.vehicle_systems import slot_label, system_label

    if host is not None and host.item_type == "house":
        sys = house_system_label(part.system)
        sl = slot_label(part.system, part.slot, HOUSE_SLOTS)
    else:
        sys = system_label(part.system)
        sl = slot_label(part.system, part.slot)
    bits = []
    if host is not None:
        bits.append(host.name)
        bits.append(host.item_type)
    bits.append(sys)
    bits.append(sl)
    return " · ".join(b for b in bits if b)


def search_household(household_id: int, q: str, *, user_id: int, limit: int = 40, scope: str = "all") -> dict:
    toks = tokens(q)
    scope = (scope or "all").strip().lower()
    if scope not in SCOPES:
        scope = "all"
    empty = {
        "q": (q or "").strip(),
        "scope": scope,
        "item_rows": [],
        "note_rows": [],
        "part_rows": [],
        "legal_rows": [],
        "case_rows": [],
        "part_hosts": {},
        "part_where": {},
        "code_rows": [],
    }
    if not toks:
        return empty

    item_cols = [
        Item.name,
        Item.barcode,
        Item.category,
        Item.item_type,
        GroceryItem.brand,
        GroceryItem.default_location,
        GroceryItem.size,
        Vehicle.make,
        Vehicle.model,
        Vehicle.vin,
        Vehicle.plate,
        Vehicle.trim,
        Tool.type,
        Tool.model,
        Tool.serial_number,
        Tool.asset_id,
        Tool.power_source,
    ]
    part_cols = [
        VehiclePart.name,
        VehiclePart.brand,
        VehiclePart.spec,
        VehiclePart.part_number,
        VehiclePart.serial_number,
        VehiclePart.model,
        VehiclePart.asset_id,
        VehiclePart.system,
        VehiclePart.slot,
        Item.name,
        Item.item_type,
    ]

    item_rows = []
    if scope != "parts":
        iq = (
            Item.query.outerjoin(GroceryItem, GroceryItem.item_id == Item.id)
            .outerjoin(Vehicle, Vehicle.item_id == Item.id)
            .outerjoin(Tool, Tool.item_id == Item.id)
            .filter(Item.household_id == household_id)
            .filter(Item.removed_at.is_(None))
        )
        if scope == "vehicles":
            iq = iq.filter(Item.item_type == "vehicle")
        elif scope == "house":
            iq = iq.filter(Item.item_type == "house")
        elif scope == "tools":
            iq = iq.filter(Item.item_type == "tool")
        elif scope == "groceries":
            iq = iq.filter(Item.item_type == "grocery")
        clause = _all_tokens(toks, item_cols)
        if clause is not None:
            item_rows = iq.filter(clause).order_by(Item.name.asc()).limit(limit).all()

    part_rows = []
    if scope in ("all", "parts", "vehicles", "house", "tools"):
        pq = (
            VehiclePart.query.join(Item, Item.id == VehiclePart.vehicle_item_id)
            .filter(VehiclePart.household_id == household_id)
        )
        if scope == "vehicles":
            pq = pq.filter(Item.item_type == "vehicle")
        elif scope == "house":
            pq = pq.filter(Item.item_type == "house")
        elif scope == "tools":
            pq = pq.filter(Item.item_type == "tool")
        clause = _all_tokens(toks, part_cols)
        if clause is not None:
            part_rows = pq.filter(clause).order_by(VehiclePart.name.asc()).limit(limit).all()

    host_ids = {p.vehicle_item_id for p in part_rows}
    hosts = {}
    if host_ids:
        hosts = {
            i.id: i
            for i in Item.query.filter(Item.id.in_(host_ids)).all()
        }
    part_where = {p.id: _part_where(p, hosts.get(p.vehicle_item_id)) for p in part_rows}

    code_rows = []
    if scope in ("all", "vehicles"):
        log_hits = (
            ItemLog.query.filter_by(household_id=household_id, kind="code")
            .order_by(ItemLog.happened_on.desc(), ItemLog.id.desc())
            .limit(200)
            .all()
        )
        for r in log_hits:
            extra = r.extra_data if isinstance(r.extra_data, dict) else {}
            blob = f"{r.title or ''} {extra.get('meaning') or ''} {extra.get('likely') or ''} {extra.get('code') or ''}".lower()
            if all(t in blob for t in toks):
                code_rows.append(r)
            if len(code_rows) >= 20:
                break

    needle = (q or "").strip().lower()
    notes, legal, case_rows = [], [], []
    if scope == "all":
        notes_all = (
            Note.query.options(selectinload(Note.files))
            .filter_by(household_id=household_id)
            .filter(or_(Note.visibility == "household", Note.user_id == user_id))
            .order_by(Note.updated_at.desc())
            .limit(200)
            .all()
        )
        for n in notes_all:
            blob = f"{n.title or ''} {n.body or ''}".lower()
            for f in n.files or []:
                blob += f" {f.original_name or ''} {f.caption or ''}"
            blob = blob.lower()
            if needle and all(t in blob for t in toks):
                notes.append(n)
            if len(notes) >= 20:
                break
        legal_all = (
            LegalRecord.query.options(joinedload(LegalRecord.case))
            .filter_by(household_id=household_id)
            .order_by(LegalRecord.issued_on.desc(), LegalRecord.id.desc())
            .limit(200)
            .all()
        )
        for r in legal_all:
            clabel = case_label(r.case) if getattr(r, "case", None) else ""
            blob = (
                f"{r.title or ''} {r.agency or ''} {r.case_number or ''} {r.location or ''} "
                f"{r.body or ''} {r.outcome or ''} {clabel} {r.kind or ''}"
            ).lower()
            extra = r.extra_data if isinstance(r.extra_data, dict) else {}
            blob += " " + str(extra.get("kind_detail") or "").lower()
            if needle and all(t in blob for t in toks):
                legal.append(r)
            if len(legal) >= 20:
                break
        case_all = (
            LegalCase.query.filter_by(household_id=household_id)
            .order_by(LegalCase.number.desc())
            .limit(80)
            .all()
        )
        for c in case_all:
            blob = f"{case_label(c)} {c.title or ''} {c.summary or ''} {c.status or ''}".lower()
            for fu in c.followups or []:
                blob += f" {fu.title or ''} {fu.body or ''} {fu.url or ''} {fu.kind or ''}"
            if needle and all(t in blob for t in toks):
                case_rows.append(c)
            if len(case_rows) >= 20:
                break

    return {
        "q": (q or "").strip(),
        "scope": scope,
        "item_rows": item_rows,
        "note_rows": notes,
        "part_rows": part_rows,
        "legal_rows": legal,
        "case_rows": case_rows,
        "part_hosts": hosts,
        "part_where": part_where,
        "code_rows": code_rows,
    }
