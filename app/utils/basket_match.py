"""Match a scanned product to a basket row that was added by name (no barcode yet)."""
from __future__ import annotations

import re
from datetime import datetime

from app.builddb.builddb import db
from app.builddb.table_grocery_list import GroceryListEntry
from app.builddb.table_items import Item

_STOP = {
    "the",
    "a",
    "an",
    "of",
    "and",
    "or",
    "from",
    "for",
    "with",
    "in",
    "at",
    "to",
    "on",
    "club",
    "store",
    "pack",
    "count",
}
_TOKEN = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    out = []
    for t in _TOKEN.findall((text or "").lower()):
        if t in _STOP or len(t) < 3:
            continue
        if t not in out:
            out.append(t)
    return out


def score_names(want: str, product: str, brand: str = "") -> float:
    need = tokens(want)
    have = tokens(" ".join(x for x in (product, brand) if x))
    if not need or not have:
        return 0.0
    hits = 0
    for t in need:
        if t in have:
            hits += 1
            continue
        if len(t) >= 4 and any(t in h or h in t for h in have if len(h) >= 4):
            hits += 1
    return hits / len(need)


def _open_unlinked(household_id: int):
    return (
        GroceryListEntry.query.filter_by(household_id=household_id, status="open")
        .filter(GroceryListEntry.item_id.is_(None))
        .order_by(GroceryListEntry.id.desc())
        .all()
    )


def _pack(row, score: float, *, used_ai: bool = False) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "store": (row.note or "").strip(),
        "score": round(score, 2),
        "used_ai": used_ai,
    }


def _ai_pick(household_id: int, product: str, brand: str, rows) -> GroceryListEntry | None:
    if not rows:
        return None
    try:
        from app.builddb.table_households import Household
        from app.utils.ai import complete_json
        from app.utils.household_ai import household_config

        household = Household.query.get(household_id)
        cfg = household_config(household)
        if not cfg.get("has_key") or not cfg.get("enabled"):
            return None
        lines = []
        by_id = {}
        for r in rows[:24]:
            by_id[r.id] = r
            store = (r.note or "").strip()
            lines.append(f"{r.id}: {r.name}" + (f" ({store})" if store else ""))
        blob = "\n".join(lines)
        prompt = (
            f"Scanned: {product}"
            + (f" · brand {brand}" if brand else "")
            + "\nOpen basket rows (id: nickname):\n"
            + blob
            + '\nPick the basket nickname this scan fulfills. JSON only: {"id": 12} or {"id": null} if none.'
        )
        ok, data = complete_json(
            prompt,
            system=(
                "You match a scanned grocery to a shopping-list nickname. "
                "French vanilla coffee creamer matches coffee creamer. "
                "Toilet paper does not match paper towels. "
                "If it is not on the list, id is null."
            ),
            max_tokens=80,
            timeout=8,
            household=household,
            household_only=True,
        )
        if not ok or not isinstance(data, dict):
            return None
        raw = data.get("id")
        if raw is None or raw == "" or str(raw).lower() in ("null", "none"):
            return None
        if not str(raw).isdigit():
            return None
        return by_id.get(int(raw))
    except Exception:
        return None


def suggest_for_item(household_id: int, item, *, min_score: float = 0.66) -> dict | None:
    name = getattr(item, "name", None) or ""
    brand = ""
    g = getattr(item, "grocery", None)
    if g is not None:
        brand = getattr(g, "brand", None) or ""
    rows = _open_unlinked(household_id)
    if not rows:
        return None
    ranked = []
    for row in rows:
        s = score_names(row.name, name, brand)
        if s >= min_score:
            ranked.append((s, row))
    ranked.sort(key=lambda x: x[0], reverse=True)
    if ranked and ranked[0][0] >= 0.85:
        best_s, best = ranked[0]
        hit = _pack(best, best_s)
        hit["also"] = [_pack(r, s) for s, r in ranked[1:4]]
        return hit
    ai_row = _ai_pick(household_id, name, brand, rows)
    if ai_row is not None:
        s = score_names(ai_row.name, name, brand)
        also = [_pack(r, sc) for sc, r in ranked if r.id != ai_row.id][:3]
        hit = _pack(ai_row, max(s, 0.7), used_ai=True)
        hit["also"] = also
        return hit
    if not ranked:
        return None
    best_s, best = ranked[0]
    hit = _pack(best, best_s)
    hit["also"] = [_pack(r, s) for s, r in ranked[1:4]]
    return hit


def suggest_for_text(household_id: int, text: str, *, min_score: float = 0.5) -> list[dict]:
    ranked = []
    for row in _open_unlinked(household_id):
        s = score_names(row.name, text, "")
        if s >= min_score:
            ranked.append(
                {
                    "id": row.id,
                    "name": row.name,
                    "store": (row.note or "").strip(),
                    "score": round(s, 2),
                }
            )
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:8]


def apply_match(row: GroceryListEntry, item: Item, user_id, *, restock: bool = True) -> dict:
    from app.utils.scan import apply_grocery_stock

    if int(getattr(item, "household_id", 0) or 0) != int(row.household_id):
        return {"ok": False, "error": "That item is not in this house."}
    wanted = row.name
    store = (row.note or "").strip()
    row.item_id = item.id
    if item.name and (not row.name or len(item.name) > len(row.name)):
        row.name = item.name[:200]
    if restock and item.grocery:
        apply_grocery_stock(
            item.grocery,
            item,
            "restock",
            row.quantity_needed or 1,
            user_id,
        )
    row.status = "done"
    row.completed_at = datetime.utcnow()
    extras = GroceryListEntry.query.filter_by(
        household_id=row.household_id, item_id=item.id, status="open"
    ).all()
    for extra in extras:
        if extra.id == row.id:
            continue
        extra.status = "done"
        extra.completed_at = row.completed_at
    db.session.flush()
    msg = f"{item.name} is the {wanted} on the basket."
    if store:
        msg = f"{item.name} is the {wanted} from {store}."
    msg += " Off the list."
    return {
        "ok": True,
        "entry_id": row.id,
        "item_id": item.id,
        "name": item.name,
        "matched": row.name,
        "store": store,
        "href": "/groceries/list",
        "message": msg,
    }
