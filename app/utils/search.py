"""Find anything in this household. Parameterized ilike only."""
from __future__ import annotations

from sqlalchemy import or_

from app.builddb.table_grocery_items import GroceryItem
from app.builddb.table_items import Item
from app.builddb.table_legal_records import LegalRecord
from app.builddb.table_notes import Note
from app.builddb.table_vehicle_parts import VehiclePart


def _like(q: str) -> str:
    cleaned = (q or "").strip()[:80]
    if len(cleaned) < 2:
        return ""
    return "%" + cleaned.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"


def search_household(household_id: int, q: str, *, user_id: int, limit: int = 40) -> dict:
    like = _like(q)
    if not like:
        return {
            "q": (q or "").strip(),
            "item_rows": [],
            "note_rows": [],
            "part_rows": [],
            "legal_rows": [],
        }

    esc = {"escape": "\\"}
    items = (
        Item.query.outerjoin(GroceryItem, GroceryItem.item_id == Item.id)
        .filter(Item.household_id == household_id)
        .filter(Item.removed_at.is_(None))
        .filter(
            or_(
                Item.name.ilike(like, **esc),
                Item.barcode.ilike(like, **esc),
                Item.category.ilike(like, **esc),
                GroceryItem.brand.ilike(like, **esc),
                GroceryItem.default_location.ilike(like, **esc),
            )
        )
        .order_by(Item.name.asc())
        .limit(limit)
        .all()
    )
    needle = (q or "").strip().lower()
    notes_all = (
        Note.query.filter_by(household_id=household_id)
        .filter(or_(Note.visibility == "household", Note.user_id == user_id))
        .order_by(Note.updated_at.desc())
        .limit(200)
        .all()
    )
    notes = []
    for n in notes_all:
        blob = f"{n.title or ''} {n.body or ''}".lower()
        if needle and needle in blob:
            notes.append(n)
        if len(notes) >= 20:
            break
    parts = (
        VehiclePart.query.filter_by(household_id=household_id)
        .filter(
            or_(
                VehiclePart.name.ilike(like, **esc),
                VehiclePart.brand.ilike(like, **esc),
                VehiclePart.spec.ilike(like, **esc),
                VehiclePart.part_number.ilike(like, **esc),
            )
        )
        .order_by(VehiclePart.name.asc())
        .limit(20)
        .all()
    )
    legal_all = (
        LegalRecord.query.filter_by(household_id=household_id)
        .order_by(LegalRecord.issued_on.desc(), LegalRecord.id.desc())
        .limit(200)
        .all()
    )
    legal = []
    for r in legal_all:
        blob = f"{r.title or ''} {r.agency or ''} {r.case_number or ''} {r.location or ''} {r.body or ''} {r.outcome or ''}".lower()
        if needle and needle in blob:
            legal.append(r)
        if len(legal) >= 20:
            break
    return {
        "q": (q or "").strip(),
        "item_rows": items,
        "note_rows": notes,
        "part_rows": parts,
        "legal_rows": legal,
    }
