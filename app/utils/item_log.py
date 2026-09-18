"""Miles, hours, fill-ups, and repairs on a household thing."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation


def _dec(raw, default=None):
    s = str(raw or "").strip().replace("$", "").replace(",", "")
    if not s:
        return default
    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        return default
    return d


def _f(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def year_driven(readings, year: int, current) -> int | None:
    """Miles (or hours) put on this year from odometer snapshots. Gas not required."""
    cur = _f(current)
    if cur is None:
        return None
    jan1 = date(year, 1, 1)
    before = []
    during = []
    for when, raw in readings or []:
        n = _f(raw)
        if n is None:
            continue
        if when is None:
            during.append(n)
            continue
        day = when.date() if hasattr(when, "date") and not isinstance(when, date) else when
        try:
            if day < jan1:
                before.append(n)
            else:
                during.append(n)
        except TypeError:
            during.append(n)
    start = before[-1] if before else (during[0] if during else None)
    if start is None:
        return None
    delta = cur - start
    if delta < 0:
        return None
    return int(round(delta))


def mpg_of(miles, gallons) -> float | None:
    m = _f(miles)
    g = _f(gallons)
    if m is None or g is None or g <= 0 or m <= 0:
        return None
    return round(m / g, 1)


def last_fillup(item_id: int, household_id: int, before_id: int | None = None):
    from app.builddb.table_item_logs import ItemLog

    q = ItemLog.query.filter_by(household_id=household_id, item_id=item_id, kind="fillup")
    if before_id:
        q = q.filter(ItemLog.id < before_id)
    return q.order_by(ItemLog.happened_on.desc(), ItemLog.id.desc()).first()


def add_item_log(
    item,
    *,
    kind: str,
    user_id,
    reading=None,
    gallons=None,
    cost=None,
    notes=None,
    title=None,
    happened_on=None,
    extra=None,
    maintenance_id=None,
):
    from app.builddb.builddb import db
    from app.builddb.table_item_logs import LOG_KINDS, ItemLog

    kind = (kind or "note").strip().lower()
    if kind not in LOG_KINDS:
        kind = "note"
    when = happened_on or date.today()
    read = _dec(reading)
    gal = _dec(gallons)
    pay = _dec(cost)
    extra = dict(extra or {})
    if kind == "fillup" and read is not None and gal and gal > 0:
        prev = last_fillup(item.id, item.household_id)
        prev_read = _dec(prev.reading) if prev is not None else None
        if prev_read is not None and read > prev_read:
            extra["mpg"] = mpg_of(read - prev_read, gal)
            extra["miles"] = float(read - prev_read)
    row = ItemLog(
        household_id=item.household_id,
        item_id=item.id,
        kind=kind,
        happened_on=when,
        reading=read,
        gallons=gal,
        cost=pay,
        title=(title or "").strip()[:200] or None,
        notes=(notes or "").strip() or None,
        extra_data=extra or None,
        maintenance_id=maintenance_id,
        created_by=user_id,
    )
    db.session.add(row)
    db.session.flush()
    if read is not None:
        if item.item_type == "vehicle" and item.vehicle:
            try:
                item.vehicle.current_mileage = int(read)
            except Exception:
                pass
        elif item.item_type == "tool" and item.tool:
            item.tool.hours_used = read
    return row


def log_stats(item) -> dict:
    from app.builddb.table_item_logs import ItemLog

    rows = (
        ItemLog.query.filter_by(household_id=item.household_id, item_id=item.id)
        .order_by(ItemLog.happened_on.desc(), ItemLog.id.desc())
        .limit(400)
        .all()
    )
    year = date.today().year
    gal = Decimal("0")
    spent = Decimal("0")
    mpg_vals = []
    year_gal = Decimal("0")
    year_spent = Decimal("0")
    year_mpg = []
    last_fill = None
    for r in rows:
        if r.kind != "fillup":
            continue
        if last_fill is None:
            last_fill = r
        g = _dec(r.gallons) or Decimal("0")
        c = _dec(r.cost) or Decimal("0")
        gal += g
        spent += c
        mpg = None
        extra = r.extra_data if isinstance(r.extra_data, dict) else {}
        try:
            mpg = float(extra.get("mpg")) if extra.get("mpg") is not None else None
        except (TypeError, ValueError):
            mpg = None
        if mpg:
            mpg_vals.append(mpg)
        if r.happened_on and r.happened_on.year == year:
            year_gal += g
            year_spent += c
            if mpg:
                year_mpg.append(mpg)
    last_mpg = None
    extra = (last_fill.extra_data if last_fill and isinstance(last_fill.extra_data, dict) else {}) or {}
    try:
        last_mpg = float(extra["mpg"]) if extra.get("mpg") is not None else None
    except (TypeError, ValueError):
        last_mpg = None
    def avg(vals):
        return round(sum(vals) / len(vals), 1) if vals else None

    reading = None
    if item.item_type == "vehicle" and item.vehicle:
        reading = item.vehicle.current_mileage
    elif item.item_type == "tool" and item.tool:
        reading = item.tool.hours_used
    snaps = [
        (r.happened_on, r.reading)
        for r in reversed(rows)
        if r.reading is not None and r.kind in ("miles", "hours", "fillup", "repair", "code")
    ]
    ytd = year_driven(snaps, year, reading)
    codes = [r for r in rows if r.kind == "code"]
    latest = {}
    for r in codes:
        key = (r.title or "").upper()
        if key and key not in latest:
            latest[key] = r
    active_codes = [
        r
        for r in latest.values()
        if (r.extra_data or {}).get("status") != "cleared"
    ]
    return {
        "reading": reading,
        "last_fill": last_fill,
        "last_mpg": last_mpg,
        "avg_mpg": avg(mpg_vals),
        "gallons": float(gal) if gal else 0,
        "spent": float(spent) if spent else 0,
        "year_gallons": float(year_gal) if year_gal else 0,
        "year_spent": float(year_spent) if year_spent else 0,
        "year_mpg": avg(year_mpg),
        "year": year,
        "year_miles": ytd,
        "count": len(rows),
        "active_codes": active_codes,
    }
