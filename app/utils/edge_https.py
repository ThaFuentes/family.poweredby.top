"""Whether this request arrived over HTTPS.

HostM and Tailscale Serve terminate TLS and connect to the app on loopback.
Cloudflare terminates TLS and connects from its own networks. Either hop may
speak plain HTTP to the app and report the visitor scheme in
X-Forwarded-Proto or CF-Visitor. A stranger sending those headers is not HTTPS.
"""
from __future__ import annotations

import ipaddress
import json

from flask import has_request_context, request

# https://www.cloudflare.com/ips-v4 and ips-v6, fetched 2026-10-02.
_CLOUDFLARE = (
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
)
_CF_NETS = tuple(ipaddress.ip_network(item) for item in _CLOUDFLARE)


def _parse_ip(value: str | None):
    try:
        return ipaddress.ip_address((value or "").strip())
    except ValueError:
        return None


def _immediate_peer() -> str | None:
    """TCP peer, before ProxyFix replaces it with the visitor."""
    if not has_request_context():
        return None
    orig = request.environ.get("werkzeug.proxy_fix.orig")
    if isinstance(orig, dict):
        saved = orig.get("REMOTE_ADDR")
        if saved:
            return str(saved)
    return request.remote_addr


def peer_is_trusted_proxy(addr: str | None = None) -> bool:
    """Loopback (local web server) or a published Cloudflare range.

    ProxyFix rewrites REMOTE_ADDR to the visitor. The address that counts
    is the one that opened the socket.
    """
    if addr is None:
        addr = _immediate_peer()
    ip = _parse_ip(addr)
    if ip is None:
        return False
    if ip.is_loopback:
        return True
    return any(ip in net for net in _CF_NETS)


def headers_say_https() -> bool:
    if not has_request_context():
        return False
    forwarded = request.headers.get("X-Forwarded-Proto") or ""
    parts = [part.strip().lower() for part in forwarded.split(",") if part.strip()]
    # The nearest proxy appends, so the last value is the one we can check.
    if parts and parts[-1] == "https":
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
    forwarded = bool(
        (request.headers.get("X-Forwarded-Proto") or "").strip()
        or (request.headers.get("CF-Visitor") or "").strip()
    )
    if peer_is_trusted_proxy():
        if headers_say_https():
            return True
        return bool(request.is_secure)
    # ProxyFix may already have trusted a spoofed proto. Do not.
    if forwarded:
        return False
    return bool(request.is_secure)
