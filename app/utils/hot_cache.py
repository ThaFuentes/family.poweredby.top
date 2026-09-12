"""Process-local TTL cache for household-safe snapshots.

Passenger workers do not share this. Keys that hold tenant data must include
household_id (or be global catalogs like UPC/VIN). Never store passwords or
session tokens here.
"""
from __future__ import annotations

import copy
import threading
import time
from typing import Any

_lock = threading.Lock()
_store: dict[str, tuple[float, Any]] = {}
_MAX = 800

# after_flush household ids, per-thread, flushed on commit
_dirty = threading.local()


def get(key: str):
    now = time.monotonic()
    with _lock:
        hit = _store.get(key)
        if not hit:
            return None
        expires, value = hit
        if expires <= now:
            _store.pop(key, None)
            return None
        value = copy.deepcopy(value)
    return value


def put(key: str, value, ttl: float) -> None:
    if not key or ttl <= 0:
        return
    expires = time.monotonic() + float(ttl)
    stored = copy.deepcopy(value)
    with _lock:
        if len(_store) >= _MAX:
            _evict_unlocked()
        _store[key] = (expires, stored)


def delete(key: str) -> None:
    with _lock:
        _store.pop(key, None)


def bump(prefix: str) -> int:
    """Drop every key that starts with prefix. Returns how many were removed."""
    if not prefix:
        return 0
    n = 0
    with _lock:
        for key in [k for k in _store if k.startswith(prefix)]:
            _store.pop(key, None)
            n += 1
    return n


def invalidate_household(household_id: int) -> None:
    hid = int(household_id)
    bump(f"home:{hid}:")
    delete(f"flush:{hid}")


def clear() -> None:
    with _lock:
        _store.clear()


def _evict_unlocked() -> None:
    now = time.monotonic()
    dead = [k for k, (exp, _) in _store.items() if exp <= now]
    for k in dead:
        _store.pop(k, None)
    if len(_store) < _MAX:
        return
    # Drop oldest expiry first.
    ordered = sorted(_store.items(), key=lambda kv: kv[1][0])
    for key, _val in ordered[: max(1, len(_store) // 5)]:
        _store.pop(key, None)


def _bag() -> set:
    bag = getattr(_dirty, "hids", None)
    if bag is None:
        bag = set()
        _dirty.hids = bag
    return bag


def _track_flush(session, _ctx) -> None:
    bag = _bag()
    try:
        rows = list(session.new) + list(session.dirty) + list(session.deleted)
    except Exception:
        return
    for obj in rows:
        hid = getattr(obj, "household_id", None)
        if hid:
            try:
                bag.add(int(hid))
            except (TypeError, ValueError):
                pass


def _after_commit(_session) -> None:
    bag = getattr(_dirty, "hids", None)
    _dirty.hids = set()
    if not bag:
        return
    for hid in bag:
        try:
            invalidate_household(hid)
        except Exception:
            pass


def _after_rollback(_session) -> None:
    _dirty.hids = set()


_hooks_registered = False


def register_session_hooks(db) -> None:
    """Invalidate household home snapshots after a real commit."""
    global _hooks_registered
    if _hooks_registered:
        return
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    event.listen(Session, "after_flush", _track_flush)
    event.listen(Session, "after_commit", _after_commit)
    event.listen(Session, "after_rollback", _after_rollback)
    _hooks_registered = True
