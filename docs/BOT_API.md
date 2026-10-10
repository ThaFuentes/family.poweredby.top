# Family OS Bot API — `/api/v1`

Machine access for the bots that drive a household. Bot accounts only, HTTPS
only, read and write scoped by the key itself, and every call audited.

HTTPS includes the scheme ProxyFix copies from `X-Forwarded-Proto`, and a
`CF-Visitor` scheme of `https`. A later hop may append `http` for its own
clear-text connection; `https` anywhere in that chain still counts. Plain
HTTP with neither is refused. The security pipeline, CSRF, and cross-site
checks do not block, ban, or rate-limit `/api/v1/`.

---

## The shape of it

A key's **prefix is its scope**. There is no separate permission toggle:

| Prefix | Scope | Access |
|---|---|---|
| `fos_bot_…` | House | Household content this account is allowed to open |
| `fos_vault_…` | Vault | Read-only vault. Cannot change the house |

A `fos_vault_` key cannot reach a house route. A `fos_bot_` key can read the
vault only when that bot account can use the vault in the app (never a child).

The key does not raise the account. `GET /api/v1/whoami` returns `account.role`
and `account.can`. A turned-down ability is `403` with `code: forbidden`. A
key prefix that cannot touch the route is `403` with `code: scope_denied`.

House reads a member can use also include basket, reminders, tools, house,
item logs, oil, parts, photos, find, people, cases, and that bot's own Ask
history. Writes follow the same permissions as the page: a member can save a
tool, a house thing, oil, a part, a reminder, and a case; a child can check
the basket and cannot file a legal record or edit a vehicle. Leaders can read
`GET /api/v1/activity`. There is still no delete. `GET /api/v1/helper` returns
`data.lines` (the paths) and `data.guide` (the field-by-field help for this
key).

## One login key, one 2FA key

Each scope has one login key. It does not expire.

| Key | Goes to | Lifetime | Used as |
|---|---|---|---|
| Login key | the bot's login email (`users.email`) | does not expire | `Authorization: Bearer` on present and exchange |
| 2FA key | the bot's 2FA email (`users.security_email`) | 1 hour | `X-FOS-2FA`, once |

The 2FA inbox must be a different address from the login inbox. The bot
account also needs 2FA turned on and a separate reset inbox, or no key can be
issued at all.

A **vault** key lives on its own bot account with its own three inboxes, so it
is completely independent of the house bot's key.

### Why there are two, and what "reset" does

The login key alone is not enough to use the API. Presenting it emails a
fresh 2FA key to the other inbox. That key lasts one hour and is spent when
the session opens, so a leak of one inbox is not a working credential.

Only the SHA-256 hash of each key is stored. A resend cannot repeat the old
login key. `Send login key`, `Reset`, and `Resend` on People all rotate it
and kill its sessions.

## Getting keys

**A household leader**, on People → the bot's sheet → *Bot API*:

- `Send keys` — first pair for that scope
- `Reset` — new pair, old pair dead
- `Resend` — new pair, old pair dead (same thing; the label says why)

The login key is shown once in the copy window and emailed to the login
inbox. The 2FA key is never shown there. It is emailed only when the bot
presents the login key.

**The bot itself**, from its own dashboard (`/`), proved by its current
password or a fresh authenticator code — exactly like the password reset card.
A bot can never see its own keys on that page; it can only ask for new ones.

**What this key can do** is the same guide as `GET /api/v1/helper`, as a page.
The bot opens `/bot-api/guide`. A leader opens `/members/<id>/bot-api/guide`
from that bot's People sheet. House key and vault key are two views of the
same page. Each call is marked from that account's role: this account can, or
this account cannot. A person who is not that bot gets 404 on `/bot-api/guide`.
The page shows no secrets.

## Using it

### 1. Present the login key, then exchange

```bash
curl -X POST https://family.poweredby.top/api/v1/auth/present \
  -H "Authorization: Bearer fos_bot_<login key>"
```

That returns `sent: true` and `expires_in: 3600`. The 2FA key is in the other
inbox, not in this response.

```bash
curl -X POST https://family.poweredby.top/api/v1/auth/exchange \
  -H "Authorization: Bearer fos_bot_<login key>" \
  -H "X-FOS-2FA: fos_bot_<2FA key>"
```

```json
{
  "token": "fos_s1_…",
  "token_type": "Bearer",
  "expires_in": 3600,
  "expires_at": "2026-10-02T18:04:05Z",
  "scope": "fos_bot_",
  "scope_label": "House (read + write)",
  "bot": "truckbot"
}
```

The 2FA key is spent here and is **not** sent on any later request. The
login key stays until the bot replaces it, or a leader does. Ask for a new
2FA key with `/api/v1/auth/present` when the hour is up or the key was already used.

### 2. Call the API

```bash
curl https://family.poweredby.top/api/v1/vehicles \
  -H "Authorization: Bearer fos_s1_…"
```

### 3. Replace the login key when the session is finished

```bash
curl -X POST https://family.poweredby.top/api/v1/auth/reset \
  -H "Authorization: Bearer fos_s1_…"
```

That emails a new login key to the login inbox. The new key does not expire.
The previous login key and this session stop working. The response does not
contain the new key. Sign in again with present, then exchange.

`POST /api/v1/auth/revoke` still ends the session only and leaves the login key.

---

## Routes

### Either scope

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/v1/auth/present` | Login key in. Emails a 2FA key that expires in 1 hour. |
| `POST` | `/api/v1/auth/exchange` | Login key plus that 2FA key → session token. |
| `GET` | `/api/v1/helper` | The route map for this key. `/api/v1/help` is the same call. JSON is `{ok, greeting, data:{lines, calls, guide, examples}}`. `data.guide` is the field-by-field help. A path that is not listed is 404. |
| `GET` | `/api/v1/whoami` | Bot, scope, `account.role`, `account.can`, session expiry, and routes. |
| `GET` | `/api/v1/me` | Same as whoami. |
| `GET` | `/api/v1/meta` | The documented v1 surface for both scopes. |
| `POST` | `/api/v1/auth/revoke` | Kills the calling session only. |
| `POST` | `/api/v1/auth/reset` | Session only. Emails a new login key to the login inbox, kills the old key, and ends this session. The new key does not expire. |

### `fos_bot_` — read

| Method | Path |
|---|---|
| `GET` | `/api/v1/vehicles`, `/api/v1/vehicles/<id>` |
| `GET` | `/api/v1/notes`, `/api/v1/notes/<id>` |
| `GET` | `/api/v1/notes/<id>/files` |
| `GET` | `/api/v1/files/<id>` — decrypted attachment bytes |
| `GET` | `/api/v1/inventory`, `/api/v1/inventory/<id>` |
| `GET` | `/api/v1/records`, `/api/v1/records/<id>` — needs `legal` |
| `GET` | `/api/v1/records/<id>/files`, `/api/v1/records/<id>/files/<file_id>` — needs `legal` |
| `GET` | `/api/v1/cases`, `/api/v1/cases/<id>` — needs `legal` |
| `GET` | `/api/v1/basket` |
| `GET` | `/api/v1/reminders` |
| `GET` | `/api/v1/tools`, `/api/v1/tools/<id>` |
| `GET` | `/api/v1/house`, `/api/v1/house/<id>` |
| `GET` | `/api/v1/items/<id>/logs` |
| `GET` | `/api/v1/items/<id>/parts` — vehicles only |
| `GET` | `/api/v1/photos`, `/api/v1/photos/<id>` |
| `GET` | `/api/v1/find?q=` — records and cases only when `legal` |
| `GET` | `/api/v1/people` — not a child. No passwords or security inboxes |
| `GET` | `/api/v1/ask` — this bot's own Ask history, not a child's |
| `GET` | `/api/v1/activity` — leaders only |
| `GET` | `/api/v1/vault`, `/api/v1/vault/<id>` — when this account can use the vault. Names on the list, the open card on `<id>` |

### `fos_bot_` — write

| Method | Path |
|---|---|
| `POST` | `/api/v1/vehicles` · `PATCH /api/v1/vehicles/<id>` |
| `POST` | `/api/v1/notes` · `PATCH /api/v1/notes/<id>` |
| `POST` | `/api/v1/notes/<id>/files` — multipart, field `file` |
| `POST` | `/api/v1/inventory` · `PATCH /api/v1/inventory/<id>` |
| `POST` | `/api/v1/records` · `PATCH /api/v1/records/<id>` — needs `legal`. PATCH may also send multipart field `file` |
| `POST` | `/api/v1/records/<id>/files` — multipart, field `file`. Adds a photo or PDF. Needs `legal` |
| `POST` | `/api/v1/basket` · `POST /api/v1/basket/<id>/done` — scan or groceries |
| `POST` | `/api/v1/reminders` · `PATCH /api/v1/reminders/<id>` · `POST /api/v1/reminders/<id>/done` — needs `maintain` |
| `POST` | `/api/v1/tools` · `PATCH /api/v1/tools/<id>` — needs `maintain` |
| `POST` | `/api/v1/house` · `PATCH /api/v1/house/<id>` — needs `maintain` |
| `POST` | `/api/v1/items/<id>/logs` — needs `maintain` |
| `POST` | `/api/v1/items/<id>/oil` — vehicle or tool, needs `maintain` |
| `POST` | `/api/v1/items/<id>/parts` — vehicles only, needs `maintain` |
| `POST` | `/api/v1/cases` — needs `legal` |

`PATCH` is a whitelisted column update — a body key that is not a known field
is ignored, never mass-assigned.

List routes take `?limit=` (default 50, max 200) and `?offset=`, and answer
with `count`, `total`, and `has_more` so a caller knows there is more to fetch.

### `fos_vault_` — read only

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/v1/vault` | Card metadata only. **No secrets** — safe to poll. |
| `GET` | `/api/v1/vault/<id>` | Decrypts that card. Audited as `vault.read`. |

`GET /api/v1/vault` deliberately omits passwords and account numbers so a
routine sync never pulls plaintext. Fetch a card only when you need it.

Access follows the vault page's own rules: never a child account, and only
cards this bot may see — its own, the whole household's, or one shared with it
on a live grant. A card the bot cannot see returns 404, the same as a card
that does not exist.

### No delete in v1

Nothing deletes. `DELETE` on any path is `405`. Check a basket line off, mark a reminder done, or `PATCH` a reminder's `status` to `done`.

---

## Doing the work

`GET /api/v1/helper` is the help file for the key that is signed in. `data.guide` is the prose. `data.examples` is one JSON body per job. A vault key's guide only covers opening cards. The bodies below are the house key.

Send `Content-Type: application/json`. A missing required field is `400`. An unknown field is ignored. The account still has to be allowed: `403` `forbidden` when the role cannot, `403` `scope_denied` when the prefix cannot.

This key does not change people, passwords, leaders, the AI key, mail, or the Look theme. It does not write vault cards. Item photos (`GET /api/v1/photos`) are read-only. A photo or PDF on a legal record is added with `POST /api/v1/records/<id>/files`. `POST /api/v1/inventory` is for groceries. A tool or a house thing has its own route so it does not also become a grocery row.

### Vehicle

`POST /api/v1/vehicles` and `PATCH /api/v1/vehicles/<id>`. Needs `maintain`.

```json
{"name":"Tundra","year":2006,"make":"Toyota","model":"Tundra","current_mileage":78000,"oil_needs":"5W-30","oil_capacity":"6.5 qt"}
```

Also `vin`, `plate`, `color`, `trim`, `oil_type`, `filter_type`, `tire_size`, `notes`, `category`, `last_oil_change_date`, `next_oil_due_date` (`YYYY-MM-DD`), `oil_interval_miles`, `oil_interval_months`.

### Tool

`POST /api/v1/tools`, `GET /api/v1/tools/<id>`, `PATCH /api/v1/tools/<id>`. Needs `maintain`.

```json
{"name":"Gas generator","category":"power","type":"generator","model":"EU2200i","serial_number":"SN1","power_source":"gas","oil_needs":"10W-30","oil_capacity":"0.4 qt","notes":"shed"}
```

### House thing

`POST /api/v1/house`, `GET /api/v1/house/<id>`, `PATCH /api/v1/house/<id>`. The reply key is `place`. Needs `maintain`.

```json
{"name":"Pool pump","category":"pool","notes":"Hayward"}
```

### Oil

`POST /api/v1/items/<id>/oil` on a vehicle or a tool. A house thing is `400`. Needs `maintain`.

```json
{"needs":"5W-30","capacity":"6.5 qt","in_it":"5W-30"}
```

One other fluid, or several:

```json
{"fluid":"rear_diff","value":"75W-90"}
```

```json
{"fluids":{"transmission":"WS","coolant":"pink","transfer_case":"75W-90"}}
```

Fluid keys: `rear_diff`, `front_diff`, `transmission`, `transfer_case`, `coolant`, `brake_fluid`, `power_steering`.

### Part

`GET` and `POST /api/v1/items/<id>/parts`. Vehicles only. A tool or a house thing is `404`. Needs `maintain`. `status` is `installed`, `spare`, or `retired`. `installed` replaces the current part in that system and slot.

```json
{"name":"Oil filter","system":"engine","slot":"oil_filter","brand":"Wix","part_number":"57060","status":"installed"}
```

`system` is `engine`, `electrical`, `electronics`, `exhaust`, `cooling`, `fuel`, `drivetrain`, `brakes`, `steering`, `tires`, `body`, `hvac`, or `other`. Also `spec`, `model`, `serial_number`, `asset_id`, `installed_on`, `installed_mileage`, `notes`, `source`, `cost`.

### Grocery, basket, reminder, log, note

```json
{"name":"Oat milk","quantity":2,"location":"fridge","unit":"each"}
```

`POST /api/v1/inventory`. A child may change the count, not the name. `PATCH` can set `expires_on` (`YYYY-MM-DD`). A barcode already in the house is `409`.

```json
{"name":"Oat milk","quantity_needed":1,"reason":"want"}
```

`POST /api/v1/basket`. `POST /api/v1/basket/<id>/done` checks that line off. `POST /api/v1/basket/<id>/match` ties that line to stock (`item_id`).

```json
{"title":"Change the generator oil","type":"oil_change","due_at":"2026-11-01T09:00:00","item_id":123,"recurrence":"50h","notes":"after 50 hours"}
```

`POST /api/v1/reminders`. `type` is `bill`, `oil_change`, `filter`, `blades`, `hvac_filter`, `tires`, `battery`, `smoke`, or `custom`. `recurrence` is `30d`, `90d`, `180d`, `365d`, `3000mi`, `5000mi`, `50h`, or blank. `PATCH /api/v1/reminders/<id>` takes the same fields plus `status` `open` or `done`. Needs `maintain`.

```json
{"kind":"repair","title":"Spark plugs","notes":"gapped 0.044","happened_on":"2026-10-07","reading":78120,"cost":"24.00"}
```

`POST /api/v1/items/<id>/logs`. `kind` is `miles`, `hours`, `fillup`, `repair`, `note`, `code`, or `trip`. A fill-up can send `gallons`.

`POST /api/v1/items/<id>/trips` starts or ends a trip on a vehicle. `action` is `start` or `end`. `reading` is the odometer. `start` also takes `origin` and `dest`.

```json
{"title":"Filter size","body":"16x20x1","visibility":"household","item_id":123}
```

`POST /api/v1/notes`. `visibility` is `personal` or `household`. Files are multipart, field `file`, on `POST /api/v1/notes/<id>/files`.

### Legal paper and cases

Needs `legal` on this account.

```json
{"title":"Speeding ticket","kind":"ticket","status":"open","agency":"City","due_on":"2026-11-01","amount":"150.00","body":"Main St"}
```

`POST /api/v1/records`. `kind` is `citation`, `notice`, `warning`, `ticket`, `court`, `letter`, or `other`. `status` is `open`, `paid`, `contested`, `appealed`, `dismissed`, or `closed`. Also `case_number`, `location`, `issued_on`, `outcome`.

A later photo stays on that same record. `POST /api/v1/records/<id>/files` is multipart, field `file` (also `photo` or `image`). Optional `caption`, for example `Paid receipt`. Several files in one call are all kept. Nothing already on the record is replaced. `PATCH /api/v1/records/<id>` accepts the same file fields when the body is multipart, so a status change and a receipt can go together. `GET /api/v1/records/<id>/files` lists them. `GET /api/v1/records/<id>/files/<file_id>` returns the bytes.

```json
{"title":"The ticket","status":"open","summary":"Follow the paper."}
```

`POST /api/v1/cases`. `status` is `open` or `closed`. The number is assigned. `PATCH /api/v1/cases/<id>` takes the same fields. `POST /api/v1/cases/<id>/followups` adds a note, link, or email. A photo or PDF belongs on the record (`POST /api/v1/records/<id>/files`), not as a file follow-up. `PATCH /api/v1/records/<id>` with `case_id` ties a paper on. `GET /api/v1/cases/<id>` reads one.

### Find, people, Ask, activity, vault

`GET /api/v1/find?q=` searches the house. Records and cases are included only when this account has `legal`.

`GET /api/v1/people` is names and roles. Not a child. No passwords and no security inboxes.

`GET /api/v1/ask` is this bot's own Ask history. Not a child.

`GET /api/v1/activity` is leaders and admins.

`GET /api/v1/vault` is card names. `GET /api/v1/vault/<id>` opens one card when this account can use the vault. A child never can. A card this account cannot see is `404`.

---

## Errors

Always JSON:

```json
{"error": "That key pair is not valid.", "status": 401, "code": "invalid_key_pair"}
```

| Status | When |
|---|---|
| `400` | Missing/invalid body, bad file type |
| `401` | Missing, malformed, revoked, or expired token; bad key pair |
| `403` | Plain HTTP; wrong scope; paused household; bot setup regressed |
| `404` | Not in this household — or not visible to this bot |
| `409` | Barcode already in this household |
| `429` | Rate limited (see `Retry-After`) |

A probe cannot use error codes to map which keys exist: unknown token and bad
token are the same 401, and an invisible vault card is the same 404 as a
missing one.

## Limits

| What | Default | Config |
|---|---|---|
| Read calls, per session, per minute | 240 | `BOT_API_READ_RATE` |
| Write calls, per session, per minute | 60 | `BOT_API_WRITE_RATE` |
| Exchange, per IP, per minute | 20 | `BOT_API_EXCHANGE_RATE` |
| Calls, per IP, per minute | 1200 | `BOT_API_IP_RATE` |
| Session token life | 1 hour | `BOT_API_SESSION_TTL` (max 24h) |

Counters live in `bot_api_rate`, not memory, because Passenger runs several
workers and an in-process counter resets on every recycle.

## Security posture

- **HTTPS only.** `X-Forwarded-Proto` is honoured via the existing `ProxyFix`.
  Local development can stand this down with `BOT_API_ALLOW_INSECURE=1`.
- **Hashes only.** Keys and session tokens are stored as SHA-256. Key lookups
  are constant-time.
- **Bots only.** A key on a non-bot account cannot be minted, and a session
  belonging to an account that is no longer a bot stops resolving.
- **Household-scoped.** Every query filters the session's `household_id`.
  `app.utils.household.scoped` is not used here because it reads
  `flask_login's current_user`, which is anonymous on a Bearer request.
- **Setup is re-checked on every exchange.** If a bot's 2FA is cleared or an
  inbox collapses back to the login address, new tokens stop being issued.
- **CSRF is not bypassed.** Bearer requests carry no session cookie, so the
  existing CSRF and cross-site checks apply unchanged.

## Audit log

Every call writes one row to `bot_api_audit`: event, method, path, status,
scope, key, session, IP, user agent. `event` is one of `exchange`, `call`,
`denied`, `rate_limit`, `vault.read`. `scope` is one prefix, or
`fos_bot_,fos_vault_` when the route accepts either key. That column is
`VARCHAR(64)`.

Denials are logged too — a wrong-scope or wrong-token attempt shows up
alongside normal traffic.

Bot writes **also** land in the household's *What happened* log
(`household_activity`), so the family sees the bot working in the same place
they see a kid's tap. Those rows are not reversible from the UI.

## Tables

| Table | Holds |
|---|---|
| `bot_api_keys` | Key hashes, scope, role, pair id, expiry, revocation |
| `bot_api_sessions` | Session token hashes, scope, expiry, revocation |
| `bot_api_audit` | One row per call / exchange / denial |
| `bot_api_rate` | Fixed-window counters, shared across workers |

## Tests

```bash
.venv/bin/python -m unittest tests.test_bot_api
```

33 tests: pair delivery to two inboxes, hash-only storage, exchange, every
resource route, the helper guide, a house key saving a tool, oil, a part, a
house thing, a reminder, a case (including a follow-up, a status change, and
tying on a paper), a trip, a use-by date, and a basket match, the same jobs
through the Ask tools, a vault key refused on those routes,
scope separation both ways, cross-household isolation, reset/resend, swapped
halves, mixed bots, self-pairing, HTTPS, rate limits, audit rows, revoke,
no-delete, paging, the leader + self-service UI, and the in-app key guide
(a child can open Ask, and still cannot open the vault or records).