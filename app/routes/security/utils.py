"""Access + ban helpers for the Family OS owner security console."""
from __future__ import annotations

from datetime import datetime, timedelta

from flask import session

from app.builddb.builddb import db
from app.builddb.table_users import User


def ensure_security_grants_table() -> None:
    return None


def can_access_security_console(user=None) -> bool:
    from app.utils.platform_auth import is_owner

    return is_owner()


def can_manage_security_access(user=None) -> bool:
    return can_access_security_console()


def csrf_token() -> str:
    try:
        from poweredbytop.security.csrf import generate_csrf_token

        return generate_csrf_token() or ""
    except Exception:
        return session.get("csrf_token") or ""


def csrf_ok() -> bool:
    try:
        from poweredbytop.security.csrf import validate_csrf_token

        return bool(validate_csrf_token())
    except Exception:
        from flask import request

        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
        return bool(sent) and sent == csrf_token()


def clear_account_login_lock(user_id: int, actor_id: int | None = None) -> bool:
    user = User.query.get(user_id)
    if not user:
        return False
    user.failed_login_attempts = 0
    user.account_locked_until = None
    db.session.commit()
    try:
        from app.utils.platform_settings import audit

        audit("security.unlock", owner_id=actor_id, detail={"user_id": int(user.id)})
    except Exception:
        pass
    return True


def _sec_db():
    try:
        from poweredbytop.models.connect_db import get_security_db

        return get_security_db()
    except Exception:
        return None


def _close_sec(conn) -> None:
    try:
        from poweredbytop.models.connect_db import close_security_db

        close_security_db(conn)
    except Exception:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def ban_ip_console(ip: str, reason: str, *, permanent: bool = False, hours: int = 1) -> bool:
    ip = (ip or "").strip()
    if not ip:
        return False
    reason = (reason or "Manual ban from Security console").strip()[:500]
    hours = max(1, min(int(hours or 1), 168))
    conn = _sec_db()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO pbt_reputation (ip, score, grade, positive_requests, negative_points, ban_count, first_seen, last_seen)
            VALUES (%s, 0, 'suspicious', 0, 0, 0, NOW(), NOW())
            ON DUPLICATE KEY UPDATE last_seen = NOW()
            """,
            (ip,),
        )
        if permanent:
            cur.execute(
                """
                UPDATE pbt_reputation
                SET grade='perm_ban', ban_until=NULL, ban_reason=%s,
                    ban_count=ban_count+1, score=0, last_seen=NOW()
                WHERE ip=%s
                """,
                (reason, ip),
            )
        else:
            until = datetime.now() + timedelta(hours=hours)
            cur.execute(
                """
                UPDATE pbt_reputation
                SET grade='temp_ban', ban_until=%s, ban_reason=%s,
                    ban_count=ban_count+1, score=LEAST(score, 20), last_seen=NOW()
                WHERE ip=%s
                """,
                (until, reason, ip),
            )
        conn.commit()
        return True
    except Exception as exc:
        print(f"[security] ban_ip_console: {exc}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        _close_sec(conn)


def unban_ip_console(ip: str, restore_score: int = 100) -> bool:
    ip = (ip or "").strip()
    if not ip:
        return False
    conn = _sec_db()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE pbt_reputation
            SET grade='normal', ban_until=NULL, ban_reason=NULL,
                score=GREATEST(COALESCE(score,0), %s), last_seen=NOW()
            WHERE ip=%s
            """,
            (int(restore_score), ip),
        )
        conn.commit()
        return True
    except Exception as exc:
        print(f"[security] unban_ip_console: {exc}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        _close_sec(conn)


def trust_ip_console(ip: str, score: int = 250) -> bool:
    ip = (ip or "").strip()
    if not ip:
        return False
    conn = _sec_db()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO pbt_reputation (ip, score, grade, positive_requests, negative_points, first_seen, last_seen)
            VALUES (%s, %s, 'trusted', 0, 0, NOW(), NOW())
            ON DUPLICATE KEY UPDATE score=%s, grade='trusted', ban_until=NULL, ban_reason=NULL, last_seen=NOW()
            """,
            (ip, int(score), int(score)),
        )
        conn.commit()
        return True
    except Exception as exc:
        print(f"[security] trust_ip_console: {exc}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        _close_sec(conn)


def ban_device_console(device_fp: str, reason: str, *, hours: int = 6, permanent: bool = False) -> bool:
    fp = (device_fp or "").strip()
    if not fp or len(fp) < 8:
        return False
    try:
        from poweredbytop.security.device_print import ban_device, ensure_device_tables

        ensure_device_tables()
        ban_device(
            fp,
            reason or "Manual device ban from Security console",
            hours=max(1, min(int(hours or 6), 168)),
            permanent=bool(permanent),
        )
        return True
    except Exception as exc:
        print(f"[security] ban_device_console: {exc}")
        return False


def unban_device_console(device_fp: str) -> bool:
    fp = (device_fp or "").strip()
    if not fp:
        return False
    try:
        from poweredbytop.security.device_print import unban_device, ensure_device_tables

        ensure_device_tables()
        return bool(unban_device(fp))
    except Exception as exc:
        print(f"[security] unban_device_console: {exc}")
        return False


def trust_device_console(device_fp: str, *, score: int = 250, notes: str | None = None, trusted_by: int | None = None) -> bool:
    fp = (device_fp or "").strip()
    if not fp or len(fp) < 8:
        return False
    try:
        from poweredbytop.security.device_print import trust_device, ensure_device_tables

        ensure_device_tables()
        return bool(trust_device(fp, score=score, notes=notes, trusted_by=trusted_by))
    except Exception as exc:
        print(f"[security] trust_device_console: {exc}")
        return False


def untrust_device_console(device_fp: str) -> bool:
    fp = (device_fp or "").strip()
    if not fp:
        return False
    try:
        from poweredbytop.security.device_print import untrust_device, ensure_device_tables

        ensure_device_tables()
        return bool(untrust_device(fp))
    except Exception as exc:
        print(f"[security] untrust_device_console: {exc}")
        return False
