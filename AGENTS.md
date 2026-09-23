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
- Notes (`/notes`): title + body, Just me / Whole household. Photos and PDFs attach to the note (encrypted, same as records). Household notes show those files to everyone in the house so they can open them later. Kids can see household notes; they cannot see the vault.
- Ask: a chat window on adult pages when the household has its own AI key. On by default; leaders can hide it on Household → AI key. Full-page rooms at `/ask/`, `/ask/vehicles`, `/ask/inventory`, `/ask/tools`, `/ask/basket`, `/ask/due` keep threads apart. `/ask/help` and slash `/help` `/vehicles` `/inventory` `/tools` `/basket` `/due` `/oil` list the house with no model. The bubble on Vehicles / Inventory / Tools / Due / Basket uses that room. It looks the house up itself (do not dump JSON, do not ask them to go look). Missing oil on a saved vehicle/tool is looked up from year/make/model/VIN (NHTSA engine + OEM spec) and offered to save. Food with no use-by: it says how many, and “add generic expirations” writes typical shelf life without overwriting typed dates. It can inspect/add/remove tools, vehicles, and inventory; restock / mark used / need-more; add basket rows and notes; set billing schedules (Due); unlock the vault with this login’s password then add/open logins and bills. The floating Ask bubble is one house thread: Close keeps it (DB + this device). New wipes it. Idle 14 days also clears it. Full-page `/ask/vehicles` and friends stay their own rooms. Kids never see Ask. Family OS never uses the owner’s key. Ask and scan AI stay in the signed-in household — never another house’s key, list, or vault.
- Basket is a shopping list. Do not auto-add items when they run low unless that item has **When this is low, put it on the basket**. Explicit Need more / Want / Buy still add to the basket. Ask can dump a store run by name (“from Sam’s: coffee creamer…”) with no barcode. Later scan-in of the real UPC (French vanilla creamer) matches that placeholder, restocks, and takes the line off. Token match first; household AI picks the nickname if the names are looser.
- Vault (`/vault`): Passwords, Billing, and Shareable info. Cards open in the iframe sheet. Each item holds phone(s), web address, account number, login, password, 2FA (and how), plus codes/info needed for the call or site. Encrypted at rest. Unlock with Family OS username + password. Kids never see the vault.
- Vault sharing: named people get a clock (1 hour, 1 week, forever…). Forever stays after they open it — viewing does not end access. The sheet shows who **still** has it, how long is left, and whether they opened it. Expired or taken-back people move to Ended. Activity lists copies and opens.
- Scan is a **UPC scanner** (EAN/UPC + household QR). Do not switch the camera to VIN/Code 39 globally. Type VIN on the vehicle form for NHTSA. On an open vehicle, tool, or house, a UPC attaches as equipment, with **Undo**. Inventory rows have +/- to correct the count. Scan-in remembers the usual pack size (30-count chips) as the first chip.
- Inventory rows show the catalog product picture (Frosted Flakes, milk, etc.), not a blank white tile. Prefer front-of-pack thumbs from lookup. Household photo is the fallback. Letter tile if neither loads.
- Records are the paper (notice, ticket, letter). A **case** is optional and later: open one from a record, keep follow-ups (notes, emails, links, files) on the case. The record stays searchable by kind and shows **Case #N**.
- Vehicle/house Systems default to the calmer Amy layout (on-it + dates, history collapsed, empty slots in Add/Replace). Cookie `family_systems_ui=classic` or **Switch back** restores the old view. Do not delete `vehicle_systems_classic.html` / `parts_sheet_classic.html`.
- Vehicle / tool / house **Log** tab: miles or hours, fill-ups (mpg + year $ / gallons), repairs with the odometer/hours, notes and photos. Overview stays a snapshot; the log holds history.
- The house file has kitchen, electronics, fitness, **pool** (pump, filter, chemicals), **coop** (feed, hay, gear), sink/faucet parts, HVAC, and the rest. Each thing can have model, product #, serial, and an internal ID. Two TVs is two rows — do not auto-replace house items. Scan on the house page attaches the UPC to the right slot.
