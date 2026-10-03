"""Whether this request arrived over HTTPS.

HostM, Tailscale, and Cloudflare terminate TLS and connect onward in clear
text. ProxyFix (x_proto=1) copies X-Forwarded-Proto onto the request scheme.
CF-Visitor is Cloudflare's own copy of the visitor scheme. Either one means
the visitor used HTTPS. A plain HTTP socket with neither is not HTTPS.

The previous peer-address allowlist rejected real Cloudflare calls: the host
replaces the socket address with the visitor, so the app no longer sees a
Cloudflare IP.
"""
from __future__ import annotations

import json

from flask import has_request_context, request


def headers_say_https() -> bool:
    if not has_request_context():
        return False
    forwarded = request.headers.get("X-Forwarded-Proto") or ""
    parts = [part.strip().lower() for part in forwarded.split(",") if part.strip()]
    # The nearest proxy appends. "https" anywhere in the chain is enough:
    # a later hop often appends "http" for its own clear-text connection.
    if any(part == "https" for part in parts):
        return True
    raw = (request.headers.get("CF-Visitor") or "").strip()
    if not raw:
        return False
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return False
    return isinstance(data, dict) and str(data.get("scheme") or "").lower() == "https"


def request_is_https() -> bool:
    if not has_request_context():
        return False
    if request.is_secure:
        return True
    return headers_say_https()
