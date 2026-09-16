"""US vehicle decode via NHTSA vPIC (free, no key). Plate is stored; full specs come from VIN."""
from __future__ import annotations

import re
import requests

_UA = {"User-Agent": "family.poweredby.top/1.0 (household)"}
_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$", re.I)
_SKIP = {"", "0", "not applicable", "n/a", "null", "none"}

# Human labels for the household card (NHTSA key → label)
FACT_LABELS = (
    ("year", "Year"),
    ("make", "Make"),
    ("model", "Model"),
    ("trim", "Trim"),
    ("series", "Series"),
    ("body_class", "Body"),
    ("vehicle_type", "Type"),
    ("doors", "Doors"),
    ("drive_type", "Drive"),
    ("fuel_type", "Fuel"),
    ("engine", "Engine"),
    ("displacement_l", "Displacement (L)"),
    ("cylinders", "Cylinders"),
    ("horsepower", "Horsepower"),
    ("transmission", "Transmission"),
    ("gvwr", "GVWR"),
    ("manufacturer", "Built by"),
    ("plant", "Plant"),
    ("electrification", "Electrification"),
    ("abs", "ABS"),
    ("airbags", "Airbags"),
    ("tpms", "TPMS"),
    ("steering", "Steering"),
    ("brake_system", "Brakes"),
)


def looks_like_vin(value: str) -> bool:
    return bool(_VIN_RE.match((value or "").strip().replace(" ", "").upper()))


def _clean_val(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in _SKIP:
        return None
    return s


def decode_vin(vin: str) -> dict:
    code = (vin or "").strip().replace(" ", "").upper()
    out = {"ok": False, "vin": code, "facts": {}, "raw": {}, "recalls": [], "error": None}
    if not looks_like_vin(code):
        out["error"] = "VIN should be 17 characters (no I, O, or Q)."
        return out
    try:
        from app.utils.hot_cache import get as cache_get

        cached = cache_get(f"vin:{code}")
        if isinstance(cached, dict):
            return cached
    except Exception:
        pass
    url = f"https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{code}?format=json"
    try:
        r = requests.get(url, timeout=10, headers=_UA)
        data = r.json() if r.ok else {}
    except Exception as e:
        out["error"] = f"NHTSA lookup failed ({e})."
        return out
    rows = data.get("Results") or []
    raw = rows[0] if rows else {}
    out["raw"] = {k: v for k, v in raw.items() if _clean_val(v)}
    err = _clean_val(raw.get("ErrorText") or raw.get("ErrorCode"))
    facts = {
        "year": _clean_val(raw.get("ModelYear")),
        "make": _clean_val(raw.get("Make")),
        "model": _clean_val(raw.get("Model")),
        "trim": _clean_val(raw.get("Trim") or raw.get("Trim2")),
        "series": _clean_val(raw.get("Series")),
        "body_class": _clean_val(raw.get("BodyClass")),
        "vehicle_type": _clean_val(raw.get("VehicleType")),
        "doors": _clean_val(raw.get("Doors")),
        "drive_type": _clean_val(raw.get("DriveType")),
        "fuel_type": _clean_val(raw.get("FuelTypePrimary")),
        "engine": " ".join(
            x
            for x in (
                _clean_val(raw.get("EngineConfiguration")),
                _clean_val(raw.get("EngineCylinders")) and f"{raw.get('EngineCylinders')}-cyl",
                _clean_val(raw.get("DisplacementL")) and f"{raw.get('DisplacementL')}L",
                _clean_val(raw.get("EngineModel")),
            )
            if x
        )
        or None,
        "displacement_l": _clean_val(raw.get("DisplacementL")),
        "cylinders": _clean_val(raw.get("EngineCylinders")),
        "horsepower": _clean_val(raw.get("EngineHP")),
        "transmission": _clean_val(raw.get("TransmissionStyle") or raw.get("TransmissionSpeeds")),
        "gvwr": _clean_val(raw.get("GVWR")),
        "manufacturer": _clean_val(raw.get("Manufacturer")),
        "plant": " ".join(
            x
            for x in (
                _clean_val(raw.get("PlantCity")),
                _clean_val(raw.get("PlantState")),
                _clean_val(raw.get("PlantCountry")),
            )
            if x
        )
        or None,
        "electrification": _clean_val(raw.get("ElectrificationLevel")),
        "abs": _clean_val(raw.get("ABS")),
        "airbags": _clean_val(raw.get("AirBagLocFront") or raw.get("AirBagLocSide")),
        "tpms": _clean_val(raw.get("TPMS")),
        "steering": _clean_val(raw.get("SteeringLocation")),
        "brake_system": _clean_val(raw.get("BrakeSystemType")),
        "color": None,
        "plate": None,
    }
    out["facts"] = {k: v for k, v in facts.items() if v}
    out["ok"] = bool(out["facts"].get("make") or out["facts"].get("model"))
    if not out["ok"]:
        out["error"] = err or "NHTSA did not recognize that VIN."
        return out
    out["recalls"] = _recalls(out["facts"].get("make"), out["facts"].get("model"), out["facts"].get("year"))
    out["name"] = " ".join(
        x for x in (out["facts"].get("year"), out["facts"].get("make"), out["facts"].get("model"), out["facts"].get("trim")) if x
    )
    try:
        from app.utils.hot_cache import put as cache_put

        cache_put(f"vin:{code}", dict(out), 7 * 24 * 3600)
    except Exception:
        pass
    return out


def _recalls(make, model, year) -> list:
    if not (make and model and year):
        return []
    url = "https://api.nhtsa.gov/recalls/recallsByVehicle"
    try:
        r = requests.get(
            url,
            params={"make": make, "model": model, "modelYear": year},
            timeout=8,
            headers=_UA,
        )
        data = r.json() if r.ok else {}
    except Exception:
        return []
    rows = data.get("results") or []
    out = []
    for row in rows[:25]:
        summary = (row.get("Summary") or "")[:400]
        out.append(
            {
                "date": row.get("ReportReceivedDate") or "",
                "component": row.get("Component") or "",
                "summary": summary,
                "campaign": row.get("NHTSACampaignNumber") or "",
            }
        )
    return out


def lookup_vehicle(plate: str = "", vin: str = "") -> dict:
    plate = (plate or "").strip().upper().replace(" ", "")
    vin = (vin or "").strip().replace(" ", "").upper()
    if not vin and looks_like_vin(plate):
        vin, plate = plate, ""
    if vin:
        decoded = decode_vin(vin)
        if plate:
            decoded["facts"]["plate"] = plate
            decoded["plate"] = plate
        decoded["vin"] = vin
        return decoded
    if plate:
        return {
            "ok": True,
            "vin": "",
            "plate": plate,
            "facts": {"plate": plate},
            "raw": {},
            "recalls": [],
            "error": None,
            "name": f"Plate {plate}",
            "need_vin": True,
            "message": "Plate saved. Paste the 17-character VIN from the dash or registration for factory specs.",
        }
    return {"ok": False, "error": "Enter a plate or a 17-character VIN.", "facts": {}, "recalls": []}


DIFF_FIELDS = (
    ("name", "Name"),
    ("vin", "VIN"),
    ("year", "Year"),
    ("make", "Make"),
    ("model", "Model"),
    ("trim", "Trim"),
    ("body_class", "Body"),
    ("drive_type", "Drive"),
    ("fuel_type", "Fuel"),
    ("engine", "Engine"),
    ("transmission", "Transmission"),
    ("doors", "Doors"),
    ("manufacturer", "Built by"),
    ("color", "Color"),
    ("plate", "Plate"),
)


def vehicle_ours(v, item) -> dict:
    return {
        "name": (item.name if item is not None else None) or None,
        "vin": getattr(v, "vin", None),
        "year": str(v.year) if getattr(v, "year", None) else None,
        "make": getattr(v, "make", None),
        "model": getattr(v, "model", None),
        "trim": getattr(v, "trim", None),
        "body_class": getattr(v, "body_class", None),
        "drive_type": getattr(v, "drive_type", None),
        "fuel_type": getattr(v, "fuel_type", None),
        "engine": getattr(v, "engine", None),
        "transmission": getattr(v, "transmission", None),
        "doors": getattr(v, "doors", None),
        "manufacturer": getattr(v, "manufacturer", None),
        "color": getattr(v, "color", None),
        "plate": getattr(v, "plate", None),
    }


def vehicle_theirs(decoded: dict) -> dict:
    facts = dict((decoded or {}).get("facts") or {})
    if (decoded or {}).get("vin"):
        facts["vin"] = decoded["vin"]
    if (decoded or {}).get("name"):
        facts["name"] = decoded["name"]
    if (decoded or {}).get("plate"):
        facts["plate"] = decoded["plate"]
    return facts


def diff_vehicle(v, item, decoded: dict) -> list[dict]:
    """Fields NHTSA would change. Empty ours = fill-in. Different ours = overwrite candidate."""
    ours = vehicle_ours(v, item)
    theirs = vehicle_theirs(decoded)
    diffs = []
    for key, label in DIFF_FIELDS:
        a = _clean_val(ours.get(key))
        b = _clean_val(theirs.get(key))
        if not b:
            continue
        if not a:
            diffs.append({"field": key, "label": label, "ours": "", "theirs": b, "kind": "fill"})
        elif a.lower() != b.lower():
            diffs.append({"field": key, "label": label, "ours": a, "theirs": b, "kind": "change"})
    return diffs


def apply_vehicle_lookup(v, item, decoded: dict, *, fields=None, overwrite=False) -> None:
    facts = (decoded or {}).get("facts") or {}
    allow = {str(x) for x in fields} if fields else None

    def take(key: str) -> bool:
        return allow is None or key in allow

    vin = (decoded or {}).get("vin") or facts.get("vin")
    if vin and take("vin") and (overwrite or not getattr(v, "vin", None)):
        v.vin = str(vin)[:32]
    plate = (decoded or {}).get("plate") or facts.get("plate")
    if plate and take("plate") and (overwrite or not getattr(v, "plate", None)):
        v.plate = str(plate)[:20]
    mapping = (
        ("make", "make"),
        ("model", "model"),
        ("trim", "trim"),
        ("body_class", "body_class"),
        ("drive_type", "drive_type"),
        ("fuel_type", "fuel_type"),
        ("engine", "engine"),
        ("transmission", "transmission"),
        ("doors", "doors"),
        ("manufacturer", "manufacturer"),
        ("color", "color"),
    )
    for fact_key, col in mapping:
        val = facts.get(fact_key)
        if val and take(fact_key) and (overwrite or not getattr(v, col, None)):
            setattr(v, col, str(val)[:160])
    year = facts.get("year")
    if year and take("year") and (overwrite or not v.year):
        try:
            v.year = int(str(year)[:4])
        except ValueError:
            pass
    extra = dict(v.extra_data or {})
    extra["nhtsa"] = facts
    extra["nhtsa_raw"] = (decoded or {}).get("raw") or {}
    extra["recalls"] = (decoded or {}).get("recalls") or []
    v.extra_data = extra
    if item is not None and decoded.get("name") and take("name"):
        if overwrite or not item.name or item.name.lower() in ("vehicle", "car", "truck"):
            item.name = str(decoded["name"])[:200]
