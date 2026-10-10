"""The Family bot route map. GET /api/v1/helper returns this.

A path that is not listed here is 404. /api/v1/me is this account (whoami),
not a person record. data.guide is the field-by-field help for this key.
The same contract is docs/BOT_API.md.
"""
from __future__ import annotations

from app.utils.bot_api_keys import SCOPE_ALL, SCOPE_VAULT

# method, path, scope (either | fos_bot_ | fos_vault_), needs, one line.
HELP_CALLS = (
    ("GET", "/api/v1/helper", "either", "", "This map. Call it whenever you need the paths. /api/v1/help is the same."),
    ("GET", "/api/v1/help", "either", "", "Same map as /api/v1/helper."),
    ("GET", "/api/v1/whoami", "either", "", "This bot: name, scope, role, and what the account can do."),
    ("GET", "/api/v1/me", "either", "", "Same as whoami. There is no other /me."),
    ("GET", "/api/v1/meta", "either", "", "Both scopes, for reference."),
    ("POST", "/api/v1/auth/present", "login", "", "Send the login key. A 2FA key is emailed to the other inbox for 1 hour."),
    ("POST", "/api/v1/auth/exchange", "login", "", "Login key as Bearer, 2FA key as X-FOS-2FA. Returns fos_s1_."),
    ("POST", "/api/v1/auth/revoke", "either", "", "End this session only. The login key stays."),
    ("POST", "/api/v1/auth/reset", "either", "", "End this session and replace the login key. The new key does not expire and is emailed to the login inbox. Call this when the session is finished."),
    ("GET", "/api/v1/vehicles", "fos_bot_", "view", "Vehicles. Query limit, offset."),
    ("GET", "/api/v1/vehicles/<id>", "fos_bot_", "view", "One vehicle."),
    ("POST", "/api/v1/vehicles", "fos_bot_", "maintain or edit_meta", "Body name, and optional year, make, model, category, notes, current_mileage, oil_needs."),
    ("PATCH", "/api/v1/vehicles/<id>", "fos_bot_", "maintain or edit_meta", "Same fields as create. Unknown fields are ignored."),
    ("GET", "/api/v1/notes", "fos_bot_", "view", "Notes. Query scope, limit, offset."),
    ("GET", "/api/v1/notes/<id>", "fos_bot_", "view", "One note."),
    ("POST", "/api/v1/notes", "fos_bot_", "view", "Body title, body, visibility, item_id."),
    ("PATCH", "/api/v1/notes/<id>", "fos_bot_", "author, leader, or admin", "Same fields. A child can edit only their own note."),
    ("GET", "/api/v1/notes/<id>/files", "fos_bot_", "view", "Files on a note."),
    ("POST", "/api/v1/notes/<id>/files", "fos_bot_", "view", "Multipart field file. Optional caption."),
    ("GET", "/api/v1/files/<id>", "fos_bot_", "view", "The file bytes."),
    ("GET", "/api/v1/inventory", "fos_bot_", "view", "Stock. Query q, limit, offset."),
    ("GET", "/api/v1/inventory/<id>", "fos_bot_", "view", "One item."),
    ("POST", "/api/v1/inventory", "fos_bot_", "scan, groceries, or maintain", "Groceries. Body name. Optional quantity, barcode, location, brand, size, unit. A tool or house thing uses POST /tools or POST /house."),
    ("PATCH", "/api/v1/inventory/<id>", "fos_bot_", "scan, groceries, or maintain", "Same fields, plus expires_on YYYY-MM-DD. A child may change stock, not the name."),
    ("GET", "/api/v1/records", "fos_bot_", "legal", "Legal paper. Query status, limit, offset."),
    ("GET", "/api/v1/records/<id>", "fos_bot_", "legal", "One record."),
    ("POST", "/api/v1/records", "fos_bot_", "legal", "Body title. Optional kind, status, agency, case_number, location, issued_on, due_on, amount, body."),
    ("PATCH", "/api/v1/records/<id>", "fos_bot_", "legal", "Same fields. case_id ties the paper to a case. null pulls it off. A multipart file on this call is kept on the record."),
    ("GET", "/api/v1/records/<id>/files", "fos_bot_", "legal", "Photos and PDFs already on a record."),
    ("POST", "/api/v1/records/<id>/files", "fos_bot_", "legal", "Multipart field file, photo, or image. Adds another photo or PDF, such as a paid receipt. Optional caption."),
    ("GET", "/api/v1/records/<id>/files/<file_id>", "fos_bot_", "legal", "The file bytes for one photo or PDF on a record."),
    ("GET", "/api/v1/cases", "fos_bot_", "legal", "Cases. Query limit, offset."),
    ("GET", "/api/v1/cases/<id>", "fos_bot_", "legal", "One case."),
    ("POST", "/api/v1/cases", "fos_bot_", "legal", "Body title. Optional status open or closed, and summary. The number is assigned."),
    ("PATCH", "/api/v1/cases/<id>", "fos_bot_", "legal", "Same fields as create. status open or closed."),
    ("POST", "/api/v1/cases/<id>/followups", "fos_bot_", "legal", "Body kind note, link, or email. A photo or PDF goes on the record with POST /api/v1/records/<id>/files."),
    ("GET", "/api/v1/basket", "fos_bot_", "view", "Shopping basket. Query status=open."),
    ("POST", "/api/v1/basket", "fos_bot_", "scan or edit_grocery", "Body name. Optional item_id, quantity_needed, reason, note."),
    ("POST", "/api/v1/basket/<id>/done", "fos_bot_", "scan or edit_grocery", "Check one line off. There is no delete."),
    ("POST", "/api/v1/basket/<id>/match", "fos_bot_", "scan or edit_grocery", "Tie a basket line to stock. Body item_id."),
    ("GET", "/api/v1/reminders", "fos_bot_", "view", "Due items. Query status, limit, offset."),
    ("POST", "/api/v1/reminders", "fos_bot_", "maintain", "Body title. Optional type, due_at, item_id, recurrence, notes."),
    ("PATCH", "/api/v1/reminders/<id>", "fos_bot_", "maintain", "Same fields, plus status open or done."),
    ("POST", "/api/v1/reminders/<id>/done", "fos_bot_", "maintain", "Mark one done."),
    ("GET", "/api/v1/tools", "fos_bot_", "view", "Tools. Query limit, offset."),
    ("GET", "/api/v1/tools/<id>", "fos_bot_", "view", "One tool."),
    ("POST", "/api/v1/tools", "fos_bot_", "maintain or edit_meta", "Body name. Optional category, notes, type, model, serial_number, asset_id, power_source, oil_needs, oil_capacity."),
    ("PATCH", "/api/v1/tools/<id>", "fos_bot_", "maintain or edit_meta", "Same fields. Unknown fields are ignored."),
    ("GET", "/api/v1/house", "fos_bot_", "view", "House things. Query limit, offset."),
    ("GET", "/api/v1/house/<id>", "fos_bot_", "view", "One house thing. The reply key is place."),
    ("POST", "/api/v1/house", "fos_bot_", "maintain or edit_meta", "Body name. Optional category, notes."),
    ("PATCH", "/api/v1/house/<id>", "fos_bot_", "maintain or edit_meta", "Same fields."),
    ("GET", "/api/v1/items/<id>/logs", "fos_bot_", "view", "Log on a vehicle, tool, or house thing."),
    ("POST", "/api/v1/items/<id>/logs", "fos_bot_", "maintain or edit_meta", "Body kind, title, notes, and optional reading, gallons, cost, happened_on."),
    ("POST", "/api/v1/items/<id>/trips", "fos_bot_", "scan, maintain, or edit_meta", "Start or end a trip on a vehicle. action start or end, and reading in miles."),
    ("POST", "/api/v1/items/<id>/oil", "fos_bot_", "maintain or edit_meta", "Oil on a vehicle or tool. Body needs (such as 5W-30), or fluids. A house thing has no oil record."),
    ("GET", "/api/v1/items/<id>/parts", "fos_bot_", "view", "Parts on a vehicle. Query limit, offset."),
    ("POST", "/api/v1/items/<id>/parts", "fos_bot_", "maintain or edit_meta", "Body name. Optional system, slot, brand, spec, part_number, status. Vehicles only."),
    ("GET", "/api/v1/photos", "fos_bot_", "view", "Photos. Query item_id, limit, offset."),
    ("GET", "/api/v1/photos/<id>", "fos_bot_", "view", "One photo."),
    ("GET", "/api/v1/find", "fos_bot_", "view", "Query q. Records and cases are included only with legal."),
    ("GET", "/api/v1/people", "fos_bot_", "not a child", "Names and roles. No passwords, no security inboxes."),
    ("GET", "/api/v1/ask", "fos_bot_", "not a child", "This bot's own Ask history. Query room, limit, offset."),
    ("GET", "/api/v1/activity", "fos_bot_", "override", "What happened. Query hours, limit, offset. newest_at is the last row stored, even when this window is empty. Leaders and admins."),
    ("GET", "/api/v1/vault", "either", "vault, never a child", "Card names only. No secrets."),
    ("GET", "/api/v1/vault/<id>", "either", "vault, never a child", "Open one card. A card this account cannot see is 404."),
)


_HOUSE_GUIDE = """\
This is a house key (fos_bot_). It can do the household work this account can already do on the pages. It does not raise the account. Read data.lines for every path, and the examples below for the JSON.

Sign in
1. POST /api/v1/auth/present with Authorization: Bearer and the login key. A 2FA key is emailed to the other inbox and lasts 1 hour. The response does not contain that key.
2. POST /api/v1/auth/exchange with the same login key as Bearer and the 2FA key as X-FOS-2FA. You receive fos_s1_ for 1 hour. Send that as Authorization: Bearer on every later call. The 2FA key is spent and is not sent again.
3. GET /api/v1/me is this account. account.role and account.can say what you may do. A false flag is 403 forbidden. A vault key on a house route is 403 scope_denied.
4. Send Content-Type: application/json. A missing required field is 400. A body key that is not a known field is ignored.
5. Lists take limit (default 50, max 200) and offset, and return count, total, and has_more.
6. DELETE is 405. Check a basket line off, mark a reminder done, or PATCH status to done.
7. When the session is finished, POST /api/v1/auth/reset emails a new login key and ends the session. POST /api/v1/auth/revoke ends the session and leaves the login key.

This key does not change people, passwords, leaders, the AI key, mail, or the Look theme. It does not write vault cards. Item photos (GET /api/v1/photos) are read-only here. A photo or PDF on a legal record is added with POST /api/v1/records/<id>/files. A card this account cannot see is 404.

Vehicle. POST /api/v1/vehicles needs name. Also year, make, model, vin, plate, color, current_mileage, oil_needs, oil_capacity, oil_type, filter_type, tire_size, notes, category, last_oil_change_date (YYYY-MM-DD), next_oil_due_date, oil_interval_miles, oil_interval_months. PATCH /api/v1/vehicles/<id> takes the same fields. Needs maintain.
Example: {"name":"Tundra","year":2006,"make":"Toyota","model":"Tundra","current_mileage":78000,"oil_needs":"5W-30"}

Tool. Use POST /api/v1/tools, not inventory. Needs name. Also category, notes, type, model, serial_number, asset_id, power_source, oil_needs, oil_capacity. PATCH /api/v1/tools/<id> takes the same fields. GET /api/v1/tools/<id> reads one. Needs maintain.
Example: {"name":"Gas generator","category":"power","type":"generator","model":"EU2200i","power_source":"gas","oil_needs":"10W-30","oil_capacity":"0.4 qt"}

House thing. POST /api/v1/house needs name. Also category and notes. The reply key is place. PATCH /api/v1/house/<id>. Needs maintain.
Example: {"name":"Pool pump","category":"pool","notes":"Hayward"}

Oil. POST /api/v1/items/<id>/oil on a vehicle or a tool. A house thing returns 400. Engine oil uses needs (or oil_needs), capacity, and in_it. Other fluids use fluid plus value, or a fluids object. Fluid keys: rear_diff, front_diff, transmission, transfer_case, coolant, brake_fluid, power_steering.
Example: {"needs":"5W-30","capacity":"6.5 qt","in_it":"5W-30"}
Example: {"fluid":"rear_diff","value":"75W-90"}
Example: {"fluids":{"transmission":"WS","coolant":"pink","transfer_case":"75W-90"}}

Part. Vehicles only. GET and POST /api/v1/items/<id>/parts. A tool or house thing is 404. Needs name. system is engine, electrical, electronics, exhaust, cooling, fuel, drivetrain, brakes, steering, tires, body, hvac, or other. slot examples: oil, oil_filter, air_filter, spark_plugs, battery. status is installed, spare, or retired. installed replaces the current part in that system and slot. Also brand, spec, part_number, model, serial_number, asset_id, installed_on, installed_mileage, notes, source, cost.
Example: {"name":"Oil filter","system":"engine","slot":"oil_filter","brand":"Wix","part_number":"57060","status":"installed"}

Stock. POST /api/v1/inventory is for groceries. Needs name. Also quantity, location, brand, size, unit, barcode, restock_threshold. PATCH can set expires_on as YYYY-MM-DD. item_type grocery or custom. A child may change the count and the use-by, not the name. A barcode already in the house is 409.

Basket. POST /api/v1/basket needs name. Also item_id, quantity_needed, reason, note. POST /api/v1/basket/<id>/done checks that line off. POST /api/v1/basket/<id>/match ties that line to stock. Body item_id.

Reminder. POST /api/v1/reminders needs title. type is bill, oil_change, filter, blades, hvac_filter, tires, battery, smoke, or custom. due_at is an ISO date-time. recurrence is 30d, 90d, 180d, 365d, 3000mi, 5000mi, 50h, or blank. Also item_id and notes. PATCH /api/v1/reminders/<id> takes those fields plus status open or done. POST /api/v1/reminders/<id>/done marks it done. Needs maintain.
Example: {"title":"Change the generator oil","type":"oil_change","due_at":"2026-11-01T09:00:00","recurrence":"50h"}

Log. POST /api/v1/items/<id>/logs. kind is miles, hours, fillup, repair, note, code, or trip. Also title, notes, happened_on (YYYY-MM-DD), reading, gallons, cost.
Trip. POST /api/v1/items/<id>/trips on a vehicle. action is start or end. reading is the odometer. start also takes origin and dest. end updates the miles. A house thing or a tool is 404.
Example: {"kind":"repair","title":"Spark plugs","notes":"gapped 0.044","happened_on":"2026-10-07","reading":78120}

Note. POST /api/v1/notes needs title. Also body, visibility (personal or household), item_id. Files: POST multipart field file to /api/v1/notes/<id>/files. GET /api/v1/files/<id> returns the bytes.

Legal paper. Needs legal on this account. POST /api/v1/records needs title. kind is citation, notice, warning, ticket, court, letter, or other. status is open, paid, contested, appealed, dismissed, or closed. Also agency, case_number, location, issued_on, due_on (YYYY-MM-DD), amount, body, outcome. PATCH /api/v1/records/<id> takes those fields. To add another photo or a paid receipt, POST multipart field file (or photo, or image) to /api/v1/records/<id>/files. Optional caption. The same file fields are accepted on the PATCH. GET /api/v1/records/<id>/files lists them. GET /api/v1/records/<id>/files/<file_id> returns the bytes. Adding a file does not replace the ones already there.
Example: {"title":"Speeding ticket","kind":"ticket","agency":"City","due_on":"2026-11-01","amount":"150.00"}

Case. Needs legal. POST /api/v1/cases needs title. status is open or closed. summary is optional. The case number is assigned. PATCH /api/v1/cases/<id> takes the same fields. POST /api/v1/cases/<id>/followups adds a note, link, or email. A photo or PDF belongs on the record, not as a file follow-up. PATCH /api/v1/records/<id> with case_id ties a paper on, or null pulls it off. GET /api/v1/cases/<id> reads one.
Example: {"title":"The ticket","status":"open","summary":"Follow the paper."}

Find. GET /api/v1/find?q= . Records and cases are included only when this account has legal.

People. GET /api/v1/people. Names and roles. Not a child. No passwords and no security inboxes.

Ask history. GET /api/v1/ask. This bot's own turns. Not a child.

Activity. GET /api/v1/activity. Leaders and admins. Query hours, limit, offset.

Vault read. GET /api/v1/vault lists names only. GET /api/v1/vault/<id> opens one card when this account can use the vault. Never a child. This key cannot create or change a card.
"""

_VAULT_GUIDE = """\
This is a vault key (fos_vault_). It opens password cards this account is allowed to see. It cannot change the house, and it cannot create or change a card.

Sign in
1. POST /api/v1/auth/present with Authorization: Bearer and the login key. A 2FA key is emailed to the other inbox and lasts 1 hour. The response does not contain that key.
2. POST /api/v1/auth/exchange with the same login key as Bearer and the 2FA key as X-FOS-2FA. You receive fos_s1_ for 1 hour. Send that as Authorization: Bearer on every later call. The 2FA key is spent and is not sent again.
3. GET /api/v1/me is this account. A child never opens the vault. account.can.vault false is 403 forbidden.
4. GET /api/v1/vault lists card names only. No passwords and no account numbers. GET /api/v1/vault/<id> opens one card. A card this account cannot see is 404, the same as a card that is not there.
5. DELETE is 405. A house route is 403 scope_denied. Lists take limit (default 50, max 200) and offset.
6. When the session is finished, POST /api/v1/auth/reset emails a new login key and ends the session. POST /api/v1/auth/revoke ends the session and leaves the login key.
"""

_HOUSE_EXAMPLES = (
    {
        "method": "POST",
        "path": "/api/v1/vehicles",
        "body": {"name": "Tundra", "year": 2006, "make": "Toyota", "model": "Tundra", "oil_needs": "5W-30"},
        "says": "Add a vehicle. Needs maintain.",
    },
    {
        "method": "POST",
        "path": "/api/v1/tools",
        "body": {"name": "Gas generator", "oil_needs": "10W-30", "oil_capacity": "0.4 qt"},
        "says": "Add a tool. Do not use inventory for this.",
    },
    {
        "method": "POST",
        "path": "/api/v1/house",
        "body": {"name": "Pool pump", "category": "pool"},
        "says": "Add a house thing. The reply key is place.",
    },
    {
        "method": "POST",
        "path": "/api/v1/items/<id>/oil",
        "body": {"needs": "5W-30", "capacity": "6.5 qt"},
        "says": "Save engine oil on a vehicle or tool.",
    },
    {
        "method": "POST",
        "path": "/api/v1/items/<id>/oil",
        "body": {"fluid": "rear_diff", "value": "75W-90"},
        "says": "Save one non-engine fluid.",
    },
    {
        "method": "POST",
        "path": "/api/v1/items/<id>/parts",
        "body": {"name": "Oil filter", "system": "engine", "slot": "oil_filter", "status": "installed"},
        "says": "Put a part on a vehicle.",
    },
    {
        "method": "POST",
        "path": "/api/v1/inventory",
        "body": {"name": "Oat milk", "quantity": 2, "location": "fridge", "unit": "each"},
        "says": "Add a grocery.",
    },
    {
        "method": "POST",
        "path": "/api/v1/basket",
        "body": {"name": "Oat milk", "quantity_needed": 1},
        "says": "Add a shopping line. POST /basket/<id>/done checks it off.",
    },
    {
        "method": "POST",
        "path": "/api/v1/reminders",
        "body": {"title": "Change the generator oil", "type": "oil_change", "recurrence": "50h"},
        "says": "Add a reminder. PATCH can set status to done.",
    },
    {
        "method": "POST",
        "path": "/api/v1/records",
        "body": {"title": "Speeding ticket", "kind": "ticket", "due_on": "2026-11-01", "amount": "150.00"},
        "says": "File legal paper. Needs legal. Add a later photo with POST /api/v1/records/<id>/files.",
    },
    {
        "method": "POST",
        "path": "/api/v1/records/<id>/files",
        "body": None,
        "says": "Multipart field file. Adds a photo or PDF to a record already filed, such as a paid receipt. Optional caption. Needs legal.",
    },
    {
        "method": "POST",
        "path": "/api/v1/cases",
        "body": {"title": "The ticket", "status": "open", "summary": "Follow the paper."},
        "says": "Open a case. Needs legal.",
    },
    {
        "method": "POST",
        "path": "/api/v1/notes",
        "body": {"title": "Filter size", "body": "16x20x1", "visibility": "household"},
        "says": "Add a note.",
    },
)

_VAULT_EXAMPLES = (
    {
        "method": "GET",
        "path": "/api/v1/vault",
        "body": None,
        "says": "Card names only. No secrets.",
    },
    {
        "method": "GET",
        "path": "/api/v1/vault/<id>",
        "body": None,
        "says": "Open one card. A card this account cannot see is 404.",
    },
)


def call_allowed(user, needs: str) -> bool:
    """Whether this account may try the call. The key still cannot raise the role."""
    from app.utils.permissions import can, role_of

    text = (needs or "").strip().lower()
    if user is None:
        return False
    child = role_of(user) == "child"
    if "never a child" in text or "not a child" in text:
        if child:
            return False
    if "override" in text:
        return can("override", user)
    checks = []
    if "legal" in text:
        checks.append(can("legal", user))
    if "maintain" in text:
        checks.append(can("maintain", user))
    if "edit_meta" in text:
        checks.append(can("edit_meta", user))
    if "edit_grocery" in text or "groceries" in text:
        checks.append(can("edit_grocery", user))
    if "scan" in text:
        checks.append(can("scan", user))
    if "vault" in text:
        checks.append(can("vault", user) and not child)
    if "view" in text and not checks:
        checks.append(can("view", user))
    if not checks:
        return True
    return any(checks)


def _for_this_key(scope: str, call_scope: str) -> bool:
    if call_scope in ("either", "login"):
        return True
    return call_scope == (scope or "")


def help_for(scope: str) -> dict:
    """Warm note plus one labeled line per call this key can try."""
    scope = scope if scope in (SCOPE_ALL, SCOPE_VAULT) else SCOPE_ALL
    calls = []
    lines = []
    for method, path, call_scope, needs, what in HELP_CALLS:
        mine = _for_this_key(scope, call_scope)
        if not mine:
            continue
        row = {
            "method": method,
            "path": path,
            "needs": needs,
            "what": what,
        }
        calls.append(row)
        if needs:
            lines.append(f"{method} {path} | needs: {needs} | {what}")
        else:
            lines.append(f"{method} {path} | {what}")
    return {
        "greeting": "Hello. I'm glad you're looking. The lines below are the calls this key can make.",
        "authorization": "Bearer fos_s1_…",
        "you": "GET /api/v1/me",
        "you_same_as": "GET /api/v1/whoami",
        "helper": "GET /api/v1/helper",
        "scope": scope,
        "wrong_path": "A path that is not in this list is 404. /api/v1/me is you. A role that cannot do the call is 403 forbidden. The other key prefix is 403 scope_denied.",
        "no_delete": "DELETE is 405.",
        "list_query": "Lists take limit (default 50, max 200) and offset, and return count, total, and has_more.",
        "lines": lines,
        "calls": calls,
        "guide": _VAULT_GUIDE if scope == SCOPE_VAULT else _HOUSE_GUIDE,
        "examples": list(_VAULT_EXAMPLES if scope == SCOPE_VAULT else _HOUSE_EXAMPLES),
    }
