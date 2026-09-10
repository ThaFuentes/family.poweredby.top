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

- Household = tenant. Every query is filtered by `household_id`.
- Roles: `admin` (full), `member` (scan + groceries + maintenance), `child` (scan only).
- Leaders (`users.is_leader`): **the household** picks them (People page). Platform does not. Name + email is the only tenant PII the owner console may show. At least one leader. Child cannot be a leader. Founder of a new household is the first leader (email required).
- Password reset is in-household only: Forgot password, Look → your password, or a leader sending a reset to someone in **that** household. No platform reset of tenant passwords. No cross-tenant.
- Reminders: household chooses email / calendar / both. Calendar is a secret ICS feed (`/reminders/calendar/<token>.ics`) scoped to that household. Email From: is the platform SMTP identity.
- Owner console: `/platform/` — first person there becomes the owner (no .env token). Later owners need an `OWN-` key the first owner mints on Access. Separate `platform_owners` table. SMTP From + SpaceXAI. Fleet is household name, people count, leader name/email.
- `SITE_MODE` is `family`. Wrapper cookie: `pbt_family_session`. Camera is on for scan.
