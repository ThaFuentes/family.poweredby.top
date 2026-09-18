"""Vehicle OBD / dash codes. AI looks them up when the household has a key."""
from __future__ import annotations

import re

_CODE = re.compile(r"\b([PCBU][0-9A-Fa-f]{4})\b", re.I)

# Short fallbacks when AI is off. Not a full DTC bible.
COMMON = {
    "P0300": ("Random misfire", "engine", "Plugs, coils, fuel, vacuum leak."),
    "P0301": ("Cylinder 1 misfire", "engine", "Plug, coil, injector on cylinder 1."),
    "P0302": ("Cylinder 2 misfire", "engine", "Plug, coil, injector on cylinder 2."),
    "P0303": ("Cylinder 3 misfire", "engine", "Plug, coil, injector on cylinder 3."),
    "P0304": ("Cylinder 4 misfire", "engine", "Plug, coil, injector on cylinder 4."),
    "P0171": ("System too lean (bank 1)", "fuel", "Vacuum leak, MAF, fuel pressure, O2 sensor."),
    "P0174": ("System too lean (bank 2)", "fuel", "Same as P0171 on the other bank."),
    "P0420": ("Catalyst efficiency below threshold (bank 1)", "exhaust", "Cat, downstream O2, exhaust leak."),
    "P0430": ("Catalyst efficiency below threshold (bank 2)", "exhaust", "Same as P0420 on the other bank."),
    "P0442": ("EVAP small leak", "fuel", "Gas cap, EVAP hose, purge valve."),
    "P0455": ("EVAP large leak", "fuel", "Gas cap left off, EVAP hose."),
    "P0128": ("Coolant temp below thermostat", "cooling", "Stuck-open thermostat, low coolant."),
    "P0401": ("EGR insufficient flow", "engine", "EGR valve, passages carboned up."),
    "P0133": ("O2 sensor slow (bank 1 sensor 1)", "exhaust", "Upstream O2, wiring, exhaust leak."),
    "P0500": ("Vehicle speed sensor", "drivetrain", "VSS, ABS ring, cluster."),
    "C0035": ("Left front wheel speed", "brakes", "ABS sensor, tone ring, wiring."),
    "B0001": ("Driver airbag circuit", "body", "Clock spring, airbag, SRS module — don't guess."),
    "U0100": ("Lost comms with ECM", "electrical", "Battery, grounds, CAN wiring, module."),
}

_FAMILY = {
    "P": "Powertrain (engine / trans)",
    "C": "Chassis (ABS / suspension)",
    "B": "Body (airbag / comfort)",
    "U": "Network (modules talking)",
}


def parse_dtcs(raw: str) -> list[str]:
    found = []
    seen = set()
    for m in _CODE.finditer(raw or ""):
        code = m.group(1).upper()
        if code not in seen:
            seen.add(code)
            found.append(code)
    return found


def normalize_dtc(raw: str) -> str | None:
    s = (raw or "").strip().upper()
    if _CODE.fullmatch(s):
        return s
    found = parse_dtcs(s)
    return found[0] if found else None


def _fallback(code: str) -> dict:
    meaning, system, likely = COMMON.get(code, ("", "", ""))
    if not meaning:
        meaning = _FAMILY.get(code[:1], "Trouble code")
        likely = "Look it up with AI on, or a shop scanner."
        system = {"P": "engine", "C": "brakes", "B": "body", "U": "electrical"}.get(code[:1], "")
    return {
        "code": code,
        "meaning": meaning,
        "system": system,
        "likely": likely,
        "used_ai": False,
    }


def lookup_dtc(code: str, *, vehicle=None, household=None) -> dict:
    code = normalize_dtc(code) or (code or "").strip().upper()[:8]
    if not code:
        return {}
    out = _fallback(code)
    if household is None:
        return out
    try:
        from app.utils.ai import complete_json, get_ai_config

        cfg = get_ai_config(household, household_only=True)
        if not cfg.get("ready"):
            return out
        year = getattr(vehicle, "year", None) or ""
        make = getattr(vehicle, "make", None) or ""
        model = getattr(vehicle, "model", None) or ""
        prompt = (
            f"OBD/DTC {code} on a {year} {make} {model}. "
            "Reply JSON only: "
            '{"meaning":"short title","system":"engine|exhaust|fuel|brakes|electrical|body","likely":"one short sentence of common causes","severity":"low|medium|high"}. '
            "No markdown. Household mechanic notes, not a shop invoice."
        )
        ok, data = complete_json(prompt, household=household, max_tokens=280, timeout=12)
        if not ok or not isinstance(data, dict) or data.get("error"):
            return out
        meaning = str(data.get("meaning") or "").strip()[:200]
        likely = str(data.get("likely") or "").strip()[:400]
        system = str(data.get("system") or out["system"]).strip()[:40]
        if meaning:
            out["meaning"] = meaning
        if likely:
            out["likely"] = likely
        if system:
            out["system"] = system
        sev = str(data.get("severity") or "").strip().lower()
        if sev in ("low", "medium", "high"):
            out["severity"] = sev
        out["used_ai"] = True
    except Exception:
        return out
    return out
