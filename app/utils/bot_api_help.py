"""The Family bot route map. GET /api/v1/helper returns this.

A path that is not listed here is 404. /api/v1/me is this account (whoami),
not a person record.
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
    ("POST", "/api/v1/inventory", "fos_bot_", "scan, groceries, or maintain", "Body name. Optional item_type, quantity, barcode, location, brand, size, unit."),
    ("PATCH", "/api/v1/inventory/<id>", "fos_bot_", "scan, groceries, or maintain", "Same fields. A child may change stock, not the name."),
    ("GET", "/api/v1/records", "fos_bot_", "legal", "Legal paper. Query status, limit, offset."),
    ("GET", "/api/v1/records/<id>", "fos_bot_", "legal", "One record."),
    ("POST", "/api/v1/records", "fos_bot_", "legal", "Body title. Optional kind, status, agency, case_number, location, body."),
    ("PATCH", "/api/v1/records/<id>", "fos_bot_", "legal", "Same fields."),
    ("GET", "/api/v1/cases", "fos_bot_", "legal", "Cases. Query limit, offset."),
    ("GET", "/api/v1/basket", "fos_bot_", "view", "Shopping basket. Query status=open."),
    ("POST", "/api/v1/basket", "fos_bot_", "scan or edit_grocery", "Body name. Optional item_id, reason, note."),
    ("POST", "/api/v1/basket/<id>/done", "fos_bot_", "scan or edit_grocery", "Check one line off."),
    ("GET", "/api/v1/reminders", "fos_bot_", "view", "Due items. Query status, limit, offset."),
    ("POST", "/api/v1/reminders", "fos_bot_", "maintain", "Body title. Optional type, due_at, item_id, recurrence, notes."),
    ("POST", "/api/v1/reminders/<id>/done", "fos_bot_", "maintain", "Mark one done."),
    ("GET", "/api/v1/tools", "fos_bot_", "view", "Tools."),
    ("GET", "/api/v1/house", "fos_bot_", "view", "House things."),
    ("GET", "/api/v1/items/<id>/logs", "fos_bot_", "view", "Log on a vehicle, tool, or house thing."),
    ("POST", "/api/v1/items/<id>/logs", "fos_bot_", "maintain or edit_meta", "Body kind, title, notes, and optional reading, gallons, cost, happened_on."),
    ("GET", "/api/v1/photos", "fos_bot_", "view", "Photos. Query item_id, limit, offset."),
    ("GET", "/api/v1/photos/<id>", "fos_bot_", "view", "One photo."),
    ("GET", "/api/v1/find", "fos_bot_", "view", "Query q. Records and cases are included only with legal."),
    ("GET", "/api/v1/people", "fos_bot_", "not a child", "Names and roles. No passwords, no security inboxes."),
    ("GET", "/api/v1/ask", "fos_bot_", "not a child", "This bot's own Ask history. Query room, limit, offset."),
    ("GET", "/api/v1/activity", "fos_bot_", "override", "What happened. Query hours, limit, offset. Leaders and admins."),
    ("GET", "/api/v1/vault", "either", "vault, never a child", "Card names only. No secrets."),
    ("GET", "/api/v1/vault/<id>", "either", "vault, never a child", "Open one card. A card this account cannot see is 404."),
)


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
    }
