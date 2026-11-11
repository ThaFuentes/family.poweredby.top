# poweredbytop/models/connect_db.py
# Full path: poweredbytop/models/connect_db.py
# File name: connect_db.py
# Brief detailed purpose: Security DB layer - STRICTLY uses root dbconnector.py. Handles cPanel socket issues and background threads. Graceful fallback so security features still run. FULL REBUILD with UTF8MB4 forced everywhere, cleaner import from root dbconnector, safer ensure_table_exists, and background-thread safety.
"""
SECURITY DB CONNECTOR
- Never raises unhandled exceptions
- Works with .env MYSQL_* variables via root dbconnector.py
- Handles cPanel socket issues and background threads
- Graceful fallback so security features still run
- UTF8MB4 FORCED + pool_recycle alignment with root dbconnector
"""
import os
import threading
import time
import sys
from poweredbytop.utils.helpers import logger

# ====================== IMPORT ROOT DBCONNECTOR (CLEAN & SAFE) ======================
DATABASE_URI = None
MYSQL_HOST = "127.0.0.1"
MYSQL_PORT = "3306"
MYSQL_DATABASE = None
try:
    # Direct import from the root dbconnector we just rebuilt
    from dbconnector import DATABASE_URI, MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE
    logger("connect_db.py -> Successfully imported root dbconnector.py")
except ImportError:
    # Emergency fallback (only if import fails)
    fallback_path = "/home/ua882038/public_html/family.poweredby.top/dbconnector.py"
    if os.path.exists(fallback_path):
        import importlib.util
        spec = importlib.util.spec_from_file_location("dbconnector", fallback_path)
        dbconnector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dbconnector)
        DATABASE_URI = getattr(dbconnector, "DATABASE_URI", None)
        MYSQL_HOST = getattr(dbconnector, "MYSQL_HOST", "127.0.0.1")
        MYSQL_PORT = getattr(dbconnector, "MYSQL_PORT", "3306")
        MYSQL_DATABASE = getattr(dbconnector, "MYSQL_DATABASE", None)
        logger("connect_db.py -> Used fallback import for dbconnector")
    else:
        logger("WARNING: dbconnector.py not found at expected path")

# ====================== CONNECTION FUNCTION ======================
# One household page opens several of these (device, ban, reputation, traffic).
# Cloudflare closes the origin around 100s and shows 522. The old budget was
# 4 tries at 15s connect + 35s read, per call. Callers already treat None as
# "skip the log and continue", so a live request must give up quickly.
_db_local = threading.local()
REQUEST_DB_BUDGET_SECONDS = 8
REQUEST_DB_CONNECT_CAP = 3
REQUEST_DB_IO_CAP = 4


class _HeldConnection:
    """One security connection for this request.

    Callers close what they think is their own connection. Closing the real
    socket there made the next check open another one, and a full MariaDB
    made each of those waits stack until Cloudflare returned 522. close()
    waits. The request teardown closes the socket.
    """

    def __init__(self, raw):
        self._raw = raw
        self._released = False

    def close(self):
        # Callers close after they commit. Roll back anything they left
        # open so the next check on this same socket does not commit it.
        try:
            self._raw.rollback()
        except Exception:
            pass

    def release(self):
        if self._released:
            return
        self._released = True
        try:
            self._raw.close()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._raw, name)


def _release_shared_security_db():
    shared = getattr(_db_local, "shared", None)
    _db_local.shared = None
    if shared is not None and hasattr(shared, "release"):
        shared.release()


def begin_request_db_budget(seconds=None):
    """Start the per-request cap. The next request on this thread replaces it."""
    _release_shared_security_db()
    if seconds is None:
        seconds = REQUEST_DB_BUDGET_SECONDS
    _db_local.deadline = time.monotonic() + float(seconds)


def end_request_db_budget():
    _release_shared_security_db()
    _db_local.deadline = None


def request_db_seconds_left():
    """Seconds left on this request, or None when no request budget is armed."""
    deadline = getattr(_db_local, "deadline", None)
    if deadline is None:
        return None
    return deadline - time.monotonic()


def security_db_attempt_plan(remaining):
    """
    How get_security_db will try.
    None means do not connect. A missing remaining is the background path and
    keeps the old 4 x (15s connect, 35s read) tries. A request gets one try
    whose socket timeouts fit inside the time still left.
    """
    if remaining is None:
        return {
            "attempts": 4,
            "connect_timeout": 15,
            "read_timeout": 35,
            "write_timeout": 35,
        }
    if remaining < 1:
        return None
    whole = int(remaining)
    connect_timeout = min(REQUEST_DB_CONNECT_CAP, max(1, whole))
    if connect_timeout >= whole and whole >= 2:
        connect_timeout = whole - 1
    io_timeout = min(REQUEST_DB_IO_CAP, max(1, whole - connect_timeout))
    return {
        "attempts": 1,
        "connect_timeout": connect_timeout,
        "read_timeout": io_timeout,
        "write_timeout": io_timeout,
    }


def _parse_security_uri(uri):
    """Split the root DATABASE_URI. Same rules as the previous connector."""
    bare = uri.replace("mysql+pymysql://", "")
    auth_part, host_part = bare.split("@", 1)
    user, password = auth_part.split(":", 1)
    host_db_part = host_part.split("?", 1)[0]
    if ":" in host_db_part and "/" in host_db_part:
        host_port, db_name = host_db_part.split("/", 1)
        host, port_str = host_port.split(":", 1)
        port = int(port_str)
    else:
        host_db_split = host_db_part.split("/", 1)
        host = host_db_split[0]
        db_name = host_db_split[1] if len(host_db_split) > 1 else (MYSQL_DATABASE or "ua882038_family")
        port = int(MYSQL_PORT)
    return {"user": user, "password": password, "host": host, "port": port, "database": db_name}


def get_security_db():
    """Return pymysql connection using ONLY the root DATABASE_URI. Safe for background threads."""
    shared = getattr(_db_local, "shared", None)
    if shared is not None:
        try:
            shared.ping(reconnect=False)
            return shared
        except Exception:
            logger("[DB] request security connection went stale - opening another")
            _release_shared_security_db()
    plan = security_db_attempt_plan(request_db_seconds_left())
    if plan is None:
        logger("[DB] request budget spent - security connection skipped")
        return None
    if not DATABASE_URI:
        logger("[DB] No DATABASE_URI available - security logging disabled")
        return None
    import pymysql
    try:
        parsed = _parse_security_uri(DATABASE_URI)
    except Exception as e:
        logger("[DB ERROR] bad DATABASE_URI: " + str(e))
        return None
    attempts = plan["attempts"]
    db = None
    for attempt in range(attempts):
        plan = security_db_attempt_plan(request_db_seconds_left())
        if plan is None:
            logger("[DB] request budget spent - security connection skipped")
            return None
        try:
            # Connection parameters - UTF8MB4 + cPanel ready (aligned with hardened root dbconnector)
            connect_params = {
                "user": parsed["user"],
                "password": parsed["password"],
                "database": parsed["database"],
                "charset": "utf8mb4",
                "cursorclass": pymysql.cursors.DictCursor,
                "connect_timeout": plan["connect_timeout"],
                "read_timeout": plan["read_timeout"],
                "write_timeout": plan["write_timeout"],
            }
            host = parsed["host"]
            port = parsed["port"]
            # cPanel unix socket optimization
            if host in ("127.0.0.1", "localhost"):
                socket_path = "/var/lib/mysql/mysql.sock"
                if os.path.exists(socket_path):
                    connect_params["unix_socket"] = socket_path
                    logger("[DB] Using cPanel unix socket")
                else:
                    connect_params["host"] = host
                    connect_params["port"] = port
            else:
                connect_params["host"] = host
                connect_params["port"] = port
            db = pymysql.connect(**connect_params)
            # Health check
            with db.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            try:
                db.rollback()
            except Exception:
                pass
            logger("[DB] Secure connection established")
            # Background threads keep a private connection and close it
            # themselves. A live request reuses this one until teardown.
            if request_db_seconds_left() is not None:
                held = _HeldConnection(db)
                _db_local.shared = held
                return held
            return db
        except Exception as e:
            if db:
                try:
                    db.close()
                except Exception:
                    pass
                db = None
            if attempt == attempts - 1:
                logger("[DB ERROR] security connection failed (" + str(attempts) + " tries): " + str(e))
                return None
            backoff = 0.4 * (attempt + 1)
            left = request_db_seconds_left()
            if left is not None:
                if left < 1:
                    logger("[DB] request budget spent - security connection skipped")
                    return None
                backoff = min(backoff, left)
            time.sleep(backoff)
            logger("[DB] Retry " + str(attempt + 1) + "/" + str(attempts))
    return None

def close_security_db(db_connection=None):
    """Safely close a private connection. The request connection stays until teardown."""
    if db_connection is None:
        return
    if db_connection is getattr(_db_local, "shared", None):
        return
    if hasattr(db_connection, "close"):
        try:
            db_connection.close()
        except Exception:
            pass

def ensure_table_exists(table_name: str, create_sql: str):
    """Create table if missing - silent on failure + UTF8MB4 forced"""
    db = get_security_db()
    if not db:
        return False
    try:
        with db.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE %s", (table_name,))
            if not cursor.fetchone():
                # Force UTF8MB4 on every table creation
                full_sql = f"CREATE TABLE IF NOT EXISTS `{table_name}` ({create_sql}) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
                cursor.execute(full_sql)
                db.commit()
                logger("[DB] Table created: " + table_name + " (UTF8MB4 enforced)")
                return True
            else:
                logger("[DB] Table already exists: " + table_name)
                return True
    except Exception as e:
        logger("[DB] ensure_table_exists failed for " + table_name + ": " + str(e))
        return False
    finally:
        close_security_db(db)

def get_sqlalchemy_config():
    """Return config that matches the hardened root dbconnector.py (recycle=120 + reset_on_return)"""
    if not DATABASE_URI:
        return {}
    return {
        "SQLALCHEMY_DATABASE_URI": DATABASE_URI,
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SQLALCHEMY_ENGINE_OPTIONS": {
            "pool_pre_ping": True,
            "pool_recycle": 120,
            "pool_size": 3,
            "max_overflow": 30,
            "pool_timeout": 45,
            "pool_reset_on_return": "commit",
        }
    }

logger("poweredbytop/models/connect_db.py - FULL REBUILD COMPLETE (UTF8MB4 forced + clean root dbconnector import + background safe + aligned pool settings)")