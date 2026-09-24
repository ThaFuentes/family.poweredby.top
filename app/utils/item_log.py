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
        if r.reading is not None and r.kind in ("miles", "hours", "fillup", "repair", "code", "trip")
    ]
    ytd = year_driven(snaps, year, reading)
    trip_miles = Decimal("0")
    year_trip = Decimal("0")
    trip_n = 0
    open_trip = None
    last_trip = None
    for r in rows:
        if r.kind != "trip":
            continue
        extra = r.extra_data if isinstance(r.extra_data, dict) else {}
        if extra.get("status") == "open" and open_trip is None:
            open_trip = r
        miles = _dec(extra.get("miles"))
        if miles and miles > 0:
            trip_n += 1
            trip_miles += miles
            if r.happened_on and r.happened_on.year == year:
                year_trip += miles
            if last_trip is None:
                last_trip = r
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
        "open_trip": open_trip,
        "last_trip": last_trip,
        "trip_count": trip_n,
        "trip_miles": float(trip_miles) if trip_miles else 0,
        "year_trip_miles": float(year_trip) if year_trip else 0,
    }


def _miles_int(raw):
    n = _dec(raw)
    if n is None:
        return None
    v = int(n)
    return v if v >= 0 else None


def trip_extra(row) -> dict:
    return dict(row.extra_data) if row is not None and isinstance(row.extra_data, dict) else {}


def open_trips_for_household(household_id: int, *, user_id: int | None = None):
    from app.builddb.table_item_logs import ItemLog
    from app.builddb.table_items import Item

    q = (
        ItemLog.query.join(Item, Item.id == ItemLog.item_id)
        .filter(
            ItemLog.household_id == household_id,
            ItemLog.kind == "trip",
            Item.removed_at.is_(None),
        )
        .order_by(ItemLog.id.desc())
        .limit(40)
    )
    out = []
    for row in q.all():
        if trip_extra(row).get("status") == "open":
            out.append(row)
    return out


def open_trip(item):
    from app.builddb.table_item_logs import ItemLog

    rows = (
        ItemLog.query.filter_by(household_id=item.household_id, item_id=item.id, kind="trip")
        .order_by(ItemLog.id.desc())
        .limit(20)
        .all()
    )
    for row in rows:
        if trip_extra(row).get("status") == "open":
            return row
    return None


def trip_title(origin: str, dest: str) -> str:
    a = (origin or "").strip()
    b = (dest or "").strip()
    if a:
        a = a[0].upper() + a[1:] if len(a) > 1 else a.upper()
    if b:
        b = b[0].upper() + b[1:] if len(b) > 1 else b.upper()
    if a and b:
        return f"{a} → {b}"
    return a or b or "Trip"


def start_trip(item, *, user_id, start_miles, origin="", dest="", happened_on=None, notes=None):
    start = _miles_int(start_miles)
    if start is None:
        raise ValueError("Need starting miles from the odometer.")
    live = open_trip(item)
    if live is not None:
        return live, "open"
    extra = {
        "status": "open",
        "origin": (origin or "").strip()[:80],
        "dest": (dest or "").strip()[:80],
        "start_miles": start,
    }
    row = add_item_log(
        item,
        kind="trip",
        user_id=user_id,
        reading=start,
        title=trip_title(origin, dest),
        notes=notes,
        happened_on=happened_on,
        extra=extra,
    )
    return row, "started"


def end_trip(item, *, user_id, end_miles, happened_on=None, notes=None, row=None):
    from sqlalchemy.orm.attributes import flag_modified

    from app.builddb.builddb import db

    live = row if row is not None else open_trip(item)
    if live is None:
        raise ValueError("No open trip on this vehicle.")
    end = _miles_int(end_miles)
    if end is None:
        raise ValueError("Need ending miles from the odometer.")
    extra = trip_extra(live)
    start = _miles_int(extra.get("start_miles") if extra.get("start_miles") is not None else live.reading)
    if start is None:
        start = end
    miles = end - start
    if miles < 0:
        raise ValueError(f"Ending miles ({end:,}) are before the start ({start:,}).")
    extra["status"] = "done"
    extra["start_miles"] = start
    extra["end_miles"] = end
    extra["miles"] = miles
    extra["ended_on"] = (happened_on or date.today()).isoformat()
    live.extra_data = extra
    try:
        flag_modified(live, "extra_data")
    except Exception:
        pass
    live.reading = end
    if notes:
        live.notes = ((live.notes or "") + ("\n" if live.notes else "") + str(notes).strip())[:4000]
    if item.item_type == "vehicle" and item.vehicle:
        item.vehicle.current_mileage = end
    db.session.flush()
    return live, miles
