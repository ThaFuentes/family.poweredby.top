# Family OS: Maya bot API (2026-10-04)

Built on the existing `/api/v1` bot API. Maya's routes sit at **`/api/v1/maya/...`** on the same blueprint, so they
inherit HTTPS-only, the `fos_s1_` session, scopes, DB rate limits, the CSRF/tenant exemption for `/api/v1/` and the
per-call `bot_api_audit` row.

## Sign-in (unchanged)
1. `POST /api/v1/auth/present` with the login key, then `POST /api/v1/auth/exchange` with the emailed code → `fos_s1_…` session.
2. `POST /api/v1/auth/reset` (already existed): emails a new non-expiring login key to the login inbox, kills the old key and session. The raw key is never in the response.
3. `GET /api/v1/maya/capabilities`: every route, its permission, whether it is on right now, `expires_at` / `remaining` / `timer_required` per permission, plus the hard limits.

## How every Maya call is checked
1. The session's bot user must be the household's designated Maya (`maya_bot_accounts`; seeded to household `fuentes`, bot `grokbots`; the owner can change it).
2. The route's permission must be on **right now**. It is read from the DB on every call (`maya_bot_permissions`). If a row is missing, the default applies. A switch whose timer has passed (`expires_at`) counts as OFF immediately.
3. For the request, Maya is bound as `current_user`, so the shared services (`app/services/*`, the same code the web pages call) record Happened rows as Maya, and results show in the app as done by Maya.
4. Writes add one `household_activity` row and one `bot_api_audit` row (`maya.write`). Denials are audited as `maya.denied`.

Error codes: `not_maya`, `permission_off` (with `permission`), `hard_limit`, plus the normal bot API errors.

## Owner checklist: `/maya-permissions` (People page → "Maya permissions" tile)
- Only a signed-in, non-bot household leader can open it. Bots get a 403, and Maya cannot reach it in any way.
- Lets the owner pick which BOT account is Maya.
- Every permission has its own checkbox with a plain-English line, grouped by area, with "All on / All off" per group.
- **High risk** switches are red-badged and default OFF. Turning one on (or lengthening its timer) needs the owner's password or a 2FA code. Without one, the switch stays off and the page says so.
- **Auto-off timer** per switch: Hours / Days / Weeks / Months + a number (months are counted as 30 days; the cap is 366 days). Normal switches default to "no expiry". High-risk switches *must* have a timer; it defaults to 24 hours. Remaining time is shown next to each switch, and an untouched running timer is kept ("keep (5h 12m left)").
- Expired switches are OFF on the next check. A lazy cleanup flips the row and writes `maya_bot_perm_log.confirmed_with='auto-expired'` plus a Happened line `maya.perms.expired`. There is also a cron script: `scripts/maya_expire_permissions.py`.
- Every change is logged in `maya_bot_perm_log` (owner, perm, old/new, high_risk, how it was confirmed, IP) and in Happened (`maya.perms`). The page shows the latest 40 changes and the recycle bin with "Put back" buttons.

## Hard limits (in code, no switch lifts them)
- Maya cannot open or change her checklist or pick who Maya is. `save_state` refuses bots, and `/activity/<id>/undo` refuses `maya.perms*` rows.
- Maya never gets raw secrets: no keys, 2FA secrets, password hashes, decrypted vault passwords, mail/AI keys, or calendar link. `/people` has no emails. `/vault` returns card names and kinds only.
- Maya cannot change her own account or role. `people.*` refuses self, leaders, and bots. Password resets go to the person's inbox, and Maya never sees the link.
- Removals go to a recycle bin (`household_trash`: raw row snapshots plus files archived outside the docroot in `FAMILY_ARCHIVE_DIR`, default `~/familyos_file_archive`, 0700). Replaced files are versioned (`household_file_versions`). Purging needs the high-risk `trash.purge` plus `{"confirm":"PURGE"}`.
- Uploads: file type is checked by magic bytes (JPG/PNG/WEBP/GIF/PDF), size is capped (`MAYA_UPLOAD_MAX_BYTES`, default 10 MB), names are cleaned, and EXIF/GPS is stripped by re-encoding.

## Not built (listed, always off)
`people.create` (a new login shows its password once, so it stays on the People page) and `settings.security`.

## Routes

DATABASE_URI successfully built from .env MYSQL_* variables
 Host: 127.0.0.1:9 | DB: n | User: n
dbconnector.py fully loaded - STABLE pool settings (recycle=120 + pre_ping + reset_on_return + checkout listener)
[2026-10-04 12:45:11] WARNING: get_db_connection not found in connect_db.py - using JSON fallback only
PATH FIX: Added /home/clarkkent/pyprojects/family.poweredby.top
PATH FIX: Added /home/clarkkent/pyprojects/family.poweredby.top/poweredbytop
Current dir: /home/clarkkent/pyprojects/family.poweredby.top
sys.path top 3: ['/home/clarkkent/pyprojects/family.poweredby.top/poweredbytop/security_build_db', '/home/clarkkent/pyprojects/family.poweredby.top/poweredbytop', '/home/clarkkent/pyprojects/family.poweredby.top']
SUCCESS: Imported get_security_db from poweredbytop.models.connect_db
=== POWEREDBYTOP SECURITY BUILD ORCHESTRATOR STARTED ===
poweredbytop/security_build_db/security_build_db.py - 100% fresh rebuild loaded (clean, no unicode, robust path fixing)
=== STARTING FULL TABLE BUILD ===
[2026-10-04 12:45:14] [DB ERROR] All 4 retries failed: (2003, "Can't connect to MySQL server on '127.0.0.1' ([Errno 111] Connection refused)")
CRITICAL ERROR: get_security_db() returned None
[security] Package loading...
[security] Headers ON
[security] Helpers ON
[security] XSS Sanitizer ON
[security] CSRF Protection ON
[security] Device prints ON
[security] Decorators ON
[security] Rate Limiting ON
[security] All features loaded: Headers, Helpers, XSS Sanitizer, CSRF, DevicePrints, Decorators, Rate Limiting
[2026-10-04 12:45:16] [DB ERROR] All 4 retries failed: (2003, "Can't connect to MySQL server on '127.0.0.1' ([Errno 111] Connection refused)")
[BUILD-DB] engine ping not attached: Working outside of application context.

This typically means that you attempted to use functionality that needed
the current application. To solve this, set up an application context
with app.app_context(). See the documentation for more information.
| Method | Path | Permission | What |
|---|---|---|---|
| GET | `/api/v1/maya/capabilities` | `-` | Every Maya route, its permission, and whether it is on now. |
| GET | `/api/v1/maya/items` | `(by item type)` | List items. ?type=grocery/custom/vehicle/tool/house, ?q=, ?removed=1. Needs <area>.read. |
| GET | `/api/v1/maya/items/<int:item_id>` | `(by item type)` | One item (any type). Needs <area>.read. |
| POST | `/api/v1/maya/items` | `(by item type)` | Add an item: {name, item_type, ...same fields as the Add form}. lookup=true runs product/VIN lookup. Needs <area>.create. |
| PATCH | `/api/v1/maya/items/<int:item_id>` | `(by item type)` | Edit an item. Only the keys you send change. Needs <area>.edit. |
| POST | `/api/v1/maya/items/<int:item_id>/stock` | `inventory.stock` | {action: consume/restock/plus/minus/need_more/freeze/fridge, amount, place}. Groceries only. |
| POST | `/api/v1/maya/items/<int:item_id>/reading` | `vehicles.reading` | {reading}: odometer miles (vehicle) or hours (tool). Writes the log row. |
| DELETE | `/api/v1/maya/items/<int:item_id>` | `(by item type)` | Remove an item (soft: Happened can put it back). Needs <area>.delete. |
| POST | `/api/v1/maya/items/<int:item_id>/restore` | `(by item type)` | Put a removed item back. Needs <area>.restore. |
| GET | `/api/v1/maya/items/<int:item_id>/logs` | `logs.read` | Log rows on a vehicle, tool or house. |
| POST | `/api/v1/maya/items/<int:item_id>/logs` | `logs.create` | {kind: miles/hours/fuel/repair/oil/note/code/..., happened_on, reading, gallons, cost, title, notes}. |
| DELETE | `/api/v1/maya/logs/<int:log_id>` | `logs.delete` | Remove a log row (recycle bin). |
| GET | `/api/v1/maya/items/<int:item_id>/parts` | `parts.read` | Parts on a vehicle or house slot. ?all=1 includes retired. |
| POST | `/api/v1/maya/items/<int:item_id>/parts` | `parts.create` | {system, slot, name, brand, spec, status, installed_on, installed_mileage, part_number, model, serial_number, asset_id, source, cost, warranty_until, notes, replace_current}. |
| PATCH | `/api/v1/maya/parts/<int:part_id>` | `parts.edit` | Edit a part. Only keys you send change. |
| POST | `/api/v1/maya/parts/<int:part_id>/retire` | `parts.retire` | Take a part off (Happened can put it back). |
| POST | `/api/v1/maya/parts/<int:part_id>/restore` | `parts.restore` | Put a retired part back on. |
| GET | `/api/v1/maya/basket` | `basket.read` | Basket lines. ?status=open/done/all. |
| POST | `/api/v1/maya/basket` | `basket.create` | {names: [..] or 'a, b', note, item_id, quantity}. |
| POST | `/api/v1/maya/basket/<int:entry_id>/check` | `basket.check` | Got it: check off (restocks a matched item). |
| POST | `/api/v1/maya/basket/<int:entry_id>/reopen` | `basket.check` | Put a checked-off line back on the list. |
| DELETE | `/api/v1/maya/basket/<int:entry_id>` | `basket.delete` | Take a line off (recycle bin; stock unchanged). |
| GET | `/api/v1/maya/reminders` | `reminders.read` | Reminders / calendar items. ?status=open/done/all. |
| POST | `/api/v1/maya/reminders` | `reminders.create` | {title, type, due_at (ISO), recurrence, notify_via, linked_item_id, notes, announce}. Emails/calendar like the Due page. |
| PATCH | `/api/v1/maya/reminders/<int:rid>` | `reminders.edit` | Edit a reminder. Only keys you send change. |
| POST | `/api/v1/maya/reminders/<int:rid>/done` | `reminders.complete` | Mark done. |
| POST | `/api/v1/maya/reminders/<int:rid>/reopen` | `reminders.complete` | Open again. |
| DELETE | `/api/v1/maya/reminders/<int:rid>` | `reminders.delete` | Remove (recycle bin). |
| GET | `/api/v1/maya/notes` | `notes.read` | Household notes + Maya's own. ?item_id= |
| GET | `/api/v1/maya/notes/<int:note_id>` | `notes.read` | One note with its files. |
| POST | `/api/v1/maya/notes` | `notes.create` | {title, body, visibility: personal/household (default household), item_id}. |
| PATCH | `/api/v1/maya/notes/<int:note_id>` | `notes.edit` | Edit a note Maya may edit (hers, or any if her account is admin). |
| DELETE | `/api/v1/maya/notes/<int:note_id>` | `notes.delete` | Remove a note and its files (recycle bin). |
| GET | `/api/v1/maya/items/<int:item_id>/photos` | `files.read` | Photos and receipts on an item. |
| GET | `/api/v1/maya/notes/<int:note_id>/files` | `files.read` | Files on a note. |
| GET | `/api/v1/maya/files/<kind>/<int:row_id>` | `files.read` | Download a file. kind = note_file / photo / legal_file. |
| POST | `/api/v1/maya/notes/<int:note_id>/files` | `files.upload` | multipart 'file' (+ caption). JPG/PNG/WEBP/GIF/PDF, size-capped, EXIF stripped. |
| POST | `/api/v1/maya/items/<int:item_id>/photos` | `files.upload` | multipart 'file' (+ caption, kind photo/receipt/serial/connector, warranty_until). EXIF stripped. |
| PUT | `/api/v1/maya/files/<kind>/<int:row_id>` | `files.replace` | Replace the bytes (multipart 'file'). The old version is archived outside the docroot. |
| DELETE | `/api/v1/maya/files/<kind>/<int:row_id>` | `files.delete` | Remove a file (row to recycle bin, bytes archived outside the docroot). |
| GET | `/api/v1/maya/files/<kind>/<int:row_id>/versions` | `files.read` | Archived old versions of a file. |
| POST | `/api/v1/maya/files/<kind>/<int:row_id>/versions/<int:version_id>/restore` | `files.restore` | Make an archived version current again (the current one is archived first). |
| GET | `/api/v1/maya/records` | `records.read` | Records (notices, tickets, letters). |
| GET | `/api/v1/maya/records/<int:record_id>` | `records.read` | One record with files. |
| POST | `/api/v1/maya/records` | `records.create` | {title, kind, status, agency, case_number, location, issued_on, due_on, body, outcome, kind_detail}. amount needs records.amounts. |
| PATCH | `/api/v1/maya/records/<int:record_id>` | `records.edit` | Edit a record. Only keys you send change. amount needs records.amounts. |
| DELETE | `/api/v1/maya/records/<int:record_id>` | `records.delete` | Remove a record and its files (recycle bin). |
| POST | `/api/v1/maya/records/<int:record_id>/files` | `files.upload` | Attach a photo/PDF to a record (needs records.edit too). |
| GET | `/api/v1/maya/cases` | `cases.read` | Cases. |
| GET | `/api/v1/maya/cases/<int:case_id>` | `cases.read` | One case with records and follow-ups. |
| POST | `/api/v1/maya/cases` | `cases.create` | {title, summary, record_id}. |
| PATCH | `/api/v1/maya/cases/<int:case_id>` | `cases.edit` | {title, status: open/closed, summary, attach_record_id, detach_record_id}. |
| POST | `/api/v1/maya/cases/<int:case_id>/followups` | `cases.followup` | {kind: note/link/email, title, body, url, email_from}. |
| DELETE | `/api/v1/maya/followups/<int:followup_id>` | `cases.delete` | Remove a follow-up (recycle bin). |
| GET | `/api/v1/maya/trash` | `trash.read` | Recycle bin. ?state=live/restored/purged/all (default live). |
| POST | `/api/v1/maya/trash/<int:trash_id>/restore` | `trash.restore` | Put a removed row (and its files) back. |
| DELETE | `/api/v1/maya/trash/<int:trash_id>` | `trash.purge` **HIGH RISK** | HIGH RISK. Permanently delete one recycle-bin entry and its archived files. Body {confirm: 'PURGE'}. |
| GET | `/api/v1/maya/activity` | `activity.read` | Happened (household activity). ?hours=48 |
| POST | `/api/v1/maya/activity/<int:aid>/undo` | `activity.undo` | The Put back button on Happened. |
| GET | `/api/v1/maya/find` | `search.read` | Search. ?q=&scope=all/items/notes/parts/records |
| GET | `/api/v1/maya/ask` | `ask.read` | Maya's own Ask turns. ?room= |
| GET | `/api/v1/maya/people` | `people.read` | Members: name, username, role, leader/bot flags. No emails, no keys. |
| POST | `/api/v1/maya/people/<int:user_id>/role` | `people.role` **HIGH RISK** | HIGH RISK. {role: admin/member/child}. Never Maya herself, never leader flags. |
| POST | `/api/v1/maya/people/<int:user_id>/remove` | `people.remove` **HIGH RISK** | HIGH RISK. Take someone off People (Put back on Happened). Never Maya, never the last leader. |
| POST | `/api/v1/maya/people/<int:user_id>/reset-password` | `people.reset_password` **HIGH RISK** | HIGH RISK. Email the person a reset link. Maya never sees the link or a password. |
| PATCH | `/api/v1/maya/settings/household` | `settings.household` **HIGH RISK** | HIGH RISK. {name, places: 'Kitchen, Garage, ...'}. |
| PATCH | `/api/v1/maya/settings/reminders` | `settings.reminders` **HIGH RISK** | HIGH RISK. {reminders_via: email/calendar/both}. |
| GET | `/api/v1/maya/vault` | `vault.read` **HIGH RISK** | HIGH RISK. Vault card names/kinds only. Never passwords or numbers. |

## Permission catalog

| Group | id | Label | Default | High risk | Built |
|---|---|---|---|---|---|
| Inventory | `inventory.read` | See inventory items | ON |  | yes |
| Inventory | `inventory.create` | Add inventory items | ON |  | yes |
| Inventory | `inventory.edit` | Edit inventory items | ON |  | yes |
| Inventory | `inventory.delete` | Remove inventory items | ON |  | yes |
| Inventory | `inventory.restore` | Put back inventory items | ON |  | yes |
| Inventory | `inventory.stock` | Change counts | ON |  | yes |
| Basket | `basket.read` | See basket lines | ON |  | yes |
| Basket | `basket.create` | Add basket lines | ON |  | yes |
| Basket | `basket.edit` | Edit basket lines | ON |  | yes |
| Basket | `basket.delete` | Remove basket lines | ON |  | yes |
| Basket | `basket.restore` | Put back basket lines | ON |  | yes |
| Basket | `basket.check` | Check off / reopen basket lines | ON |  | yes |
| Vehicles | `vehicles.read` | See vehicles | ON |  | yes |
| Vehicles | `vehicles.create` | Add vehicles | ON |  | yes |
| Vehicles | `vehicles.edit` | Edit vehicles | ON |  | yes |
| Vehicles | `vehicles.delete` | Remove vehicles | ON |  | yes |
| Vehicles | `vehicles.restore` | Put back vehicles | ON |  | yes |
| Vehicles | `vehicles.reading` | Update miles / hours | ON |  | yes |
| Tools | `tools.read` | See tools | ON |  | yes |
| Tools | `tools.create` | Add tools | ON |  | yes |
| Tools | `tools.edit` | Edit tools | ON |  | yes |
| Tools | `tools.delete` | Remove tools | ON |  | yes |
| Tools | `tools.restore` | Put back tools | ON |  | yes |
| House file | `house.read` | See house things | ON |  | yes |
| House file | `house.create` | Add house things | ON |  | yes |
| House file | `house.edit` | Edit house things | ON |  | yes |
| House file | `house.delete` | Remove house things | ON |  | yes |
| House file | `house.restore` | Put back house things | ON |  | yes |
| Maintenance & logs | `logs.read` | See log entries | ON |  | yes |
| Maintenance & logs | `logs.create` | Add log entries | ON |  | yes |
| Maintenance & logs | `logs.delete` | Remove log entries | ON |  | yes |
| Maintenance & logs | `logs.restore` | Put back log entries | ON |  | yes |
| Parts & equipment | `parts.read` | See parts | ON |  | yes |
| Parts & equipment | `parts.create` | Add parts | ON |  | yes |
| Parts & equipment | `parts.edit` | Edit parts | ON |  | yes |
| Parts & equipment | `parts.retire` | Take parts off | ON |  | yes |
| Parts & equipment | `parts.restore` | Put parts back on | ON |  | yes |
| Reminders & calendar | `reminders.read` | See reminders | ON |  | yes |
| Reminders & calendar | `reminders.create` | Add reminders | ON |  | yes |
| Reminders & calendar | `reminders.edit` | Edit reminders | ON |  | yes |
| Reminders & calendar | `reminders.delete` | Remove reminders | ON |  | yes |
| Reminders & calendar | `reminders.restore` | Put back reminders | ON |  | yes |
| Reminders & calendar | `reminders.complete` | Mark reminders done / reopen | ON |  | yes |
| Notes | `notes.read` | See notes | ON |  | yes |
| Notes | `notes.create` | Add notes | ON |  | yes |
| Notes | `notes.edit` | Edit notes | ON |  | yes |
| Notes | `notes.delete` | Remove notes | ON |  | yes |
| Notes | `notes.restore` | Put back notes | ON |  | yes |
| Files & photos | `files.read` | Open files and photos | ON |  | yes |
| Files & photos | `files.upload` | Upload files and photos | ON |  | yes |
| Files & photos | `files.replace` | Replace files and photos | ON |  | yes |
| Files & photos | `files.delete` | Remove files and photos | ON |  | yes |
| Files & photos | `files.restore` | Restore old file versions | ON |  | yes |
| Records & cases | `records.read` | See records | ON |  | yes |
| Records & cases | `records.create` | Add records | ON |  | yes |
| Records & cases | `records.edit` | Edit records | ON |  | yes |
| Records & cases | `records.delete` | Remove records | ON |  | yes |
| Records & cases | `records.restore` | Put back records | ON |  | yes |
| Records & cases | `cases.read` | See cases | ON |  | yes |
| Records & cases | `cases.create` | Open cases | ON |  | yes |
| Records & cases | `cases.edit` | Edit cases | ON |  | yes |
| Records & cases | `cases.followup` | Add case follow-ups | ON |  | yes |
| Records & cases | `cases.delete` | Remove case follow-ups | ON |  | yes |
| Activity log | `activity.read` | See Happened | ON |  | yes |
| Activity log | `activity.undo` | Undo on Happened | ON |  | yes |
| Recycle bin | `trash.read` | See the recycle bin | ON |  | yes |
| Recycle bin | `trash.restore` | Restore from the recycle bin | ON |  | yes |
| Search | `search.read` | Search the house | ON |  | yes |
| People | `people.read` | See household members | ON |  | yes |
| Ask | `ask.read` | See Maya's own Ask history | ON |  | yes |
| People (high risk) | `people.create` | Add people | OFF | yes | no (always off) |
| People (high risk) | `people.role` | Change roles | OFF | yes | yes |
| People (high risk) | `people.remove` | Remove people | OFF | yes | yes |
| People (high risk) | `people.reset_password` | Send password resets | OFF | yes | yes |
| Settings (high risk) | `settings.household` | Rename household / rooms | OFF | yes | yes |
| Settings (high risk) | `settings.reminders` | Reminder delivery | OFF | yes | yes |
| Settings (high risk) | `settings.security` | Security & mail settings | OFF | yes | no (always off) |
| Vault (high risk) | `vault.read` | See vault card names | OFF | yes | yes |
| Recycle bin (high risk) | `trash.purge` | Permanently delete | OFF | yes | yes |
| Money (high risk) | `records.amounts` | Edit amounts on records | OFF | yes | yes |

## Server steps (not done; no deploy was run)
1. Pull the branch on HostM, then `pip install -r requirements.txt` (no new packages; Pillow is already used).
2. Run `migrations/2026-10-04_maya_bot_api.sql` (or let boot-time builddb create the tables).
3. Optional: set `FAMILY_ARCHIVE_DIR` to a folder OUTSIDE public_html (the default is `~/familyos_file_archive`) and `MAYA_UPLOAD_MAX_BYTES`.
4. Add cron: `*/15 * * * * cd ~/family.poweredby.top && .venv/bin/python scripts/maya_expire_permissions.py`.
5. Restart Passenger. As the owner, open People → Maya permissions, check the Maya account, and review the switches.

