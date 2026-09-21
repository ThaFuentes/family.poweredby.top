"""Dated packs on a grocery row. Two gallons of milk can expire on two days."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm.attributes import flag_modified


def parse_day(raw) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    s = str(raw).strip()[:10]
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _qty(val, default="0") -> Decimal:
    try:
        q = Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError):
        try:
            q = Decimal(default)
        except Exception:
            return Decimal("0")
    if q < 0:
        return Decimal("0")
    return q


def _qty_json(q: Decimal):
    q = _qty(q)
    if q == q.to_integral_value():
        return int(q)
    return float(q)


def _place(raw) -> str | None:
    name = " ".join(str(raw or "").strip().split())[:80]
    return name or None


def extra_of(g) -> dict:
    raw = getattr(g, "extra_data", None) if g is not None else None
    return dict(raw) if isinstance(raw, dict) else {}


def _save(g, extra: dict) -> None:
    g.extra_data = extra or None
    try:
        flag_modified(g, "extra_data")
    except Exception:
        pass


def on_hand(g) -> Decimal:
    return _qty(getattr(g, "quantity", 0) if g is not None else 0)


def _lot_from_raw(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    q = _qty(raw.get("qty") or raw.get("quantity") or raw.get("amount") or 0)
    day = parse_day(raw.get("expires_on") or raw.get("expires") or raw.get("date"))
    if q <= 0 or day is None:
        return None
    out = {"qty": q, "expires_on": day.isoformat()}
    place = _place(raw.get("place") or raw.get("location") or raw.get("where"))
    if place:
        out["place"] = place
    if raw.get("guessed"):
        out["guessed"] = True
    return out


def lots_list(g) -> list[dict]:
    """Dated packs. Legacy single expires_on becomes one pack covering on-hand."""
    extra = extra_of(g)
    raw = extra.get("lots")
    out = []
    if isinstance(raw, list):
        for row in raw:
            lot = _lot_from_raw(row)
            if lot:
                out.append(lot)
    if out:
        return out
    day = parse_day(extra.get("expires_on"))
    if day is None:
        return []
    q = on_hand(g)
    if q <= 0:
        q = Decimal("1")
    lot = {"qty": q, "expires_on": day.isoformat()}
    if extra.get("expires_guessed"):
        lot["guessed"] = True
    return [lot]


def dated_sum(g) -> Decimal:
    total = Decimal("0")
    for lot in lots_list(g):
        total += _qty(lot.get("qty"))
    return total


def undated_qty(g) -> Decimal:
    left = on_hand(g) - dated_sum(g)
    return left if left > 0 else Decimal("0")


def has_manual_lot(g) -> bool:
    return any(not lot.get("guessed") for lot in lots_list(g))


def soonest(g) -> date | None:
    days = []
    for lot in lots_list(g):
        day = parse_day(lot.get("expires_on"))
        if day:
            days.append(day)
    return min(days) if days else None


def is_guessed(g) -> bool:
    lots = lots_list(g)
    if not lots:
        extra = extra_of(g)
        return bool(extra.get("expires_guessed")) and bool(extra.get("expires_on"))
    return all(bool(lot.get("guessed")) for lot in lots)


def write_lots(g, lots) -> None:
    extra = extra_of(g)
    cleaned = []
    for row in lots or []:
        lot = _lot_from_raw(row)
        if lot:
            row = {
                "qty": _qty_json(_qty(lot["qty"])),
                "expires_on": lot["expires_on"],
            }
            if lot.get("place"):
                row["place"] = lot["place"]
            if lot.get("guessed"):
                row["guessed"] = True
            cleaned.append(row)
    if cleaned:
        extra["lots"] = cleaned
        days = [parse_day(x["expires_on"]) for x in cleaned]
        days = [d for d in days if d]
        extra["expires_on"] = min(days).isoformat() if days else extra.get("expires_on")
        extra["expires_guessed"] = bool(cleaned) and all(x.get("guessed") for x in cleaned)
        extra.pop("expires_cleared", None)
    else:
        extra.pop("lots", None)
        extra.pop("expires_on", None)
        extra.pop("expires_guessed", None)
    extra.pop("expires_days", None)
    _save(g, extra)


def sync_expires_on(g) -> str | None:
    lots = lots_list(g)
    if not lots:
        extra = extra_of(g)
        extra.pop("expires_on", None)
        extra.pop("expires_guessed", None)
        extra.pop("lots", None)
        _save(g, extra)
        return None
    write_lots(g, lots)
    extra = extra_of(g)
    return extra.get("expires_on")


def align_quantity(g, prev, new) -> None:
    """When count drops, use the soonest pack first. Count up leaves leftover undated."""
    prev_q = _qty(prev)
    new_q = _qty(new)
    take = prev_q - new_q
    if take <= 0:
        return
    lots = sorted(lots_list(g), key=lambda row: parse_day(row.get("expires_on")) or date.max)
    left = take
    kept = []
    for lot in lots:
        q = _qty(lot.get("qty"))
        if left <= 0:
            kept.append(lot)
            continue
        if q <= left:
            left -= q
            continue
        lot = dict(lot)
        lot["qty"] = q - left
        left = Decimal("0")
        kept.append(lot)
    write_lots(g, kept)


def apply_guess(g, day: date, *, force: bool = False) -> str | None:
    """Typical use-by on leftover undated packs. Never overwrites a date someone typed."""
    extra = extra_of(g)
    if day is None:
        return extra.get("expires_on")
    if extra.get("expires_cleared") and not force:
        return extra.get("expires_on")
    lots = lots_list(g)
    manual = [lot for lot in lots if not lot.get("guessed")]
    leftover = undated_qty(g)
    if force:
        for lot in lots:
            if lot.get("guessed"):
                leftover += _qty(lot.get("qty"))
        kept = list(manual)
        if leftover > 0:
            kept.append({"qty": leftover, "expires_on": day.isoformat(), "guessed": True})
        write_lots(g, kept)
        return extra_of(g).get("expires_on")
    if leftover > 0:
        lots = lots + [{"qty": leftover, "expires_on": day.isoformat(), "guessed": True}]
        write_lots(g, lots)
        return extra_of(g).get("expires_on")
    if lots:
        write_lots(g, lots)
        return extra_of(g).get("expires_on")
    q = on_hand(g)
    if q <= 0:
        return extra.get("expires_on")
    write_lots(g, [{"qty": q, "expires_on": day.isoformat(), "guessed": True}])
    return day.isoformat()


def apply_single_date(g, raw) -> str | None:
    """One typed date from Edit — covers leftover undated, or all stock if nothing is dated yet."""
    day = parse_day(raw)
    if day is None:
        return extra_of(g).get("expires_on")
    lots = [lot for lot in lots_list(g) if not lot.get("guessed")]
    leftover = undated_qty(g)
    guessed = [lot for lot in lots_list(g) if lot.get("guessed")]
    for lot in guessed:
        leftover += _qty(lot.get("qty"))
    if leftover <= 0:
        leftover = on_hand(g) if not lots else Decimal("0")
    if leftover > 0:
        lots.append({"qty": leftover, "expires_on": day.isoformat()})
    elif not lots:
        lots = [{"qty": on_hand(g) or Decimal("1"), "expires_on": day.isoformat()}]
    write_lots(g, lots)
    return day.isoformat()


def apply_partial(g, rows) -> list[dict]:
    """Only rows with a date are written. Blank rows keep whatever was already there."""
    existing = [dict(lot) for lot in lots_list(g) if not lot.get("guessed")]
    result = list(existing)
    filled = False
    extras = []
    for i, row in enumerate(rows or []):
        if not isinstance(row, dict):
            continue
        day = parse_day(row.get("expires_on") or row.get("expires") or row.get("date"))
        if day is None:
            continue
        q = _qty(row.get("qty") or row.get("quantity") or row.get("amount") or 0)
        if q <= 0:
            q = Decimal("1")
        lot = {"qty": q, "expires_on": day.isoformat()}
        place = _place(row.get("place") or row.get("location") or row.get("where"))
        if place:
            lot["place"] = place
        elif i < len(result) and result[i].get("place"):
            lot["place"] = result[i]["place"]
        filled = True
        if i < len(result):
            result[i] = lot
        else:
            extras.append(lot)
    if not filled:
        return lots_list(g)
    write_lots(g, result + extras)
    return lots_list(g)


def parse_form_rows(form) -> list[dict]:
    """qty[] + place[] + expires_on[] from the use-by sheet. Parallel lists."""
    if form is None:
        return []
    qtys = list(form.getlist("qty") or [])
    days = list(form.getlist("expires_on") or [])
    places = list(form.getlist("place") or [])
    n = max(len(qtys), len(days), len(places))
    rows = []
    for i in range(n):
        rows.append(
            {
                "qty": qtys[i] if i < len(qtys) else "",
                "expires_on": days[i] if i < len(days) else "",
                "place": places[i] if i < len(places) else "",
            }
        )
    return rows


def sheet_rows(g, *, max_split: int = 8) -> list[dict]:
    """Rows for the editor: each dated pack, then empty slots for leftover units."""
    rows = []
    for lot in lots_list(g):
        if lot.get("guessed"):
            continue
        rows.append(
            {
                "qty": _qty_json(_qty(lot.get("qty"))),
                "expires_on": lot.get("expires_on") or "",
                "place": lot.get("place") or (getattr(g, "default_location", None) or ""),
                "hint": None,
            }
        )
    leftover = undated_qty(g)
    for lot in lots_list(g):
        if lot.get("guessed"):
            leftover += _qty(lot.get("qty"))
    leftover = leftover if leftover > 0 else Decimal("0")
    typical = None
    extra = extra_of(g)
    if extra.get("expires_guessed"):
        typical = extra.get("expires_on")
    else:
        for lot in lots_list(g):
            if lot.get("guessed"):
                typical = lot.get("expires_on")
                break
    if leftover > 0:
        whole = leftover == leftover.to_integral_value()
        n = int(leftover) if whole else 0
        here = (getattr(g, "default_location", None) or "").strip()
        if whole and 1 <= n <= max_split:
            for _ in range(n):
                rows.append({"qty": 1, "expires_on": "", "place": here, "hint": typical})
        else:
            rows.append(
                {"qty": _qty_json(leftover), "expires_on": "", "place": here, "hint": typical}
            )
    rows.append({"qty": "", "expires_on": "", "place": (getattr(g, "default_location", None) or ""), "hint": None})
    return rows


def summary_bits(g) -> list[str]:
    """Short chips: '1 by Oct 1', '1 no date'."""
    bits = []
    for lot in sorted(lots_list(g), key=lambda row: parse_day(row.get("expires_on")) or date.max):
        q = _qty(lot.get("qty"))
        day = parse_day(lot.get("expires_on"))
        if q <= 0 or day is None:
            continue
        q_s = str(int(q)) if q == q.to_integral_value() else str(q)
        label = day.strftime("%b ") + str(day.day)
        place = (lot.get("place") or "").strip()
        if place:
            bits.append(f"{q_s} {place} by {label}")
        else:
            bits.append(f"{q_s} by {label}")
    left = undated_qty(g)
    if left > 0:
        q_s = str(int(left)) if left == left.to_integral_value() else str(left)
        bits.append(f"{q_s} no date")
    return bits


def summary_line(g) -> str:
    return " · ".join(summary_bits(g))


def payload(g) -> dict:
    lots = lots_list(g)
    day = soonest(g)
    return {
        "lots": [
            {
                "qty": _qty_json(_qty(x.get("qty"))),
                "expires_on": x.get("expires_on"),
                "place": x.get("place") or "",
                "guessed": bool(x.get("guessed")),
            }
            for x in lots
        ],
        "expires_on": day.isoformat() if day else None,
        "expires_guessed": is_guessed(g) if lots else False,
        "undated": _qty_json(undated_qty(g)),
        "lots_line": summary_line(g),
    }


def dated_packs(g, item=None) -> list[dict]:
    """One row per dated pack for the store-style date check."""
    today = date.today()
    out = []
    fallback = (getattr(g, "default_location", None) or "").strip()
    for lot in lots_list(g):
        day = parse_day(lot.get("expires_on"))
        q = _qty(lot.get("qty"))
        if day is None or q <= 0:
            continue
        left = (day - today).days
        out.append(
            {
                "item": item,
                "qty": _qty_json(q),
                "expires_on": day,
                "place": (lot.get("place") or fallback or "").strip(),
                "gone": left < 0,
                "soon": 0 <= left <= 30,
                "guessed": bool(lot.get("guessed")),
            }
        )
    return out


def first_place(g) -> str | None:
    for lot in lots_list(g):
        p = _place(lot.get("place"))
        if p:
            return p
    return None
