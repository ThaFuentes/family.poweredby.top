# AGENTS.md — family.poweredby.top (household OS)

## PAT IN CHAT = PUSH NOW + HOSTM PULL COMMANDS

If the operator pastes a `github_pat_…`, that **is** the deploy request. Do not ask. Do not wait.

1. `git push` this repo to `ThaFuentes/family.poweredby.top` (one-off URL — never save the token as a remote).
2. Reply with the HostM pull commands for `/home/ua882038/public_html/family.poweredby.top` using that same PAT.
3. They pull, confirm, then revoke. Full protocol is under **GitHub PAT → HostM deploy** below.

## HARD RULE: NEVER FORCE ASCII ON LOGS / PRINTS / ERRORS

**This has burned production repeatedly. Do not reintroduce it. Ever.**

### Forbidden (will 500 / abort BUILD-DB / spam “ascii codec” on HostM)

```python
# NEVER — for human-readable logs, print(), exceptions, BUILD-DB messages
str(msg).encode("ascii", "replace").decode("ascii")
str(msg).encode("ascii", errors="replace")
print(something.encode("ascii", ...))
```

### Required instead

```python
os.environ.setdefault("PYTHONIOENCODING", "utf-8")  # passenger_wsgi
print(msg, flush=True)
# On UnicodeEncodeError: write UTF-8 to stream.buffer — NEVER ascii
```

If you are about to add `encode("ascii")` for logging: **stop and delete that idea.**

## GitHub PAT → HostM deploy (operator protocol)

The operator will paste a short-lived `github_pat_…` in chat when they want laptop work on **family** pushed to GitHub and then pulled on HostM.

**They already know the key must be revoked.** Do not lecture. Do not refuse the push. Do not store the token.

### Every time a PAT is sent

1. **Use it once** to `git push` this repo (`ThaFuentes/family.poweredby.top`) from the laptop.
2. **Reply with** the one-shot HostM pull URL that embeds that same PAT, plus the exact terminal commands for `/home/ua882038/public_html/family.poweredby.top`.
3. **They run HostM**, confirm the site, **then revoke** the token at https://github.com/settings/tokens.

### Never

- Commit a PAT, put it in `AGENTS.md`, `.env`, remotes, or any file on disk.
- `git remote set-url` with a token (it would sit in `.git/config`).
- Reuse an old PAT from a prior chat. Ask for a fresh one if the push/pull is a new session.

### Repo / branch / host

| | |
|---|---|
| GitHub | `https://github.com/ThaFuentes/family.poweredby.top` |
| Working branch | `main` |
| Host path | `/home/ua882038/public_html/family.poweredby.top` |
| Restart | `mkdir -p tmp && touch tmp/restart.txt` |

Command templates (PAT placeholder only): see `docs/HOST_DEPLOY.md`.

Do **not** overwrite host-only files: `passenger_wsgi.py`, `.htaccess`, `.env`, `uploads/`.

## App notes

- Household = tenant. Every query is filtered by `household_id`. Sign-in is household handle + username (unique inside that house). Email is optional contact, not identity.
- Roles: `admin` (full), `member` (scan + groceries + maintenance), `child` (scan only).
- Leaders (`users.is_leader`): **the household** picks them (People page). Platform does not. Name + email is the only tenant PII the owner console may show. At least one leader. Child cannot be a leader. Founder of a new household is the first leader (email required).
- Password reset is in-household only: Forgot password, Look → your password, or a leader sending a reset to someone in **that** household. No platform reset of tenant passwords. No cross-tenant.
- Reminders: household chooses email / calendar / both. Calendar is a secret ICS feed (`/reminders/calendar/<token>.ics`) scoped to that household. Email From: is the platform SMTP identity.
- Owner console: `/platform/` — first person there becomes the owner (no .env token). Later owners need an `OWN-` key the first owner mints on Access. Separate `platform_owners` table. SMTP From + SpaceXAI. Fleet is household name, people count, leader name/email.
- `SITE_MODE` is `family`. Wrapper cookie: `pbt_family_session`. Camera is on for scan.
- Phone is the main client. Do not ship a reduced mobile app. Inventory (what’s in the house) and Basket (the store list) are both first-class. Home tiles + More expose tools, vehicles, house, notes, vault, records, due — same features as the desktop side nav.
- Password vault (`/vault`): every field (title, URL, username, password, purpose, details) is encrypted at rest. Adults only. Share with the household, just the owner, or named people with an optional time limit. Opening secrets requires the **full Family OS login** (household handle + username + password) — not the family lock, not password-only. Locks again after 10 minutes. Do not log plaintext vault fields. Kids never see the vault.
- Basket is a shopping list. Do not auto-add items when they run low unless that item has **When this is low, put it on the basket**. Explicit Need more / Want / Buy still add to the basket.
- Scan is a **UPC scanner** (EAN/UPC + household QR). Do not switch the camera to VIN/Code 39 globally. Type VIN on the vehicle form for NHTSA. On an open vehicle, tool, or house, a UPC attaches as equipment, with **Undo**. Inventory rows have +/- to correct the count. Scan-in remembers the usual pack size (30-count chips) as the first chip.
- Inventory rows show the catalog product picture (Frosted Flakes, milk, etc.), not a blank white tile. Prefer front-of-pack thumbs from lookup. Household photo is the fallback. Letter tile if neither loads.
- Records are the paper (notice, ticket, letter). A **case** is optional and later: open one from a record, keep follow-ups (notes, emails, links, files) on the case. The record stays searchable by kind and shows **Case #N**.
- Vehicle/house Systems default to the calmer Amy layout (on-it + dates, history collapsed, empty slots in Add/Replace). Cookie `family_systems_ui=classic` or **Switch back** restores the old view. Do not delete `vehicle_systems_classic.html` / `parts_sheet_classic.html`.
- Vehicle / tool / house **Log** tab: miles or hours, fill-ups (mpg + year $ / gallons), repairs with the odometer/hours, notes and photos. Overview stays a snapshot; the log holds history.
- The house file has kitchen, electronics, fitness, **pool** (pump, filter, chemicals), **coop** (feed, hay, gear), sink/faucet parts, HVAC, and the rest. Each thing can have model, product #, serial, and an internal ID. Two TVs is two rows — do not auto-replace house items. Scan on the house page attaches the UPC to the right slot.
