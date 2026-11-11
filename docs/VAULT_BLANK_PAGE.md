# Vault opens a blank white page

The password vault is `/my-vault`. Do not move it back to `/vault`.

HostM’s edge answers `GET /vault` and `GET /vault/…` before Flask. The response is HTTP 403 with a one-byte body (a space, `0x20`) and no Family OS headers. The browser paints that as a blank white page.

These paths still reach the app and must stay put:

- `/my-vault/` — the vault page
- `/auth/vault` — household lock
- `/api/v1/vault` — bot API

After a deploy, a signed-out `GET /my-vault/` redirects to login. `GET /vault/` stays a one-byte 403.
