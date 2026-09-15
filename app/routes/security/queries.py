# Queries for PoweredByTop tables + account locks + security grants + audit log.

from __future__ import annotations

from datetime import datetime, timedelta

try:
    from app.utils.time_utils import format_for_user, now_naive_storage
except Exception:  # pragma: no cover
    def now_naive_storage():
        return datetime.utcnow()

    def format_for_user(dt, **kwargs):
        return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "—"


def _fmt_ts(dt) -> str:
    """Show console clocks in Central Time (or the operator's ecosystem zone)."""
    if dt is None or dt == "" or dt == "—":
        return "—"
    if isinstance(dt, str):
        raw = dt.strip()
        if not raw:
            return "—"
        if raw.endswith((" CST", " CDT", " CT", " EST", " EDT")):
            return raw
        parsed = None
        for spec in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                parsed = datetime.strptime(raw.replace("Z", "")[:26], spec)
                break
            except ValueError:
                continue
        if parsed is None:
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return raw
        dt = parsed
    try:
        return format_for_user(dt)
    except Exception:
        return str(dt)


from sqlalchemy import or_, func, text

from app.builddb.builddb import db
from app.builddb.table_users import User

try:
    from app.builddb.table_audit_logs import AuditLog
except Exception:  # Family OS has platform_audit, not AX audit_logs
    AuditLog = None  # type: ignore

from .utils import ensure_security_grants_table


def _sec():
    try:
        from poweredbytop.models.connect_db import get_security_db

        return get_security_db()
    except Exception:
        return None


def _close(conn) -> None:
    try:
        from poweredbytop.models.connect_db import close_security_db

        close_security_db(conn)
    except Exception:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def summary_stats() -> dict:
    out = {
        "events_24h": 0,
        "events_total": 0,
        "active_temp_bans": 0,
        "perm_bans": 0,
        "low_reputation": 0,
        "account_login_locks": 0,
        "attack_types": 0,
        "audit_24h": 0,
        "blocked_total": 0,
        "ip_pairs_total": 0,
        "known_user_ips": 0,
        "voided_attendance_7d": 0,
        "honeypot_hits": 0,
        "honeypot_hits_24h": 0,
        "device_prints": 0,
        "device_bans_active": 0,
    }
    conn = _sec()
    if conn is not None:
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT COUNT(*) AS c FROM pbt_security_events "
                    "WHERE COALESCE(timestamp, created_at) >= NOW() - INTERVAL 1 DAY"
                )
                out["events_24h"] = int((cur.fetchone() or {}).get("c") or 0)
            except Exception:
                cur.execute("SELECT COUNT(*) AS c FROM pbt_security_events")
                out["events_total"] = int((cur.fetchone() or {}).get("c") or 0)
            else:
                cur.execute("SELECT COUNT(*) AS c FROM pbt_security_events")
                out["events_total"] = int((cur.fetchone() or {}).get("c") or 0)

            try:
                cur.execute(
                    """
                    SELECT COUNT(*) AS c FROM pbt_reputation
                    WHERE grade = 'temp_ban'
                       OR (ban_until IS NOT NULL AND ban_until > NOW())
                    """
                )
                out["active_temp_bans"] = int((cur.fetchone() or {}).get("c") or 0)
                cur.execute("SELECT COUNT(*) AS c FROM pbt_reputation WHERE grade = 'perm_ban'")
                out["perm_bans"] = int((cur.fetchone() or {}).get("c") or 0)
                cur.execute(
                    "SELECT COUNT(*) AS c FROM pbt_reputation WHERE score < 50 AND grade NOT IN ('perm_ban')"
                )
                out["low_reputation"] = int((cur.fetchone() or {}).get("c") or 0)
            except Exception as exc:
                print(f"[security] reputation summary: {exc}")

            try:
                # Prefer merged totals (events + stats + honeypot); fall back to table only
                merged = list_attack_stats()
                if merged:
                    out["attack_types"] = len(merged)
                    out["blocked_total"] = sum(
                        int(r.get("blocked_count") or r.get("total_attempts") or 0)
                        for r in merged
                    )
                else:
                    cur.execute("SELECT COUNT(*) AS c FROM pbt_attack_stats")
                    out["attack_types"] = int((cur.fetchone() or {}).get("c") or 0)
                    cur.execute(
                        "SELECT COALESCE(SUM(blocked_count),0) AS c FROM pbt_attack_stats"
                    )
                    out["blocked_total"] = int((cur.fetchone() or {}).get("c") or 0)
            except Exception as exc:
                print(f"[security] attack stats summary: {exc}")

            # Honeypot trips: events OR reputation bans (events insert often failed on hosts)
            try:
                out["honeypot_hits"] = count_honeypot_hits(conn=conn)
                out["honeypot_hits_24h"] = count_honeypot_hits(conn=conn, hours=24)
            except Exception as exc:
                print(f"[security] honeypot summary: {exc}")

            # Device prints / office-safe bans
            try:
                cur.execute("SELECT COUNT(*) AS c FROM pbt_device_prints")
                out["device_prints"] = int((cur.fetchone() or {}).get("c") or 0)
            except Exception:
                out["device_prints"] = 0
            try:
                cur.execute(
                    """
                    SELECT COUNT(*) AS c FROM pbt_device_bans
                    WHERE permanent = 1
                       OR (ban_until IS NOT NULL AND ban_until > NOW())
                    """
                )
                out["device_bans_active"] = int((cur.fetchone() or {}).get("c") or 0)
            except Exception:
                out["device_bans_active"] = 0
        except Exception as exc:
            print(f"[security] summary pbt: {exc}")
        finally:
            _close(conn)

    try:
        now = now_naive_storage()
        locks = (
            User.query.filter(
                User.account_locked_until.isnot(None),
                User.account_locked_until > now,
            ).count()
        )
        # also count naive DB times by comparing loosely
        if locks == 0:
            locks = (
                db.session.query(func.count(User.id))
                .filter(
                    User.account_locked_until.isnot(None),
                    User.account_locked_until > func.now(),
                )
                .scalar()
                or 0
            )
        out["account_login_locks"] = int(locks)
    except Exception as exc:
        print(f"[security] summary locks: {exc}")

    try:
        if AuditLog is not None:
            since = now_naive_storage() - timedelta(days=1)
            out["audit_24h"] = int(
                AuditLog.query.filter(AuditLog.created_at >= since).count()
            )
        else:
            from app.builddb.table_platform_audit import PlatformAudit

            since = now_naive_storage() - timedelta(days=1)
            out["audit_24h"] = int(
                PlatformAudit.query.filter(PlatformAudit.created_at >= since).count()
            )
    except Exception as exc:
        print(f"[security] summary audit: {exc}")

    try:
        from app.builddb.table_user_ip_sightings import UserIpSighting

        out["ip_pairs_total"] = int(UserIpSighting.query.count())
        out["known_user_ips"] = int(
            db.session.query(func.count(func.distinct(UserIpSighting.ip_address))).scalar()
            or 0
        )
    except Exception as exc:
        print(f"[security] summary ip pairs: {exc}")

    try:
        from app.builddb.table_attendance_logs import AttendanceLog

        since7 = (now_naive_storage() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        out["voided_attendance_7d"] = int(
            AttendanceLog.query.filter(
                AttendanceLog.void_status.isnot(None),
                AttendanceLog.void_status != "",
                AttendanceLog.clock_in_timestamp >= since7,
            ).count()
        )
    except Exception as exc:
        print(f"[security] summary voids: {exc}")

    return out


def _honeypot_sql_match(alias: str = "") -> tuple[str, list]:
    """Match honeypot rows in events or reputation ban_reason."""
    p = f"{alias}." if alias else ""
    # notes and details (schema variants)
    clause = (
        f"({p}event_type LIKE %s OR {p}event_type LIKE %s "
        f"OR {p}notes LIKE %s OR {p}notes LIKE %s "
        f"OR {p}details LIKE %s OR {p}details LIKE %s)"
    )
    params = [
        "%honeypot%",
        "%unlinked_probe%",
        "%honeypot%",
        "%unlinked_probe%",
        "%honeypot%",
        "%unlinked_probe%",
    ]
    return clause, params


def count_honeypot_hits(*, conn=None, hours: int | None = None) -> int:
    """
    Unique honeypot IPs from pbt_security_events + pbt_reputation ban reasons.
    Events insert often failed historically; bans always landed in reputation.
    """
    own = conn is None
    if own:
        conn = _sec()
    if conn is None:
        return 0
    try:
        cur = conn.cursor()
        ips: set[str] = set()
        time_clause = ""
        time_params: list = []
        if hours is not None:
            time_clause = " AND COALESCE(timestamp, created_at) >= NOW() - INTERVAL %s HOUR"
            time_params = [int(hours)]

        # Events (try with details column; fall back without)
        for use_details in (True, False):
            try:
                if use_details:
                    where, params = _honeypot_sql_match("")
                else:
                    where = (
                        "(event_type LIKE %s OR event_type LIKE %s "
                        "OR notes LIKE %s OR notes LIKE %s)"
                    )
                    params = [
                        "%honeypot%",
                        "%unlinked_probe%",
                        "%honeypot%",
                        "%unlinked_probe%",
                    ]
                cur.execute(
                    f"SELECT DISTINCT ip FROM pbt_security_events WHERE {where}{time_clause}",
                    params + time_params,
                )
                for r in cur.fetchall() or []:
                    if r.get("ip"):
                        ips.add(str(r["ip"]).strip())
                break
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass

        # Reputation honeypot bans (always written when marketing honeypot fires)
        try:
            if hours is not None:
                cur.execute(
                    """
                    SELECT DISTINCT ip FROM pbt_reputation
                    WHERE (ban_reason LIKE %s OR ban_reason LIKE %s)
                      AND last_seen >= NOW() - INTERVAL %s HOUR
                    """,
                    ("%honeypot%", "%unlinked_probe%", int(hours)),
                )
            else:
                cur.execute(
                    """
                    SELECT DISTINCT ip FROM pbt_reputation
                    WHERE ban_reason LIKE %s OR ban_reason LIKE %s
                    """,
                    ("%honeypot%", "%unlinked_probe%"),
                )
            for r in cur.fetchall() or []:
                if r.get("ip"):
                    ips.add(str(r["ip"]).strip())
        except Exception as exc:
            print(f"[security] honeypot rep count: {exc}")
        return len(ips)
    except Exception as exc:
        print(f"[security] count_honeypot_hits: {exc}")
        return 0
    finally:
        if own:
            _close(conn)


def list_honeypot_hits(
    *,
    search: str = "",
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """
    Honeypot hits for the events page: merge security_events + reputation bans.
    Returns rows shaped like security events for the template.
    """
    conn = _sec()
    if conn is None:
        return [], 0
    by_ip: dict[str, dict] = {}
    try:
        cur = conn.cursor()
        # From events
        for sql in (
            """
            SELECT id, COALESCE(timestamp, created_at) AS timestamp,
                   event_type, ip, notes, reputation_score, behavior_grade
            FROM pbt_security_events
            WHERE event_type LIKE %s OR event_type LIKE %s
               OR notes LIKE %s OR notes LIKE %s
               OR details LIKE %s OR details LIKE %s
            ORDER BY COALESCE(timestamp, created_at) DESC
            LIMIT 500
            """,
            """
            SELECT id, COALESCE(timestamp, created_at) AS timestamp,
                   event_type, ip, notes, reputation_score, behavior_grade
            FROM pbt_security_events
            WHERE event_type LIKE %s OR event_type LIKE %s
               OR notes LIKE %s OR notes LIKE %s
            ORDER BY COALESCE(timestamp, created_at) DESC
            LIMIT 500
            """,
        ):
            try:
                if "details" in sql:
                    cur.execute(
                        sql,
                        (
                            "%honeypot%",
                            "%unlinked_probe%",
                            "%honeypot%",
                            "%unlinked_probe%",
                            "%honeypot%",
                            "%unlinked_probe%",
                        ),
                    )
                else:
                    cur.execute(
                        sql,
                        (
                            "%honeypot%",
                            "%unlinked_probe%",
                            "%honeypot%",
                            "%unlinked_probe%",
                        ),
                    )
                for r in cur.fetchall() or []:
                    ip = (r.get("ip") or "").strip()
                    if not ip:
                        continue
                    by_ip[ip] = {
                        "id": r.get("id"),
                        "timestamp": r.get("timestamp"),
                        "event_type": r.get("event_type") or "honeypot_ban",
                        "ip": ip,
                        "notes": r.get("notes") or "honeypot",
                        "event_score": r.get("reputation_score"),
                        "event_grade": r.get("behavior_grade"),
                        "source": "event",
                    }
                break
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass

        # From reputation (authoritative when event insert failed)
        try:
            cur.execute(
                """
                SELECT ip, score, grade, ban_reason, ban_until, last_seen, first_seen, ban_count
                FROM pbt_reputation
                WHERE ban_reason LIKE %s OR ban_reason LIKE %s
                ORDER BY last_seen DESC
                LIMIT 500
                """,
                ("%honeypot%", "%unlinked_probe%"),
            )
            for r in cur.fetchall() or []:
                ip = (r.get("ip") or "").strip()
                if not ip:
                    continue
                existing = by_ip.get(ip)
                row = {
                    "id": existing.get("id") if existing else None,
                    "timestamp": existing.get("timestamp")
                    if existing and existing.get("timestamp")
                    else r.get("last_seen") or r.get("first_seen"),
                    "event_type": "honeypot_ban",
                    "ip": ip,
                    "notes": r.get("ban_reason") or (existing or {}).get("notes") or "honeypot",
                    "event_score": r.get("score"),
                    "event_grade": r.get("grade"),
                    "live_score": r.get("score"),
                    "live_grade": r.get("grade"),
                    "live_ban_until": r.get("ban_until"),
                    "reputation_score": r.get("score"),
                    "behavior_grade": r.get("grade"),
                    "source": "reputation" if not existing else "event+reputation",
                    "ban_count": r.get("ban_count"),
                }
                by_ip[ip] = row
        except Exception as exc:
            print(f"[security] list_honeypot reputation: {exc}")

        # Attach live reputation for event-only rows
        if by_ip:
            try:
                ips = list(by_ip.keys())
                placeholders = ", ".join(["%s"] * len(ips))
                cur.execute(
                    f"""
                    SELECT ip, score, grade, ban_until, ban_reason, negative_points
                    FROM pbt_reputation WHERE ip IN ({placeholders})
                    """,
                    ips,
                )
                live = {str(r["ip"]): r for r in (cur.fetchall() or []) if r.get("ip")}
                for ip, row in by_ip.items():
                    r = live.get(ip) or {}
                    row["live_score"] = r.get("score", row.get("live_score"))
                    row["live_grade"] = r.get("grade", row.get("live_grade"))
                    row["live_ban_until"] = r.get("ban_until", row.get("live_ban_until"))
                    row["live_negative"] = r.get("negative_points")
                    row["reputation_score"] = row.get("live_score") or row.get("reputation_score")
                    row["behavior_grade"] = row.get("live_grade") or row.get("behavior_grade")
            except Exception:
                pass

    finally:
        _close(conn)

    rows = list(by_ip.values())
    if search:
        s = search.lower()
        rows = [
            r
            for r in rows
            if s in (r.get("ip") or "").lower()
            or s in (r.get("notes") or "").lower()
            or s in (r.get("event_type") or "").lower()
        ]
    rows.sort(key=lambda r: str(r.get("timestamp") or ""), reverse=True)
    total = len(rows)
    page = rows[offset : offset + limit]
    return _attach_users_to_event_rows(page), total


def _looks_like_ip(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return False
    # IPv4
    if s.count(".") == 3 and all(p.isdigit() for p in s.split(".")):
        return True
    # IPv6 (colons) — HostM / residential often IPv6
    if ":" in s and any(c.isalnum() for c in s):
        return True
    return False


def _looks_like_device_fp(s: str) -> bool:
    s = (s or "").strip()
    if len(s) < 10 or len(s) > 64:
        return False
    # sha-ish hex fingerprints from device_print
    return all(c in "0123456789abcdefABCDEF" for c in s)


def list_device_sightings_as_events(
    *,
    ip: str = "",
    device_fp: str = "",
    search: str = "",
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """
    Device prints are the real per-browser history for clean traffic.
    Security events only fire on flags/blocks. When Events is filtered by IP/FP
    and pbt_security_events is empty, surface sightings so the page is not dead.
    """
    conn = _sec()
    if conn is None:
        return [], 0
    ip = (ip or "").strip()
    device_fp = (device_fp or "").strip()
    search = (search or "").strip()
    if not ip and not device_fp and search:
        if _looks_like_ip(search):
            ip = search
        elif _looks_like_device_fp(search):
            device_fp = search
        else:
            # free text — try both
            pass
    if not ip and not device_fp and not search:
        return [], 0
    try:
        cur = conn.cursor()
        try:
            from poweredbytop.security.device_print import ensure_device_tables

            ensure_device_tables()
        except Exception:
            pass
        where = []
        params: list = []
        if ip:
            # Exact IPv6 match is critical — LIKE with truncated URLs fails
            where.append("(p.ip = %s OR p.ip LIKE %s)")
            params.extend([ip, f"%{ip}%"])
        if device_fp:
            where.append("(p.device_fp = %s OR p.device_fp LIKE %s)")
            params.extend([device_fp, f"{device_fp}%"])
        if search and not ip and not device_fp:
            where.append(
                "(p.ip LIKE %s OR p.device_fp LIKE %s OR p.user_agent LIKE %s "
                "OR p.last_path LIKE %s OR CAST(p.user_id AS CHAR) LIKE %s)"
            )
            like = f"%{search}%"
            params.extend([like, like, like, like, like])
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        cur.execute(
            f"SELECT COUNT(*) AS c FROM pbt_device_prints p {clause}",
            params,
        )
        total = int((cur.fetchone() or {}).get("c") or 0)
        cur.execute(
            f"""
            SELECT p.device_fp, p.ip, p.user_id, p.hit_count, p.risk_score,
                   p.last_path, p.last_method, p.user_agent, p.first_seen, p.last_seen,
                   p.notes
            FROM pbt_device_prints p
            {clause}
            ORDER BY p.last_seen DESC
            LIMIT %s OFFSET %s
            """,
            params + [int(limit), int(offset)],
        )
        rows = []
        for r in cur.fetchall() or []:
            r = dict(r)
            hits = int(r.get("hit_count") or 0)
            rows.append(
                {
                    "id": None,
                    "timestamp": r.get("last_seen") or r.get("first_seen"),
                    "event_type": "device_sighting",
                    "ip": r.get("ip"),
                    "device_fp": r.get("device_fp"),
                    "event_user_id": r.get("user_id"),
                    "path": r.get("last_path"),
                    "method": r.get("last_method"),
                    "user_agent": r.get("user_agent"),
                    "event_score": None,
                    "event_grade": None,
                    "notes": (
                        f"Browser sighting · hits={hits} · risk={r.get('risk_score') or 0}"
                        f" · first={r.get('first_seen')} · last={r.get('last_seen')}"
                        + (f" · {r.get('notes')}" if r.get("notes") else "")
                    )[:500],
                    "live_score": None,
                    "live_grade": None,
                    "live_negative": None,
                    "reputation_score": None,
                    "behavior_grade": "sighting",
                    "source": "pbt_device_prints",
                    "is_sighting": True,
                    "hit_count": hits,
                }
            )
        return _attach_users_to_event_rows(rows), total
    except Exception as exc:
        print(f"[security] list_device_sightings_as_events: {exc}")
        return [], 0
    finally:
        _close(conn)


def list_security_events(
    *,
    search: str = "",
    event_type: str = "",
    honeypot_only: bool = False,
    ip: str = "",
    device_fp: str = "",
    user_id: int | None = None,
    include_sightings_fallback: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """
    Pipeline attack/flag events from pbt_security_events.

    Also accepts explicit ip= / device_fp= (reliable for IPv6 — do not rely on
    free-text search alone). When those filters match zero security events but
    device prints exist, include_sightings_fallback surfaces those as
    event_type=device_sighting so Devices → Events is never a dead end.
    """
    if honeypot_only:
        return list_honeypot_hits(search=search, limit=limit, offset=offset)

    search = (search or "").strip()
    ip = (ip or "").strip()
    device_fp = (device_fp or "").strip()
    # Promote free-text that is clearly an IP or fingerprint
    if search and not ip and _looks_like_ip(search):
        ip = search
        search = ""
    if search and not device_fp and _looks_like_device_fp(search):
        device_fp = search
        search = ""

    conn = _sec()
    if conn is None:
        # Still try sightings if we can open later
        if include_sightings_fallback and (ip or device_fp):
            return list_device_sightings_as_events(
                ip=ip, device_fp=device_fp, limit=limit, offset=offset
            )
        return [], 0

    where_e = []
    where_plain = []
    params: list = []
    if ip:
        # Exact first (IPv6), then loose
        where_e.append("(e.ip = %s OR e.ip LIKE %s OR e.notes LIKE %s)")
        where_plain.append("(ip = %s OR ip LIKE %s OR notes LIKE %s)")
        like_ip = f"%{ip}%"
        params.extend([ip, like_ip, like_ip])
    if device_fp:
        where_e.append(
            "(e.device_fp = %s OR e.device_fp LIKE %s OR e.notes LIKE %s OR e.notes LIKE %s)"
        )
        where_plain.append(
            "(device_fp = %s OR device_fp LIKE %s OR notes LIKE %s OR notes LIKE %s)"
        )
        params.extend(
            [
                device_fp,
                f"{device_fp}%",
                f"%fp={device_fp}%",
                f"%{device_fp[:16]}%",
            ]
        )
    if user_id:
        where_e.append("e.user_id = %s")
        where_plain.append("user_id = %s")
        params.append(int(user_id))
    if search:
        where_e.append(
            "(e.ip LIKE %s OR e.notes LIKE %s OR e.event_type LIKE %s "
            "OR e.device_fp LIKE %s OR CAST(e.user_id AS CHAR) LIKE %s OR e.path LIKE %s)"
        )
        where_plain.append(
            "(ip LIKE %s OR notes LIKE %s OR event_type LIKE %s "
            "OR device_fp LIKE %s OR CAST(user_id AS CHAR) LIKE %s OR path LIKE %s)"
        )
        like = f"%{search}%"
        params.extend([like, like, like, like, like, like])
    if event_type:
        # sightings are not in this table
        if event_type != "device_sighting":
            where_e.append("e.event_type = %s")
            where_plain.append("event_type = %s")
            params.append(event_type)
    clause_e = ("WHERE " + " AND ".join(where_e)) if where_e else ""
    clause_plain = ("WHERE " + " AND ".join(where_plain)) if where_plain else ""
    total = 0
    rows: list = []
    try:
        cur = conn.cursor()
        # Ensure device_fp column exists so filters don't fall into broken paths
        try:
            from poweredbytop.security_build_db.security_events import create_tables as _evt

            _evt(cur)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

        if event_type == "device_sighting":
            # Only sightings (close conn before opening another)
            try:
                _close(conn)
            except Exception:
                pass
            conn = None
            return list_device_sightings_as_events(
                ip=ip, device_fp=device_fp, search=search, limit=limit, offset=offset
            )

        cur.execute(f"SELECT COUNT(*) AS c FROM pbt_security_events {clause_plain}", params)
        total = int((cur.fetchone() or {}).get("c") or 0)
        cur.execute(
            f"""
            SELECT e.id,
                   COALESCE(e.timestamp, e.created_at) AS timestamp,
                   e.event_type, e.ip,
                   e.device_fp, e.user_id AS event_user_id, e.path, e.method, e.user_agent,
                   e.reputation_score AS event_score,
                   e.behavior_grade AS event_grade,
                   e.notes,
                   r.score AS live_score,
                   r.grade AS live_grade,
                   r.negative_points AS live_negative,
                   r.ban_until AS live_ban_until,
                   COALESCE(r.score, e.reputation_score) AS reputation_score,
                   COALESCE(r.grade, e.behavior_grade, 'normal') AS behavior_grade
            FROM pbt_security_events e
            LEFT JOIN pbt_reputation r ON r.ip = e.ip
            {clause_e}
            ORDER BY COALESCE(e.timestamp, e.created_at) DESC, e.id DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = list(cur.fetchall() or [])
        for r in rows:
            if isinstance(r, dict):
                r["source"] = "pbt_security_events"
                r["is_sighting"] = False
        rows = _attach_users_to_event_rows(rows)
    except Exception as exc:
        print(f"[security] list_security_events: {exc}")
        try:
            where_p2, params2 = [], []
            if ip:
                where_p2.append("(ip = %s OR ip LIKE %s OR notes LIKE %s)")
                like_ip = f"%{ip}%"
                params2.extend([ip, like_ip, like_ip])
            if device_fp:
                where_p2.append("(notes LIKE %s OR notes LIKE %s)")
                params2.extend([f"%fp={device_fp}%", f"%{device_fp[:16]}%"])
            if search:
                where_p2.append("(ip LIKE %s OR notes LIKE %s OR event_type LIKE %s)")
                like = f"%{search}%"
                params2.extend([like, like, like])
            if event_type and event_type != "device_sighting":
                where_p2.append("event_type = %s")
                params2.append(event_type)
            clause_plain = ("WHERE " + " AND ".join(where_p2)) if where_p2 else ""
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) AS c FROM pbt_security_events {clause_plain}", params2)
            total = int((cur.fetchone() or {}).get("c") or 0)
            cur.execute(
                f"""
                SELECT id,
                       COALESCE(timestamp, created_at) AS timestamp,
                       event_type, ip, reputation_score, behavior_grade, notes
                FROM pbt_security_events
                {clause_plain}
                ORDER BY COALESCE(timestamp, created_at) DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                params2 + [limit, offset],
            )
            rows = list(cur.fetchall() or [])
            for r in rows:
                if isinstance(r, dict):
                    r["source"] = "pbt_security_events"
            rows = _attach_users_to_event_rows(rows)
        except Exception as exc2:
            print(f"[security] list_security_events fallback: {exc2}")
            rows, total = [], 0
    finally:
        _close(conn)

    # Fallback: clean traffic has sightings but no attack events
    if (
        include_sightings_fallback
        and total == 0
        and not rows
        and (ip or device_fp or search)
        and (not event_type or event_type == "device_sighting")
    ):
        s_rows, s_total = list_device_sightings_as_events(
            ip=ip, device_fp=device_fp, search=search, limit=limit, offset=offset
        )
        if s_rows:
            return s_rows, s_total

    return rows, total


def _device_fp_from_notes(notes: str | None) -> str:
    """Recover fp=… embedded in notes when device_fp column was null (legacy insert)."""
    if not notes:
        return ""
    import re

    m = re.search(r"\bfp=([a-fA-F0-9]{10,40})\b", str(notes))
    return (m.group(1) if m else "")[:40]


def _users_by_ids(uids: set[int]) -> dict:
    if not uids:
        return {}
    try:
        return {int(u.id): u for u in User.query.filter(User.id.in_(list(uids))).all()}
    except Exception as exc:
        print(f"[security] event username lookup: {exc}")
        return {}


def _user_ids_by_device_fp(fps: list[str]) -> dict[str, int]:
    """device_fp → latest registered user_id from pbt_device_prints."""
    clean = []
    seen: set[str] = set()
    for fp in fps:
        fp = (fp or "").strip()
        if not fp or fp in seen:
            continue
        seen.add(fp)
        clean.append(fp)
    if not clean:
        return {}
    conn = _sec()
    if conn is None:
        return {}
    try:
        cur = conn.cursor()
        chunk = clean[:200]
        ph = ",".join(["%s"] * len(chunk))
        cur.execute(
            f"SELECT device_fp, user_id FROM pbt_device_prints "
            f"WHERE device_fp IN ({ph}) AND user_id IS NOT NULL AND user_id > 0 "
            f"ORDER BY last_seen DESC",
            chunk,
        )
        fp_uid: dict[str, int] = {}
        for r in cur.fetchall() or []:
            fp = (r.get("device_fp") or "").strip()
            if not fp or fp in fp_uid:
                continue
            try:
                uid = int(r.get("user_id") or 0)
            except (TypeError, ValueError):
                uid = 0
            if uid:
                fp_uid[fp] = uid
        return fp_uid
    except Exception as exc:
        print(f"[security] device_fp user lookup: {exc}")
        return {}
    finally:
        _close(conn)


def _attach_users_to_event_rows(rows: list) -> list[dict]:
    """Attach known user↔IP pairs + recover device_fp from notes when missing."""
    if not rows:
        return []
    prepared = []
    uids: set[int] = set()
    fps: list[str] = []
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else dict(r)
        if "timestamp" in d:
            d["timestamp"] = _fmt_ts(d.get("timestamp"))
        ip = (d.get("ip") or "").strip()
        if not d.get("device_fp"):
            recovered = _device_fp_from_notes(d.get("notes"))
            if recovered:
                d["device_fp"] = recovered
                d["device_fp_recovered"] = True
        try:
            uid = int(d.get("event_user_id") or d.get("user_id") or 0)
        except (TypeError, ValueError):
            uid = 0
        if uid:
            d["event_user_id"] = uid
            uids.add(uid)
        fp = (d.get("device_fp") or "").strip()
        if fp:
            fps.append(fp)
        linked = list_users_for_ip(ip, limit=8) if ip else []
        d["linked_users"] = linked
        d["linked_users_label"] = (
            ", ".join(f"{x['username']} ({x['role']})" for x in linked[:4])
            if linked
            else ""
        )
        prepared.append(d)

    fp_uids = _user_ids_by_device_fp(fps) if fps else {}
    for d in prepared:
        if d.get("event_user_id"):
            continue
        uid = fp_uids.get((d.get("device_fp") or "").strip())
        if uid:
            d["event_user_id"] = uid
            uids.add(uid)

    umap = _users_by_ids(uids)
    out = []
    for d in prepared:
        uid = d.get("event_user_id")
        u = umap.get(int(uid)) if uid else None
        d["event_username"] = getattr(u, "username", None) if u else None
        d["event_role"] = getattr(u, "role", None) if u else None
        out.append(d)
    return out


def list_event_types() -> list[str]:
    conn = _sec()
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT event_type FROM pbt_security_events ORDER BY event_type ASC LIMIT 100"
        )
        rows = cur.fetchall() or []
        return [r["event_type"] for r in rows if r.get("event_type")]
    except Exception:
        return []
    finally:
        _close(conn)


# Map security event names → canonical attack-total buckets
_EVENT_TO_ATTACK_TYPE = {
    "attack_path_probe": "attack_path_probe",
    "early_block_attack_path": "attack_path_probe",
    "known_attacker_ua": "known_attacker_ua",
    "early_block_attacker_ua": "known_attacker_ua",
    "bot_attempt": "bot_attempt",
    "brute_force": "brute_force",
    "brute_force_lock": "brute_force",
    "token_attack": "token_attack",
    "invalid_token": "token_attack",
    "ddos_attempts": "ddos_attempts",
    "rate_limit": "rate_limit",
    "rate_limit_exceeded": "rate_limit",
    "rate_limited_request": "rate_limit",
    "refresh_spam": "rate_limit",
    "n1_attack": "n1_attack",
    "n1_query_detected": "n1_attack",
    "honeypot": "honeypot",
    "honeypot_ban": "honeypot",
    "honeypot_hit": "honeypot",
    "unlinked_probe": "honeypot",
    "banned_ip_block": "banned_ip_block",
    "perm_ban_block": "banned_ip_block",
    "ip_ban_soft_allow": "banned_ip_block",
    "ip_ban_soft_allow_clean_device": "banned_ip_block",
    "banned_device_block": "banned_device_block",
    "device_ban_soft_established": "banned_device_block",
    "reputation_block": "reputation_block",
    "low_reputation": "low_reputation",
    "failed_login": "failed_login",
    "csrf": "csrf",
    "csrf_failure": "csrf",
    "csrf_attack": "csrf",
    "csrf_soft_auth": "csrf",
    "csrf_soft_member": "csrf",
    "csrf_member_cross_origin": "csrf",
    "xss": "xss",
    "xss_attempt": "xss",
    "xss_block": "xss",
    "csrf_xss": "xss",
    "suspicious_ua": "suspicious_ua",
    "tenant_id_tamper": "token_attack",
    "session_bind_fail": "token_attack",
    "recon_scan": "known_attacker_ua",
    "attack_path_soft_established": "attack_path_probe",
    "attacker_ua_soft_established": "known_attacker_ua",
    "security_test_would_block": "security_test_would_block",
}

# Non-threats only. Soft-allows, bans, CSRF, rate limits still count.
_SKIP_EVENT_TYPES = frozenset(
    {
        "exception",
        "full_pass",
        "internal_bypass",
        "pass",
        "good_behavior",
        "vetted",
        "not_vetted",
        "csrf_grace_member",
        "csrf_field_stale",
    }
)


def _canonical_attack_type(raw: str | None) -> str | None:
    if not raw:
        return None
    key = str(raw).strip().lower()
    if not key or key in _SKIP_EVENT_TYPES:
        return None
    if key in _EVENT_TO_ATTACK_TYPE:
        return _EVENT_TO_ATTACK_TYPE[key]
    if "honeypot" in key or "unlinked" in key:
        return "honeypot"
    if "ddos" in key:
        return "ddos_attempts"
    if "brute" in key:
        return "brute_force"
    if "rate" in key or "refresh_spam" in key:
        return "rate_limit"
    if "xss" in key:
        return "xss"
    if "csrf" in key:
        return "csrf"
    if "token" in key:
        return "token_attack"
    if "banned_device" in key or "device_ban" in key:
        return "banned_device_block"
    if "banned_ip" in key or "ip_ban" in key or key.startswith("perm_ban"):
        return "banned_ip_block"
    if "security_test" in key or "would_block" in key:
        return "security_test_would_block"
    return key[:64]


def _merge_attack_row(
    by_type: dict,
    attack_type: str,
    *,
    total: int = 0,
    blocked: int = 0,
    last_ip: str | None = None,
    last_time=None,
    severity=None,
    notes: str | None = None,
) -> None:
    """Keep higher counters; prefer the newest last_time / matching IP."""
    if not attack_type:
        return
    total = int(total or 0)
    blocked = int(blocked or 0)
    cur = by_type.get(attack_type)
    if cur is None:
        by_type[attack_type] = {
            "attack_type": attack_type,
            "total_attempts": total,
            "blocked_count": blocked,
            "last_attack_ip": last_ip,
            "last_attack_time": last_time,
            "severity_level": severity,
            "notes": notes,
        }
        return
    cur["total_attempts"] = max(int(cur.get("total_attempts") or 0), total)
    cur["blocked_count"] = max(int(cur.get("blocked_count") or 0), blocked)
    # Prefer newer timestamp
    old_t = cur.get("last_attack_time")
    if last_time is not None and (old_t is None or last_time > old_t):
        cur["last_attack_time"] = last_time
        if last_ip:
            cur["last_attack_ip"] = last_ip
    elif not cur.get("last_attack_ip") and last_ip:
        cur["last_attack_ip"] = last_ip
    if severity is not None and cur.get("severity_level") is None:
        cur["severity_level"] = severity
    if notes and not cur.get("notes"):
        cur["notes"] = notes


def list_attack_stats() -> list[dict]:
    """
    Full attack breakdown for the Security console.

    Historically only early-block paths wrote pbt_attack_stats (known_attacker_ua,
    attack_path_probe). DDoS, rate limits, honeypots, failed logins, banned-IP
    blocks lived only in pbt_security_events / pbt_reputation. Merge all sources
    so the dashboard is not stuck at those two rows.
    """
    conn = _sec()
    if conn is None:
        return []
    by_type: dict[str, dict] = {}
    try:
        cur = conn.cursor()

        # 1) Dedicated attack counters table
        try:
            cur.execute(
                """
                SELECT attack_type, total_attempts, blocked_count, last_attack_ip,
                       last_attack_time, severity_level, notes
                FROM pbt_attack_stats
                """
            )
            for r in cur.fetchall() or []:
                at = _canonical_attack_type(r.get("attack_type"))
                if not at:
                    continue
                _merge_attack_row(
                    by_type,
                    at,
                    total=r.get("total_attempts") or 0,
                    blocked=r.get("blocked_count") or 0,
                    last_ip=r.get("last_attack_ip"),
                    last_time=r.get("last_attack_time"),
                    severity=r.get("severity_level"),
                    notes=r.get("notes"),
                )
        except Exception as exc:
            print(f"[security] list_attack_stats table: {exc}")

        # 2) Live aggregate from security events (covers rate_limit, honeypot_ban, etc.)
        for sql in (
            """
            SELECT event_type,
                   COUNT(*) AS c,
                   SUBSTRING_INDEX(
                       GROUP_CONCAT(ip ORDER BY COALESCE(timestamp, created_at) DESC SEPARATOR ','),
                       ',', 1
                   ) AS last_ip,
                   MAX(COALESCE(timestamp, created_at)) AS last_time
            FROM pbt_security_events
            GROUP BY event_type
            """,
            """
            SELECT event_type,
                   COUNT(*) AS c,
                   SUBSTRING_INDEX(
                       GROUP_CONCAT(ip ORDER BY created_at DESC SEPARATOR ','),
                       ',', 1
                   ) AS last_ip,
                   MAX(created_at) AS last_time
            FROM pbt_security_events
            GROUP BY event_type
            """,
        ):
            try:
                cur.execute(sql)
                for r in cur.fetchall() or []:
                    at = _canonical_attack_type(r.get("event_type"))
                    if not at:
                        continue
                    c = int(r.get("c") or 0)
                    _merge_attack_row(
                        by_type,
                        at,
                        total=c,
                        blocked=c,
                        last_ip=r.get("last_ip"),
                        last_time=r.get("last_time"),
                        notes="from security events",
                    )
                break
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass

        # 3) Honeypot: unique IPs from events + reputation (events insert often failed)
        try:
            hp_count = count_honeypot_hits(conn=conn)
            if hp_count:
                last_ip = None
                last_time = None
                try:
                    cur.execute(
                        """
                        SELECT ip, last_seen AS last_time FROM pbt_reputation
                        WHERE ban_reason LIKE %s OR ban_reason LIKE %s
                        ORDER BY last_seen DESC LIMIT 1
                        """,
                        ("%honeypot%", "%unlinked_probe%"),
                    )
                    row = cur.fetchone() or {}
                    last_ip = row.get("ip")
                    last_time = row.get("last_time")
                except Exception:
                    pass
                if not last_ip:
                    try:
                        cur.execute(
                            """
                            SELECT ip, COALESCE(timestamp, created_at) AS last_time
                            FROM pbt_security_events
                            WHERE event_type LIKE %s OR notes LIKE %s
                            ORDER BY COALESCE(timestamp, created_at) DESC LIMIT 1
                            """,
                            ("%honeypot%", "%honeypot%"),
                        )
                        row = cur.fetchone() or {}
                        last_ip = row.get("ip")
                        last_time = row.get("last_time")
                    except Exception:
                        pass
                _merge_attack_row(
                    by_type,
                    "honeypot",
                    total=hp_count,
                    blocked=hp_count,
                    last_ip=last_ip,
                    last_time=last_time,
                    notes="unique honeypot IPs (events + reputation bans)",
                )
        except Exception as exc:
            print(f"[security] list_attack_stats honeypot: {exc}")

        # 4) DDoS / hard reasons only present on reputation.ban_reason (no event row)
        try:
            cur.execute(
                """
                SELECT
                  CASE
                    WHEN ban_reason LIKE %s THEN 'ddos_attempts'
                    WHEN ban_reason LIKE %s OR ban_reason LIKE %s THEN 'honeypot'
                    WHEN ban_reason LIKE %s THEN 'brute_force'
                    WHEN ban_reason LIKE %s THEN 'attack_path_probe'
                    WHEN ban_reason LIKE %s THEN 'known_attacker_ua'
                    WHEN ban_reason LIKE %s THEN 'token_attack'
                    ELSE NULL
                  END AS attack_type,
                  COUNT(*) AS c,
                  SUBSTRING_INDEX(
                      GROUP_CONCAT(ip ORDER BY last_seen DESC SEPARATOR ','),
                      ',', 1
                  ) AS last_ip,
                  MAX(last_seen) AS last_time
                FROM pbt_reputation
                WHERE ban_reason IS NOT NULL AND ban_reason != ''
                GROUP BY attack_type
                HAVING attack_type IS NOT NULL
                """,
                (
                    "%ddos%",
                    "%honeypot%",
                    "%unlinked%",
                    "%brute%",
                    "%attack_path%",
                    "%attacker_ua%",
                    "%token%",
                ),
            )
            for r in cur.fetchall() or []:
                at = r.get("attack_type")
                if not at:
                    continue
                c = int(r.get("c") or 0)
                _merge_attack_row(
                    by_type,
                    at,
                    total=c,
                    blocked=c,
                    last_ip=r.get("last_ip"),
                    last_time=r.get("last_time"),
                    notes="from reputation ban_reason",
                )
        except Exception as exc:
            print(f"[security] list_attack_stats reputation reasons: {exc}")

        rows = list(by_type.values())
        rows.sort(
            key=lambda r: (
                r.get("last_attack_time") is None,
                r.get("last_attack_time") or datetime.min,
                -(int(r.get("blocked_count") or r.get("total_attempts") or 0)),
            ),
            reverse=True,
        )
        # datetime.min sort with reverse is awkward — re-sort cleanly:
        rows.sort(
            key=lambda r: (
                r.get("last_attack_time") or datetime.min,
                int(r.get("blocked_count") or r.get("total_attempts") or 0),
            ),
            reverse=True,
        )
        for r in rows:
            r["last_attack_time"] = _fmt_ts(r.get("last_attack_time"))
        return rows
    except Exception as exc:
        print(f"[security] list_attack_stats: {exc}")
        return []
    finally:
        _close(conn)


def list_reputation_rows(
    *,
    filter_mode: str = "bans",
    search: str = "",
    limit: int = 150,
) -> list[dict]:
    conn = _sec()
    if conn is None:
        return []
    where = []
    params: list = []
    if filter_mode == "bans":
        where.append(
            "(grade IN ('temp_ban', 'perm_ban') OR (ban_until IS NOT NULL AND ban_until > NOW()))"
        )
    elif filter_mode == "low":
        where.append("score < 50")
    if search:
        where.append("(ip LIKE %s OR ban_reason LIKE %s OR grade LIKE %s)")
        like = f"%{search}%"
        params.extend([like, like, like])
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT ip, score, grade, positive_requests, negative_points,
                   ban_until, ban_reason, ban_count, first_seen, last_seen, last_bad_behavior
            FROM pbt_reputation
            {clause}
            ORDER BY ban_until DESC, last_seen DESC, score ASC
            LIMIT %s
            """,
            params + [limit],
        )
        rows = list(cur.fetchall() or [])
        now = datetime.now()
        for r in rows:
            until = r.get("ban_until")
            r["is_active_ban"] = r.get("grade") in ("temp_ban", "perm_ban") or (
                until is not None and until > now
            )
        return rows
    except Exception as exc:
        print(f"[security] list_reputation_rows: {exc}")
        return []
    finally:
        _close(conn)


def list_account_login_locks() -> list[dict]:
    try:
        rows = (
            User.query.filter(
                User.account_locked_until.isnot(None),
                User.account_locked_until > func.now(),
            )
            .order_by(User.account_locked_until.asc())
            .all()
        )
        # Fallback if func.now() comparison fails with aware/naive mix
        if not rows:
            now = now_naive_storage()
            rows = (
                User.query.filter(User.account_locked_until.isnot(None))
                .order_by(User.account_locked_until.asc())
                .all()
            )
            cleaned = []
            for u in rows:
                lock = u.account_locked_until
                if lock is None:
                    continue
                try:
                    if lock.replace(tzinfo=None) > now:
                        cleaned.append(u)
                except Exception:
                    cleaned.append(u)
            rows = cleaned

        out = []
        for u in rows:
            house = getattr(u, "household", None)
            out.append(
                {
                    "id": u.id,
                    "username": u.username,
                    "email": u.email,
                    "role": u.role,
                    "household_id": u.household_id,
                    "household": getattr(house, "name", None) or "",
                    "failed_login_attempts": u.failed_login_attempts or 0,
                    "account_locked_until": u.account_locked_until,
                    "full_name": u.get_full_name() if hasattr(u, "get_full_name") else u.username,
                }
            )
        return out
    except Exception as exc:
        print(f"[security] list_account_login_locks: {exc}")
        return []


def list_security_grants() -> list[dict]:
    ensure_security_grants_table()
    try:
        rows = db.session.execute(
            text(
                """
                SELECT g.id, g.user_id, g.notes, g.created_at, g.granted_by,
                       u.username, u.email, u.role, u.first_name, u.last_name,
                       gb.username AS granted_by_name
                FROM security_area_grants g
                JOIN users u ON u.id = g.user_id
                LEFT JOIN users gb ON gb.id = g.granted_by
                ORDER BY g.created_at DESC
                """
            )
        ).mappings().all()
        return [dict(r) for r in rows]
    except Exception as exc:
        print(f"[security] list_security_grants: {exc}")
        return []


def grant_security_access(user_id: int, granted_by: int, notes: str | None = None) -> None:
    ensure_security_grants_table()
    db.session.execute(
        text(
            """
            INSERT INTO security_area_grants (user_id, granted_by, notes)
            VALUES (:uid, :by, :notes)
            ON DUPLICATE KEY UPDATE
                granted_by = VALUES(granted_by),
                notes = VALUES(notes),
                created_at = CURRENT_TIMESTAMP
            """
        ),
        {"uid": user_id, "by": granted_by, "notes": (notes or "")[:255] or None},
    )
    db.session.commit()


def revoke_security_access(user_id: int) -> bool:
    ensure_security_grants_table()
    res = db.session.execute(
        text("DELETE FROM security_area_grants WHERE user_id = :uid"),
        {"uid": user_id},
    )
    db.session.commit()
    return (res.rowcount or 0) > 0


def find_user_by_username(username: str) -> dict | None:
    if not username:
        return None
    u = User.query.filter_by(username=username.strip()).first()
    if not u:
        return None
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "role": u.role,
        "first_name": u.first_name,
        "last_name": u.last_name,
    }


# ---------- Robust audit log ----------

def _platform_audit():
    try:
        from app.builddb.table_platform_audit import PlatformAudit

        return PlatformAudit
    except Exception:
        return None


def list_audit_actions(limit: int = 200) -> list[str]:
    Model = _platform_audit()
    if Model is None:
        return []
    try:
        rows = (
            db.session.query(Model.action)
            .distinct()
            .order_by(Model.action.asc())
            .limit(limit)
            .all()
        )
        return [r[0] for r in rows if r[0]]
    except Exception:
        return []


def resolve_user_ids_from_query(user_q: str) -> list[int]:
    """Resolve username / email / numeric id fragments to user IDs."""
    q = (user_q or "").strip()
    if not q:
        return []
    if q.isdigit():
        return [int(q)]
    term = f"%{q}%"
    rows = (
        User.query.filter(
            or_(
                User.username.ilike(term),
                User.email.ilike(term),
                User.first_name.ilike(term),
                User.last_name.ilike(term),
            )
        )
        .limit(50)
        .all()
    )
    return [u.id for u in rows]


def search_users(term: str, limit: int = 25) -> list[dict]:
    t = (term or "").strip()
    if not t:
        return []
    like = f"%{t}%"
    clauses = [User.username.ilike(like), User.email.ilike(like), User.name.ilike(like)]
    if t.isdigit():
        clauses.append(User.id == int(t))
    rows = (
        User.query.filter(or_(*clauses))
        .order_by(User.username.asc())
        .limit(limit)
        .all()
    )
    out = []
    for u in rows:
        house = getattr(u, "household", None)
        hname = getattr(house, "name", None) or ""
        out.append(
            {
                "id": u.id,
                "username": u.username,
                "name": u.name or "",
                "email": u.email or "",
                "role": u.role or "",
                "household_id": u.household_id,
                "household": hname,
                "is_active": bool(u.is_active),
                "label": f"{u.username} · {u.role}"
                + (f" · {hname}" if hname else "")
                + (f" · {u.email}" if u.email else ""),
            }
        )
    return out


def list_sponsors_for_filter(limit: int = 200) -> list[dict]:
    rows = (
        User.query.filter_by(role="security_company")
        .order_by(User.username.asc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": u.id,
            "username": u.username,
            "label": (u.get_full_name() if hasattr(u, "get_full_name") else None)
            or u.username,
        }
        for u in rows
    ]


def user_ids_for_sponsor(sponsor_id: int) -> list[int]:
    """All users under a sponsor: self, sponsor_admins, guards, clients of their companies."""
    try:
        from app.builddb.table_companies import Company

        client_ids = [
            c.id
            for c in Company.query.filter_by(security_company_id=sponsor_id).all()
        ]
        ids = {int(sponsor_id)}
        q = User.query.filter(
            or_(
                User.security_company_id == sponsor_id,
                User.id == sponsor_id,
            )
        )
        for u in q.all():
            ids.add(u.id)
        if client_ids:
            for u in User.query.filter(
                User.company_id.in_(client_ids),
                User.role.in_(("clients", "client", "client_admin", "employee", "staff")),
            ).all():
                ids.add(u.id)
        return list(ids)
    except Exception as exc:
        print(f"[security] user_ids_for_sponsor: {exc}")
        return [int(sponsor_id)]


def _device_fp_from_extra(extra) -> str:
    if not extra:
        return ""
    if isinstance(extra, dict):
        return str(extra.get("device_fp") or extra.get("device_fingerprint") or "")[:40]
    if isinstance(extra, str):
        try:
            import json as _json
            data = _json.loads(extra)
            if isinstance(data, dict):
                return str(data.get("device_fp") or "")[:40]
        except Exception:
            pass
    return ""


def list_audit_logs(
    *,
    search: str = "",
    action: str = "",
    user_id: int | None = None,
    user_q: str = "",
    ip: str = "",
    device_fp: str = "",
    days: int | None = 7,
    limit: int = 50,
    offset: int = 0,
    reversible_only: bool = False,
    sponsor_id: int | None = None,
    role_filter: str = "",
) -> tuple[list[dict], int]:
    """Owner-console audit (platform_audit). Household scans/notes are not here."""
    Model = _platform_audit()
    if Model is None:
        return [], 0
    try:
        q = Model.query
        if days and days > 0:
            since = now_naive_storage() - timedelta(days=int(days))
            q = q.filter(Model.created_at >= since)
        if action:
            q = q.filter(Model.action == action)
        if user_id:
            q = q.filter(Model.owner_id == int(user_id))
        if ip:
            q = q.filter(Model.ip.ilike(f"%{ip}%"))
        if search:
            term = f"%{search}%"
            q = q.filter(
                or_(
                    Model.action.ilike(term),
                    text("CAST(detail_json AS CHAR) LIKE :sterm").bindparams(sterm=term),
                    Model.ip.ilike(term),
                )
            )
        hid = None
        try:
            hid = int(role_filter) if role_filter and str(role_filter).isdigit() else None
        except Exception:
            hid = None
        if sponsor_id:
            q = q.filter(Model.household_id == int(sponsor_id))
        elif hid:
            q = q.filter(Model.household_id == hid)
        total = q.count()
        rows = (
            q.order_by(Model.created_at.desc(), Model.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        result = []
        for log in rows:
            detail = log.detail_json if isinstance(log.detail_json, dict) else {}
            result.append(
                {
                    "id": log.id,
                    "timestamp": format_for_user(log.created_at) if log.created_at else "—",
                    "created_at": log.created_at,
                    "actor": f"owner #{log.owner_id}" if log.owner_id else "owner",
                    "actor_id": log.owner_id,
                    "action": log.action or "—",
                    "description": str(detail) if detail else "",
                    "target": f"household #{log.household_id}" if log.household_id else "—",
                    "household_id": log.household_id,
                    "ip_address": log.ip or "—",
                    "device_fp": "—",
                    "extra_data": detail,
                    "can_reverse": False,
                }
            )
        return result, total
    except Exception as exc:
        print(f"[security] list_audit_logs: {exc}")
        return [], 0


def list_devices_for_user(user_id: int, limit: int = 50) -> list[dict]:
    """All device fingerprints seen for this user (guard device switches, etc.)."""
    if not user_id:
        return []
    return list_device_prints(search=str(int(user_id)), filter_mode="recent", limit=limit, user_id=int(user_id))


def get_user_security_profile(user_id: int) -> dict | None:
    """User detail for security console: identity, IPs, devices, recent audit."""
    user = User.query.get(user_id)
    if not user:
        return None
    ips = list_ips_for_user(user_id, limit=50)
    devices = list_devices_for_user(user_id, limit=40)
    house = getattr(user, "household", None)
    triggered, triggered_total = list_security_events(
        user_id=int(user_id),
        include_sightings_fallback=False,
        limit=80,
        offset=0,
    )
    timeline = _user_activity_timeline([], triggered, limit=80)
    distinct_devices = len({d.get("device_fp") for d in devices if d.get("device_fp")})
    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "name": user.name or "",
            "email": user.email or "",
            "role": user.role or "",
            "is_active": bool(user.is_active),
            "household_id": user.household_id,
            "household": getattr(house, "name", None) or "",
            "last_login_at": format_for_user(getattr(user, "last_login_at", None)) if getattr(user, "last_login_at", None) else None,
            "failed_login_attempts": getattr(user, "failed_login_attempts", 0) or 0,
        },
        "ips": ips,
        "devices": devices,
        "distinct_device_count": distinct_devices,
        "audit_ips": [{"ip": r.get("ip"), "count": r.get("hit_count") or 0} for r in ips],
        "recent_audit": [],
        "audit_total": 0,
        "triggered_events": triggered,
        "triggered_total": triggered_total,
        "timeline": timeline,
    }


def _user_activity_timeline(
    audits: list[dict],
    events: list[dict],
    *,
    limit: int = 80,
) -> list[dict]:
    """One user trail: triggered events + app audits, each row with IP + device."""
    rows: list[dict] = []
    for e in events or []:
        if e.get("is_sighting") or e.get("event_type") == "device_sighting":
            continue
        rows.append(
            {
                "kind": "security_event",
                "ts": _fmt_ts(e.get("timestamp") or e.get("ts") or e.get("created_at")),
                "action": e.get("event_type") or "event",
                "target": (e.get("path") or "—"),
                "ip": e.get("ip") or "",
                "device_fp": e.get("device_fp") or "",
                "description": (e.get("notes") or "")[:400],
                "can_reverse": False,
                "id": e.get("id"),
            }
        )
    for a in audits or []:
        ip = a.get("ip_address") or ""
        if ip == "—":
            ip = ""
        fp = a.get("device_fp") or ""
        if fp == "—":
            fp = ""
        rows.append(
            {
                "kind": "app_audit",
                "ts": a.get("timestamp") or a.get("created_at"),
                "action": a.get("action") or "audit",
                "target": a.get("target") or "—",
                "ip": ip,
                "device_fp": fp,
                "description": a.get("description") or "",
                "can_reverse": bool(a.get("can_reverse")),
                "reversed_at": a.get("reversed_at"),
                "id": a.get("id"),
            }
        )

    def _key(item):
        return str(item.get("ts") or "")

    rows.sort(key=_key, reverse=True)
    return rows[: int(limit)]


def list_ips_for_user(user_id: int, limit: int = 50) -> list[dict]:
    try:
        from app.builddb.table_user_ip_sightings import UserIpSighting

        rows = (
            UserIpSighting.query.filter_by(user_id=user_id)
            .order_by(UserIpSighting.last_seen_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "ip": r.ip_address,
                "hit_count": r.hit_count,
                "first_seen": format_for_user(r.first_seen_at) if r.first_seen_at else "—",
                "last_seen": format_for_user(r.last_seen_at) if r.last_seen_at else "—",
                "user_agent": r.last_user_agent or "",
                "source": r.source or "",
            }
            for r in rows
        ]
    except Exception as exc:
        print(f"[security] list_ips_for_user: {exc}")
        return []


def list_users_for_ip(ip: str, limit: int = 50) -> list[dict]:
    ip = (ip or "").strip()
    if not ip:
        return []
    try:
        from app.builddb.table_user_ip_sightings import UserIpSighting

        rows = (
            UserIpSighting.query.filter(UserIpSighting.ip_address.ilike(f"%{ip}%"))
            .order_by(UserIpSighting.last_seen_at.desc())
            .limit(limit)
            .all()
        )
        uids = {r.user_id for r in rows}
        umap = {u.id: u for u in User.query.filter(User.id.in_(list(uids))).all()} if uids else {}
        out = []
        for r in rows:
            u = umap.get(r.user_id)
            out.append(
                {
                    "user_id": r.user_id,
                    "username": u.username if u else f"#{r.user_id}",
                    "role": u.role if u else "—",
                    "email": (u.email if u else "") or "",
                    "ip": r.ip_address,
                    "hit_count": r.hit_count,
                    "last_seen": format_for_user(r.last_seen_at) if r.last_seen_at else "—",
                }
            )
        return out
    except Exception as exc:
        print(f"[security] list_users_for_ip: {exc}")
        return []


def list_recent_ip_pairs(limit: int = 80) -> list[dict]:
    try:
        from app.builddb.table_user_ip_sightings import UserIpSighting

        rows = (
            UserIpSighting.query.order_by(UserIpSighting.last_seen_at.desc())
            .limit(limit)
            .all()
        )
        uids = {r.user_id for r in rows}
        umap = {u.id: u for u in User.query.filter(User.id.in_(list(uids))).all()} if uids else {}
        out = []
        for r in rows:
            u = umap.get(r.user_id)
            out.append(
                {
                    "user_id": r.user_id,
                    "username": u.username if u else f"#{r.user_id}",
                    "role": u.role if u else "—",
                    "ip": r.ip_address,
                    "hit_count": r.hit_count,
                    "last_seen": format_for_user(r.last_seen_at) if r.last_seen_at else "—",
                    "first_seen": format_for_user(r.first_seen_at) if r.first_seen_at else "—",
                }
            )
        return out
    except Exception as exc:
        print(f"[security] list_recent_ip_pairs: {exc}")
        return []


def audit_action_counts(days: int = 7, limit: int = 15) -> list[dict]:
    Model = _platform_audit()
    if Model is None:
        return []
    try:
        since = now_naive_storage() - timedelta(days=max(1, int(days)))
        rows = (
            db.session.query(Model.action, func.count(Model.id).label("c"))
            .filter(Model.created_at >= since)
            .group_by(Model.action)
            .order_by(func.count(Model.id).desc())
            .limit(limit)
            .all()
        )
        return [{"action": a, "count": int(c)} for a, c in rows]
    except Exception as exc:
        print(f"[security] audit_action_counts: {exc}")
        return []


def _batch_event_stats_for_devices(
    cur, fps: list[str], ips: list[str]
) -> tuple[dict, dict]:
    """
    Returns (by_fp, by_ip) maps with event_count, last_event_type, last_event_at, last_notes.
    by_fp is authoritative; by_ip fills gaps when events predate device_fp column.
    """
    by_fp: dict = {}
    by_ip: dict = {}
    fps = [f for f in fps if f]
    ips = [i for i in ips if i]
    if not fps and not ips:
        return by_fp, by_ip
    try:
        if fps:
            placeholders = ",".join(["%s"] * len(fps))
            cur.execute(
                f"""
                SELECT device_fp,
                       COUNT(*) AS c,
                       MAX(COALESCE(timestamp, created_at)) AS last_at
                FROM pbt_security_events
                WHERE device_fp IN ({placeholders})
                GROUP BY device_fp
                """,
                fps,
            )
            for row in cur.fetchall() or []:
                fp = row.get("device_fp")
                if not fp:
                    continue
                by_fp[fp] = {
                    "event_count": int(row.get("c") or 0),
                    "last_event_at": row.get("last_at"),
                    "last_event_type": None,
                    "last_notes": None,
                }
            # Latest event type/notes per fp
            cur.execute(
                f"""
                SELECT e.device_fp, e.event_type, e.notes, e.ip,
                       COALESCE(e.timestamp, e.created_at) AS ts
                FROM pbt_security_events e
                INNER JOIN (
                    SELECT device_fp, MAX(id) AS max_id
                    FROM pbt_security_events
                    WHERE device_fp IN ({placeholders})
                    GROUP BY device_fp
                ) t ON t.max_id = e.id
                """,
                fps,
            )
            for row in cur.fetchall() or []:
                fp = row.get("device_fp")
                if fp and fp in by_fp:
                    by_fp[fp]["last_event_type"] = row.get("event_type")
                    by_fp[fp]["last_notes"] = (row.get("notes") or "")[:200]
                    by_fp[fp]["last_event_ip"] = row.get("ip")
        if ips:
            placeholders = ",".join(["%s"] * len(ips))
            cur.execute(
                f"""
                SELECT ip,
                       COUNT(*) AS c,
                       MAX(COALESCE(timestamp, created_at)) AS last_at
                FROM pbt_security_events
                WHERE ip IN ({placeholders})
                GROUP BY ip
                """,
                ips,
            )
            for row in cur.fetchall() or []:
                ip = row.get("ip")
                if not ip:
                    continue
                by_ip[ip] = {
                    "event_count": int(row.get("c") or 0),
                    "last_event_at": row.get("last_at"),
                }
            cur.execute(
                f"""
                SELECT e.ip, e.event_type, e.notes, e.device_fp,
                       COALESCE(e.timestamp, e.created_at) AS ts
                FROM pbt_security_events e
                INNER JOIN (
                    SELECT ip, MAX(id) AS max_id
                    FROM pbt_security_events
                    WHERE ip IN ({placeholders})
                    GROUP BY ip
                ) t ON t.max_id = e.id
                """,
                ips,
            )
            for row in cur.fetchall() or []:
                ip = row.get("ip")
                if ip and ip in by_ip:
                    by_ip[ip]["last_event_type"] = row.get("event_type")
                    by_ip[ip]["last_notes"] = (row.get("notes") or "")[:200]
                    by_ip[ip]["last_event_device_fp"] = row.get("device_fp")
    except Exception as exc:
        print(f"[security] _batch_event_stats_for_devices: {exc}")
    return by_fp, by_ip


def _batch_ip_reputation(cur, ips: list[str]) -> dict:
    out: dict = {}
    ips = [i for i in ips if i]
    if not ips:
        return out
    try:
        placeholders = ",".join(["%s"] * len(ips))
        cur.execute(
            f"""
            SELECT ip, score, grade, ban_until, ban_reason, positive_requests, negative_points
            FROM pbt_reputation
            WHERE ip IN ({placeholders})
            """,
            ips,
        )
        for row in cur.fetchall() or []:
            ip = row.get("ip")
            if ip:
                out[ip] = dict(row)
    except Exception as exc:
        print(f"[security] _batch_ip_reputation: {exc}")
    return out


def _batch_audit_counts_for_fps(fps: list[str]) -> dict[str, int]:
    """Count audit_logs rows that mention each device_fp in extra_data or description."""
    counts: dict[str, int] = {}
    fps = [f for f in fps if f and len(f) >= 8]
    if not fps:
        return counts
    try:
        # One scan of recent audits that look device-related, then tally in Python
        # (avoids N LIKE queries against large audit_logs)
        rows = (
            AuditLog.query.filter(
                or_(
                    AuditLog.action.ilike("%device%"),
                    AuditLog.action.ilike("%security_%"),
                    text("CAST(extra_data AS CHAR) LIKE '%device_fp%'"),
                )
            )
            .order_by(AuditLog.id.desc())
            .limit(4000)
            .all()
        )
        for log in rows:
            blob = ""
            try:
                blob = f"{log.action or ''} {log.description or ''} {log.extra_data or ''}"
            except Exception:
                blob = str(log.description or "")
            blob_l = blob.lower()
            for fp in fps:
                if fp.lower() in blob_l or fp[:16].lower() in blob_l:
                    counts[fp] = counts.get(fp, 0) + 1
    except Exception as exc:
        print(f"[security] _batch_audit_counts_for_fps: {exc}")
    return counts


def list_device_prints(
    *,
    search: str = "",
    filter_mode: str = "recent",
    limit: int = 100,
    user_id: int | None = None,
) -> list[dict]:
    """
    filter_mode:
      recent  — latest sightings
      risk    — highest risk_score
      banned  — only fingerprints with active device ban
      trusted — operator-trusted devices
    user_id — only devices paired to this user (guard multi-device checks)

    Enriched with IP reputation, security-event counts (by device_fp + IP),
    linked users on that IP, and audit hits that mention the fingerprint.
    """
    conn = _sec()
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        try:
            from poweredbytop.security.device_print import ensure_device_tables

            ensure_device_tables()
        except Exception:
            pass
        # Ensure security_events has device_fp column for joins
        try:
            from poweredbytop.security_build_db.security_events import create_tables as _evt

            _evt(cur)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

        where = []
        params: list = []
        if user_id:
            where.append("p.user_id = %s")
            params.append(int(user_id))
        if search:
            where.append(
                "(p.device_fp LIKE %s OR p.ip LIKE %s OR p.user_agent LIKE %s "
                "OR CAST(p.user_id AS CHAR) LIKE %s OR p.last_path LIKE %s "
                "OR COALESCE(p.notes,'') LIKE %s)"
            )
            like = f"%{search}%"
            params.extend([like, like, like, like, like, like])
        if filter_mode == "banned":
            where.append(
                "(b.permanent = 1 OR (b.ban_until IS NOT NULL AND b.ban_until > NOW()))"
            )
        elif filter_mode == "trusted":
            where.append("t.grade IN ('trusted', 'good')")
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        order = "p.last_seen DESC"
        if filter_mode == "risk":
            order = "p.risk_score DESC, p.last_seen DESC"

        sql_with_trust = f"""
            SELECT p.device_fp, p.ip, p.ua_hash, p.user_agent, p.accept_language,
                   p.user_id, p.hit_count, p.first_seen, p.last_seen,
                   p.last_path, p.last_method, p.risk_score, p.notes,
                   b.ban_until, b.ban_reason, b.ban_count, b.permanent,
                   t.score AS trust_score, t.grade AS trust_grade, t.notes AS trust_notes
            FROM pbt_device_prints p
            LEFT JOIN pbt_device_bans b ON b.device_fp = p.device_fp
            LEFT JOIN pbt_device_trust t ON t.device_fp = p.device_fp
            {clause}
            ORDER BY {order}
            LIMIT %s
            """
        try:
            cur.execute(sql_with_trust, params + [int(limit)])
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            clause_no_t = clause.replace("t.grade IN ('trusted', 'good')", "0=1")
            cur.execute(
                f"""
                SELECT p.device_fp, p.ip, p.ua_hash, p.user_agent, p.accept_language,
                       p.user_id, p.hit_count, p.first_seen, p.last_seen,
                       p.last_path, p.last_method, p.risk_score, p.notes,
                       b.ban_until, b.ban_reason, b.ban_count, b.permanent
                FROM pbt_device_prints p
                LEFT JOIN pbt_device_bans b ON b.device_fp = p.device_fp
                {clause_no_t}
                ORDER BY {order}
                LIMIT %s
                """,
                params + [int(limit)],
            )
        rows = list(cur.fetchall() or [])
        now = datetime.now()
        uids = {int(r["user_id"]) for r in rows if r.get("user_id")}
        umap = {}
        if uids:
            try:
                for u in User.query.filter(User.id.in_(list(uids))).all():
                    umap[u.id] = u
            except Exception:
                pass

        fps = [r.get("device_fp") for r in rows if r.get("device_fp")]
        ips = list({(r.get("ip") or "").strip() for r in rows if r.get("ip")})
        by_fp, by_ip = _batch_event_stats_for_devices(cur, fps, ips)
        rep_by_ip = _batch_ip_reputation(cur, ips)
        audit_by_fp = _batch_audit_counts_for_fps(fps)

        out = []
        for r in rows:
            until = r.get("ban_until")
            permanent = bool(r.get("permanent"))
            active = permanent or (until is not None and until > now)
            uid = r.get("user_id")
            user = umap.get(int(uid)) if uid else None
            ip = (r.get("ip") or "").strip()
            fp = r.get("device_fp") or ""
            est = by_fp.get(fp) or {}
            ip_est = by_ip.get(ip) or {}
            rep = rep_by_ip.get(ip) or {}
            linked = list_users_for_ip(ip, limit=6) if ip else []
            # Prefer exact device_fp event links; surface IP-level events as secondary
            event_count = int(est.get("event_count") or 0)
            event_count_ip = int(ip_est.get("event_count") or 0)
            last_type = est.get("last_event_type") or ip_est.get("last_event_type")
            last_notes = est.get("last_notes") or ip_est.get("last_notes")
            last_at = _fmt_ts(est.get("last_event_at") or ip_est.get("last_event_at"))
            if last_at == "—":
                last_at = None
            out.append(
                {
                    "device_fp": fp,
                    "ip": ip,
                    "user_agent": (r.get("user_agent") or "")[:120],
                    "user_id": uid,
                    "username": user.username if user else (f"#{uid}" if uid else "—"),
                    "role": user.role if user else "—",
                    "hit_count": int(r.get("hit_count") or 0),
                    "risk_score": int(r.get("risk_score") or 0),
                    "last_path": r.get("last_path") or "—",
                    "last_method": r.get("last_method") or "—",
                    "first_seen": _fmt_ts(r.get("first_seen")),
                    "last_seen": _fmt_ts(r.get("last_seen")),
                    "ban_until": until,
                    "ban_reason": r.get("ban_reason"),
                    "ban_count": int(r.get("ban_count") or 0),
                    "permanent": permanent,
                    "is_banned": active,
                    "is_trusted": (r.get("trust_grade") or "").lower() in ("trusted", "good"),
                    "trust_score": r.get("trust_score"),
                    "trust_grade": r.get("trust_grade") or "",
                    # Cross-links / capture context
                    "event_count": event_count,
                    "event_count_ip": event_count_ip,
                    "last_event_type": last_type,
                    "last_event_notes": last_notes,
                    "last_event_at": last_at,
                    "audit_count": int(audit_by_fp.get(fp) or 0),
                    "ip_score": rep.get("score"),
                    "ip_grade": rep.get("grade") or "—",
                    "ip_ban_until": rep.get("ban_until"),
                    "ip_ban_reason": rep.get("ban_reason"),
                    "linked_users": linked,
                    "linked_users_label": (
                        ", ".join(f"{x['username']} ({x['role']})" for x in linked[:4])
                        if linked
                        else ""
                    ),
                }
            )
        return out
    except Exception as exc:
        print(f"[security] list_device_prints: {exc}")
        return []
    finally:
        _close(conn)


def list_device_bans(limit: int = 100) -> list[dict]:
    conn = _sec()
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT device_fp, ban_until, ban_reason, ban_count, permanent,
                   created_at, updated_at
            FROM pbt_device_bans
            WHERE permanent = 1
               OR (ban_until IS NOT NULL AND ban_until > NOW())
            ORDER BY permanent DESC, ban_until DESC
            LIMIT %s
            """,
            (int(limit),),
        )
        return list(cur.fetchall() or [])
    except Exception as exc:
        print(f"[security] list_device_bans: {exc}")
        return []
    finally:
        _close(conn)


def get_device_activity_trail(device_fp: str, *, limit: int = 200) -> dict:
    """
    Full forensic trail for one device fingerprint.

    App Audit (audit_logs) only records *user/console actions*.
    Device captures live in pbt_security_events + pbt_device_prints.
    This merges all three so "click device → trail" always has real history
    when the pipeline saw the browser.
    """
    fp = (device_fp or "").strip()
    out = {
        "device_fp": fp,
        "sightings": [],
        "ban": None,
        "trust": {"is_trusted": False},
        "events": [],
        "audits": [],
        "timeline": [],
        "ips": [],
        "linked_users": [],
        "stats": {
            "sightings": 0,
            "events": 0,
            "audits": 0,
            "hits_total": 0,
        },
    }
    if not fp or len(fp) < 6:
        return out

    # --- Sightings + ban (security DB) ---
    conn = _sec()
    ips: list[str] = []
    try:
        if conn is not None:
            cur = conn.cursor()
            try:
                from poweredbytop.security.device_print import ensure_device_tables

                ensure_device_tables()
            except Exception:
                pass
            cur.execute(
                """
                SELECT device_fp, ip, user_agent, user_id, hit_count, risk_score,
                       first_seen, last_seen, last_path, last_method, notes
                FROM pbt_device_prints
                WHERE device_fp = %s
                ORDER BY last_seen DESC
                LIMIT 50
                """,
                (fp,),
            )
            out["sightings"] = list(cur.fetchall() or [])
            ips = list(
                {
                    (r.get("ip") or "").strip()
                    for r in out["sightings"]
                    if r.get("ip")
                }
            )
            out["ips"] = ips
            out["stats"]["sightings"] = len(out["sightings"])
            out["stats"]["hits_total"] = sum(
                int(r.get("hit_count") or 0) for r in out["sightings"]
            )

            cur.execute(
                """
                SELECT device_fp, ban_until, ban_reason, ban_count, permanent,
                       created_at, updated_at
                FROM pbt_device_bans
                WHERE device_fp = %s
                LIMIT 1
                """,
                (fp,),
            )
            ban = cur.fetchone()
            if ban:
                until = ban.get("ban_until")
                permanent = bool(ban.get("permanent"))
                active = permanent or (
                    until is not None and until > datetime.now()
                )
                ban = dict(ban)
                ban["is_banned"] = active
                out["ban"] = ban

            try:
                from poweredbytop.security.device_print import is_device_trusted

                out["trust"] = is_device_trusted(fp)
            except Exception:
                out["trust"] = {"is_trusted": False}

            # Security events: column match OR notes fp= recovery OR same IPs
            # Prefer exact fp first, then notes, then IP fallback (labeled)
            event_rows = []
            try:
                cur.execute(
                    """
                    SELECT id, event_type, ip, device_fp, user_id, path, method,
                           user_agent, reputation_score, behavior_grade, notes,
                           COALESCE(timestamp, created_at) AS ts
                    FROM pbt_security_events
                    WHERE device_fp = %s
                       OR notes LIKE %s
                       OR notes LIKE %s
                    ORDER BY COALESCE(timestamp, created_at) DESC, id DESC
                    LIMIT %s
                    """,
                    (fp, f"%fp={fp}%", f"%{fp[:16]}%", int(limit)),
                )
                event_rows = list(cur.fetchall() or [])
            except Exception:
                # Pre-device_fp column
                try:
                    cur.execute(
                        """
                        SELECT id, event_type, ip, notes, reputation_score, behavior_grade,
                               COALESCE(timestamp, created_at) AS ts
                        FROM pbt_security_events
                        WHERE notes LIKE %s OR notes LIKE %s
                        ORDER BY COALESCE(timestamp, created_at) DESC, id DESC
                        LIMIT %s
                        """,
                        (f"%fp={fp}%", f"%{fp[:16]}%", int(limit)),
                    )
                    event_rows = list(cur.fetchall() or [])
                except Exception as exc:
                    print(f"[security] device trail events: {exc}")

            # IP-level events if still thin (legacy rows without fp in notes)
            if len(event_rows) < 15 and ips:
                try:
                    placeholders = ",".join(["%s"] * len(ips))
                    cur.execute(
                        f"""
                        SELECT id, event_type, ip, device_fp, user_id, path, method,
                               notes, reputation_score, behavior_grade,
                               COALESCE(timestamp, created_at) AS ts
                        FROM pbt_security_events
                        WHERE ip IN ({placeholders})
                          AND (device_fp IS NULL OR device_fp = '' OR device_fp = %s)
                        ORDER BY COALESCE(timestamp, created_at) DESC, id DESC
                        LIMIT %s
                        """,
                        ips + [fp, max(20, int(limit) // 2)],
                    )
                    seen_ids = {r.get("id") for r in event_rows}
                    for row in cur.fetchall() or []:
                        if row.get("id") in seen_ids:
                            continue
                        row = dict(row)
                        row["via_ip_only"] = True
                        event_rows.append(row)
                except Exception as exc:
                    print(f"[security] device trail IP events: {exc}")

            for r in event_rows:
                d = dict(r) if not isinstance(r, dict) else dict(r)
                if not d.get("device_fp"):
                    recovered = _device_fp_from_notes(d.get("notes"))
                    if recovered:
                        d["device_fp"] = recovered
                out["events"].append(d)
            out["stats"]["events"] = len(out["events"])
    except Exception as exc:
        print(f"[security] get_device_activity_trail pbt: {exc}")
    finally:
        _close(conn)

    # --- App audits (user/console actions that mention this device) ---
    try:
        audits, _total = list_audit_logs(
            device_fp=fp,
            days=None,  # all time for a single device
            limit=int(limit),
            offset=0,
        )
        # Also catch description-only mentions (ban messages before extra_data fix)
        if len(audits) < 5:
            audits2, _ = list_audit_logs(
                search=fp[:16],
                days=None,
                limit=int(limit),
                offset=0,
            )
            seen = {a.get("id") for a in audits}
            for a in audits2:
                if a.get("id") not in seen:
                    audits.append(a)
        out["audits"] = audits
        out["stats"]["audits"] = len(audits)
    except Exception as exc:
        print(f"[security] get_device_activity_trail audits: {exc}")

    # Users linked via print user_id + IP pairs
    linked: list[dict] = []
    seen_uids: set[int] = set()
    for s in out["sightings"]:
        uid = s.get("user_id")
        if uid and int(uid) not in seen_uids:
            try:
                u = User.query.get(int(uid))
                if u:
                    linked.append(
                        {
                            "user_id": u.id,
                            "username": u.username,
                            "role": u.role,
                            "source": "device_print",
                        }
                    )
                    seen_uids.add(u.id)
            except Exception:
                pass
    for ip in ips:
        for u in list_users_for_ip(ip, limit=8):
            uid = int(u.get("user_id") or 0)
            if uid and uid not in seen_uids:
                u = dict(u)
                u["source"] = "ip_pair"
                linked.append(u)
                seen_uids.add(uid)
    out["linked_users"] = linked

    # Unified timeline (newest first)
    timeline = []
    for e in out["events"]:
        timeline.append(
            {
                "kind": "security_event",
                "ts": _fmt_ts(e.get("ts") or e.get("timestamp")),
                "title": e.get("event_type") or "event",
                "ip": e.get("ip"),
                "detail": (e.get("notes") or "")[:300],
                "path": e.get("path"),
                "via_ip_only": bool(e.get("via_ip_only")),
                "score": e.get("reputation_score"),
                "grade": e.get("behavior_grade"),
                "raw": e,
            }
        )
    for a in out["audits"]:
        timeline.append(
            {
                "kind": "app_audit",
                "ts": _fmt_ts(a.get("created_at") or a.get("timestamp")),
                "title": a.get("action") or "audit",
                "ip": a.get("ip_address") if a.get("ip_address") != "—" else None,
                "detail": (a.get("description") or "")[:300],
                "actor": a.get("actor"),
                "actor_id": a.get("actor_id"),
                "raw": a,
            }
        )
    for s in out["sightings"]:
        timeline.append(
            {
                "kind": "sighting",
                "ts": _fmt_ts(s.get("last_seen") or s.get("first_seen")),
                "title": "device_sighting",
                "ip": s.get("ip"),
                "detail": f"{s.get('last_method') or 'GET'} {s.get('last_path') or ''} · hits={s.get('hit_count')}",
                "user_id": s.get("user_id"),
                "raw": s,
            }
        )
    if out.get("ban"):
        b = out["ban"]
        timeline.append(
            {
                "kind": "device_ban",
                "ts": _fmt_ts(b.get("updated_at") or b.get("created_at") or b.get("ban_until")),
                "title": "device_ban_record",
                "ip": None,
                "detail": (
                    f"{'permanent' if b.get('permanent') else 'temp'} · "
                    f"{b.get('ban_reason') or '—'}"
                ),
                "raw": b,
            }
        )

    def _ts_key(item):
        t = item.get("ts")
        if t is None:
            return ""
        return str(t)

    timeline.sort(key=_ts_key, reverse=True)
    out["timeline"] = timeline[: int(limit)]
    return out


def investigate(
    *,
    user_id: int | None = None,
    device_fp: str = "",
    ip: str = "",
    q: str = "",
    match: str = "all",
    limit: int = 200,
) -> dict:
    """
    Combined look-up: user + device + IP.

    match=all  — only rows that satisfy every filled field
                 (did this user, on this browser, from this IP, trigger Y?)
    match=any  — rows that match at least one filled field
    q          — event type / notes / path search (“did they do Y”)
    """
    fp = (device_fp or "").strip()
    ip = (ip or "").strip()
    q = (q or "").strip()
    match = "any" if (match or "").strip().lower() == "any" else "all"
    try:
        uid = int(user_id) if user_id else None
    except (TypeError, ValueError):
        uid = None

    user = None
    if uid:
        try:
            u = User.query.get(uid)
            if u:
                user = {
                    "id": u.id,
                    "username": u.username,
                    "role": u.role or "",
                    "email": u.email or "",
                    "is_active": bool(u.is_active),
                }
        except Exception:
            user = {"id": uid, "username": f"#{uid}", "role": "", "email": "", "is_active": None}

    trust = {"is_trusted": False}
    if fp:
        try:
            from poweredbytop.security.device_print import is_device_trusted

            trust = is_device_trusted(fp)
        except Exception:
            pass

    ip_rep = {}
    if ip:
        conn = _sec()
        if conn is not None:
            try:
                ip_rep = _batch_ip_reputation(conn.cursor(), [ip]).get(ip) or {}
            except Exception:
                ip_rep = {}
            finally:
                _close(conn)

    devices = []
    if uid:
        devices = list_devices_for_user(uid, limit=20)
    elif fp:
        devices = list_device_prints(search=fp, limit=20)

    ips_for_user = list_ips_for_user(uid, limit=20) if uid else []
    users_for_ip = list_users_for_ip(ip, limit=20) if ip else []

    events: list[dict] = []
    event_total = 0
    if match == "all":
        events, event_total = list_security_events(
            search=q,
            ip=ip,
            device_fp=fp,
            user_id=uid,
            include_sightings_fallback=bool(fp or ip) and not uid and not q,
            limit=limit,
            offset=0,
        )
    else:
        seen_ids: set = set()
        buckets = []
        if uid:
            buckets.append(list_security_events(user_id=uid, search=q, include_sightings_fallback=False, limit=limit, offset=0))
        if fp:
            buckets.append(list_security_events(device_fp=fp, search=q, include_sightings_fallback=True, limit=limit, offset=0))
        if ip:
            buckets.append(list_security_events(ip=ip, search=q, include_sightings_fallback=True, limit=limit, offset=0))
        if q and not (uid or fp or ip):
            buckets.append(list_security_events(search=q, include_sightings_fallback=False, limit=limit, offset=0))
        for rows, total in buckets:
            event_total += int(total or 0)
            for row in rows:
                rid = row.get("id")
                key = rid if rid is not None else (row.get("timestamp"), row.get("event_type"), row.get("ip"))
                if key in seen_ids:
                    continue
                seen_ids.add(key)
                events.append(row)
        events.sort(key=lambda r: str(r.get("timestamp") or ""), reverse=True)
        events = events[:limit]

    audits: list[dict] = []
    audit_total = 0
    if uid or fp or ip:
        try:
            audits, audit_total = list_audit_logs(
                user_id=uid,
                device_fp=fp,
                ip=ip,
                search=q,
                days=None,
                limit=min(40, limit),
                offset=0,
            )
        except Exception as exc:
            print(f"[security] investigate audits: {exc}")

    return {
        "user": user,
        "user_id": uid,
        "device_fp": fp,
        "ip": ip,
        "q": q,
        "match": match,
        "trust": trust,
        "ip_rep": ip_rep,
        "devices": devices,
        "ips_for_user": ips_for_user,
        "users_for_ip": users_for_ip,
        "events": events,
        "event_total": event_total,
        "audits": audits,
        "audit_total": audit_total,
        "has_filters": bool(uid or fp or ip or q),
    }

