"""Basket (store list) actions shared by the Basket page and Maya's API."""
from __future__ import annotations

from datetime import datetime

from app.builddb.builddb import db


def split_names(raw) -> list[str]:
    if isinstance(raw, (list, tuple)):
        parts = [str(p) for p in raw]
    else:
        parts = str(raw or "").replace("\n", ",").split(",")
    return [p.strip()[:200] for p in parts if p and p.strip()][:40]


def add_names(*, hid: int, user_id: int, raw, note=None, item_id=None, quantity=None, reason="want"):
    from app.builddb.table_grocery_list import GroceryListEntry

    rows = []
    for name in split_names(raw):
        row = GroceryListEntry(
            household_id=hid,
            name=name,
            status="open",
            added_reason=reason,
            note=(str(note).strip()[:120] or None) if note else None,
            created_by=user_id,
            item_id=item_id,
            quantity_needed=quantity,
        )
        db.session.add(row)
        rows.append(row)
    db.session.flush()
    return rows


def check_off(row, *, user_id, restock=True):
    """Got it: restock the matched item, close this and duplicate lines."""
    from app.builddb.table_grocery_list import GroceryListEntry
    from app.builddb.table_items import Item
    from app.utils.scan import apply_grocery_stock

    if restock and row.item_id:
        item = Item.query.filter_by(id=row.item_id, household_id=row.household_id).first()
        if item and item.grocery:
            apply_grocery_stock(item.grocery, item, "restock", row.quantity_needed or 1, user_id)
    row.status = "done"
    row.completed_at = datetime.utcnow()
    if row.item_id:
        extras = GroceryListEntry.query.filter_by(
            household_id=row.household_id, item_id=row.item_id, status="open"
        ).all()
        for extra in extras:
            extra.status = "done"
            extra.completed_at = row.completed_at


def reopen(row):
    row.status = "open"
    row.completed_at = None


def remove_entry(row, *, actor_id, via="ui"):
    from app.builddb.table_grocery_list import GroceryListEntry
    from app.utils import maya_store

    return maya_store.trash(
        hid=row.household_id,
        label=f"Basket: {row.name}",
        rows=[(GroceryListEntry, row)],
        actor_id=actor_id,
        via=via,
    )
