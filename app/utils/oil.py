"""Oil the machine needs, what is in it, and when the next change is due."""
from __future__ import annotations

import calendar
from datetime import date, datetime


def _text(value, cap: int) -> str:
    return ("" if value is None else str(value)).strip()[:cap]


def _blank(value) -> bool:
    return value is None or str(value).strip() == ""


def add_months(day: date, months: int) -> date:
    months = int(months)
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def _date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value, 32)
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _int(value):
    text = _text(value, 20).replace(",", "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _put(record, attr: str, raw, *, clear: bool, kind: str, cap: int = 200):
    if raw is None and not clear:
        return
    if _blank(raw):
        if clear:
            setattr(record, attr, None)
        return
    if kind == "date":
        parsed = _date(raw)
        if parsed or clear:
            setattr(record, attr, parsed)
        return
    if kind == "int":
        parsed = _int(raw)
        if parsed is None:
            if clear:
                setattr(record, attr, None)
            return
        setattr(record, attr, parsed)
        return
    setattr(record, attr, _text(raw, cap) or None)


def apply_vehicle_oil(vehicle, data: dict, *, clear: bool = False) -> None:
    """Set the oil record. Blank fields stay put unless clear is true."""
    data = data or {}
    _put(vehicle, "oil_needs", data.get("needs", data.get("oil_needs")), clear=clear, kind="text", cap=200)
    _put(vehicle, "oil_capacity", data.get("capacity", data.get("oil_capacity")), clear=clear, kind="text", cap=40)
    _put(vehicle, "oil_type", data.get("in_it", data.get("oil_type")), clear=clear, kind="text", cap=80)
    _put(vehicle, "filter_type", data.get("filter", data.get("filter_type")), clear=clear, kind="text", cap=80)
    _put(vehicle, "last_oil_change_date", data.get("last_date", data.get("last_oil_change_date")), clear=clear, kind="date")
    _put(vehicle, "last_oil_change_mileage", data.get("last_miles", data.get("last_oil_change_mileage")), clear=clear, kind="int")
    _put(vehicle, "oil_interval_miles", data.get("interval_miles", data.get("oil_interval_miles")), clear=clear, kind="int")
    _put(vehicle, "oil_interval_months", data.get("interval_months", data.get("oil_interval_months")), clear=clear, kind="int")
    next_date = data.get("next_date", data.get("next_oil_due_date"))
    next_miles = data.get("next_miles", data.get("next_oil_due_mileage"))
    if not _blank(next_date):
        _put(vehicle, "next_oil_due_date", next_date, clear=clear, kind="date")
    elif vehicle.last_oil_change_date and vehicle.oil_interval_months:
        vehicle.next_oil_due_date = add_months(vehicle.last_oil_change_date, vehicle.oil_interval_months)
    elif clear and ("next_date" in data or "next_oil_due_date" in data):
        vehicle.next_oil_due_date = None
    if not _blank(next_miles):
        _put(vehicle, "next_oil_due_mileage", next_miles, clear=clear, kind="int")
    elif vehicle.last_oil_change_mileage is not None and vehicle.oil_interval_miles:
        vehicle.next_oil_due_mileage = int(vehicle.last_oil_change_mileage) + int(vehicle.oil_interval_miles)
    elif clear and ("next_miles" in data or "next_oil_due_mileage" in data):
        vehicle.next_oil_due_mileage = None


def apply_tool_oil(tool, data: dict, *, clear: bool = False) -> None:
    data = data or {}
    _put(tool, "oil_needs", data.get("needs", data.get("oil_needs")), clear=clear, kind="text", cap=200)
    _put(tool, "oil_capacity", data.get("capacity", data.get("oil_capacity")), clear=clear, kind="text", cap=40)
    _put(tool, "oil_type", data.get("in_it", data.get("oil_type")), clear=clear, kind="text", cap=80)
    _put(tool, "last_oil_date", data.get("last_date", data.get("last_oil_date")), clear=clear, kind="date")
    _put(tool, "last_oil_hours", data.get("last_hours", data.get("last_oil_hours")), clear=clear, kind="int")
    _put(tool, "oil_interval_hours", data.get("interval_hours", data.get("oil_interval_hours")), clear=clear, kind="int")
    _put(tool, "oil_interval_months", data.get("interval_months", data.get("oil_interval_months")), clear=clear, kind="int")
    next_date = data.get("next_date", data.get("next_oil_due_date"))
    next_hours = data.get("next_hours", data.get("next_oil_due_hours"))
    if not _blank(next_date):
        _put(tool, "next_oil_due_date", next_date, clear=clear, kind="date")
    elif tool.last_oil_date and tool.oil_interval_months:
        tool.next_oil_due_date = add_months(tool.last_oil_date, tool.oil_interval_months)
    elif clear and ("next_date" in data or "next_oil_due_date" in data):
        tool.next_oil_due_date = None
    if not _blank(next_hours):
        _put(tool, "next_oil_due_hours", next_hours, clear=clear, kind="int")
    elif tool.last_oil_hours is not None and tool.oil_interval_hours:
        tool.next_oil_due_hours = int(tool.last_oil_hours) + int(tool.oil_interval_hours)
    elif clear and ("next_hours" in data or "next_oil_due_hours" in data):
        tool.next_oil_due_hours = None


def save_item_oil(item, data: dict, *, clear: bool = False) -> str:
    if getattr(item, "vehicle", None) is not None:
        apply_vehicle_oil(item.vehicle, data, clear=clear)
        return "vehicle"
    if getattr(item, "tool", None) is not None:
        apply_tool_oil(item.tool, data, clear=clear)
        return "tool"
    raise ValueError("no oil record")
