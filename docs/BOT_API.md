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
item logs, photos, find, people, cases, and that bot's own Ask history.
Writes follow the same permissions as the page (a child can check the basket
and cannot file a legal record or edit a vehicle). Leaders can read
`GET /api/v1/activity`. There is still no delete.

## Two keys, two inboxes

Each scope is issued as a **pair**, never a single key:

| Half | Goes to | Used as |
|---|---|---|
| `primary` | the bot's login email (`users.email`) | `Authorization: Bearer` |
| `twofa` | the bot's 2FA email (`users.security_email`) | `X-FOS-2FA` |

The 2FA inbox must be a different address from the login inbox. The bot
account also needs 2FA turned on and a separate reset inbox, or no key can be
issued at all.

A **vault** key lives on its own bot account with its own three inboxes, so it
is completely independent of the house bot's key.

### Why there are two, and what "reset" does

The two halves go to different people-facing inboxes on purpose: the login key
alone is not enough to use the API, so a leak of one inbox is not a working
credential.

Only the SHA-256 hash of each key is stored. That is a deliberate trade:

- a database copy cannot be replayed as a key, and
- **a resend cannot repeat the old key — it issues a fresh pair and revokes
  the previous one.**

So `Send keys`, `Reset`, and `Resend` on People all rotate the pair. At any
moment exactly one pair per scope is live. Resetting also kills every session
token that pair produced.

## Getting keys

**A household leader**, on People → the bot's sheet → *Bot API*:

- `Send keys` — first pair for that scope
- `Reset` — new pair, old pair dead
- `Resend` — new pair, old pair dead (same thing; the label says why)

Both halves are also shown once in the copy window so the operator can hand
them over directly. After that they exist only in the two inboxes.

**The bot itself**, from its own dashboard (`/`), proved by its current
password or a fresh authenticator code — exactly like the password reset card.
A bot can never see its own keys on that page; it can only ask for new ones.

## Using it

### 1. Exchange the pair for a session token (once)

```bash
curl -X POST https://family.poweredby.top/api/v1/auth/exchange \
  -H "Authorization: Bearer fos_bot_<primary key>" \
  -H "X-FOS-2FA: fos_bot_<emailed key>"
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

The emailed half is spent here and is **not** sent on any later request.

The pair stays reusable until it is reset — it is a long-lived second factor,
like a hardware token, not a one-shot code. Every exchange is audited.

### 2. Call the API

```bash
curl https://family.poweredby.top/api/v1/vehicles \
  -H "Authorization: Bearer fos_s1_…"
```

### 3. Revoke the session when done

```bash
curl -X POST https://family.poweredby.top/api/v1/auth/revoke \
  -H "Authorization: Bearer fos_s1_…"
```

---

## Routes

### Either scope

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/v1/auth/exchange` | Pair → session token. Unauthenticated by design. |
| `GET` | `/api/v1/whoami` | Bot, scope, `account.role`, `account.can`, session expiry, and routes. |
| `GET` | `/api/v1/meta` | The documented v1 surface for both scopes. |
| `POST` | `/api/v1/auth/revoke` | Kills the calling session only. |

### `fos_bot_` — read

| Method | Path |
|---|---|
| `GET` | `/api/v1/vehicles`, `/api/v1/vehicles/<id>` |
| `GET` | `/api/v1/notes`, `/api/v1/notes/<id>` |
| `GET` | `/api/v1/notes/<id>/files` |
| `GET` | `/api/v1/files/<id>` — decrypted attachment bytes |
| `GET` | `/api/v1/inventory`, `/api/v1/inventory/<id>` |
| `GET` | `/api/v1/records`, `/api/v1/records/<id>` — needs `legal` |
| `GET` | `/api/v1/cases` — needs `legal` |
| `GET` | `/api/v1/basket` |
| `GET` | `/api/v1/reminders` |
| `GET` | `/api/v1/tools`, `/api/v1/house` |
| `GET` | `/api/v1/items/<id>/logs` |
| `GET` | `/api/v1/photos`, `/api/v1/photos/<id>` |
| `GET` | `/api/v1/find?q=` — records and cases only when `legal` |
| `GET` | `/api/v1/people` — not a child. No passwords or security inboxes |
| `GET` | `/api/v1/ask` — this bot's own Ask history, not a child's |
| `GET` | `/api/v1/activity` — leaders only |
| `GET` | `/api/v1/vault`, `/api/v1/vault/<id>` — when this account can use the vault |

### `fos_bot_` — write

| Method | Path |
|---|---|
| `POST` | `/api/v1/vehicles` · `PATCH /api/v1/vehicles/<id>` |
| `POST` | `/api/v1/notes` · `PATCH /api/v1/notes/<id>` |
| `POST` | `/api/v1/notes/<id>/files` — multipart, field `file` |
| `POST` | `/api/v1/inventory` · `PATCH /api/v1/inventory/<id>` |
| `POST` | `/api/v1/records` · `PATCH /api/v1/records/<id>` — needs `legal` |
| `POST` | `/api/v1/basket` · `POST /api/v1/basket/<id>/done` — scan or groceries |
| `POST` | `/api/v1/reminders` · `POST /api/v1/reminders/<id>/done` — needs `maintain` |
| `POST` | `/api/v1/items/<id>/logs` — needs `maintain` |

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

Nothing deletes. `DELETE` on any path is `405`.

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
`denied`, `rate_limit`, `vault.read`.

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

25 tests: pair delivery to two inboxes, hash-only storage, exchange, every
resource route, scope separation both ways, cross-household isolation,
reset/resend, swapped halves, mixed bots, self-pairing, HTTPS, rate limits,
audit rows, revoke, no-delete, paging, and the leader + self-service UI.