# ===========================================================
# File: app/builddb/builddb.py
# Household OS schema init. CREATE IF NOT EXISTS on boot only —
# never DDL on every request beyond the one-time evolve pass.
# After a matching schema fingerprint, skip inspector evolve on
# later Passenger worker spawns (cold start used to re-ALTER
# every table on every idle recycle).
# ===========================================================
import os
import sys
import hashlib
import importlib
import pkgutil
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, inspect

db = SQLAlchemy()

SCHEMA_STAMP_NAME = "schema.fingerprint"


def _say(msg):
    """HostM Passenger stdout is often ASCII. Never encode('ascii')."""
    text = str(msg)
    try:
        print(text, flush=True)
        return
    except UnicodeEncodeError:
        pass
    try:
        buf = getattr(sys.stdout, "buffer", None)
        if buf is not None:
            buf.write((text + "\n").encode("utf-8"))
            buf.flush()
    except Exception:
        pass


def evolve_table(table_name, columns, indexes=None):
    """Add missing columns / indexes. Never drops data.

    One statement per connection: MariaDB DDL auto-commits, and a
    HostM timeout on CREATE INDEX used to kill the pipe so later
    ADD COLUMN never ran (then we stamped 'current' anyway).
    """
    inspector = inspect(db.engine)
    if table_name not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns(table_name)}
    for col_name, col_type in columns:
        if col_name in existing:
            continue
        try:
            with db.engine.begin() as conn:
                conn.execute(
                    text(f"ALTER TABLE `{table_name}` ADD COLUMN `{col_name}` {col_type}")
                )
            existing.add(col_name)
            _say(f"[BUILD-DB] added {table_name}.{col_name}")
        except Exception as col_e:
            _say(f"[BUILD-DB] add {table_name}.{col_name}: {col_e}")
    if not indexes:
        return
    try:
        have = {i["name"] for i in inspect(db.engine).get_indexes(table_name)}
    except Exception:
        have = set()
    for idx_name, idx_cols in indexes:
        if idx_name in have:
            continue
        try:
            with db.engine.begin() as conn:
                conn.execute(
                    text(f"CREATE INDEX `{idx_name}` ON `{table_name}` ({idx_cols})")
                )
            _say(f"[BUILD-DB] added index {idx_name}")
        except Exception as idx_e:
            _say(f"[BUILD-DB] index {idx_name}: {idx_e}")


def schema_fingerprint(package_path=None) -> str:
    """Hash of table_*.py + this file. Any schema edit invalidates the stamp."""
    root = package_path or os.path.dirname(__file__)
    h = hashlib.sha256()
    names = ["builddb.py"] + sorted(
        n for n in os.listdir(root) if n.startswith("table_") and n.endswith(".py")
    )
    for name in names:
        path = os.path.join(root, name)
        try:
            with open(path, "rb") as fh:
                h.update(name.encode("utf-8"))
                h.update(b"\0")
                h.update(fh.read())
                h.update(b"\0")
        except OSError:
            h.update(name.encode("utf-8"))
            h.update(b"missing\0")
    return h.hexdigest()[:24]


def _stamp_path(app) -> str:
    return os.path.join(app.instance_path, SCHEMA_STAMP_NAME)


def _schema_is_current(app) -> bool:
    path = _stamp_path(app)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip() == schema_fingerprint()
    except Exception:
        return False


def _users_schema_ready() -> bool:
    """Stamp can lie if evolve died mid-ALTER. Login selects these columns."""
    try:
        cols = {c["name"] for c in inspect(db.engine).get_columns("users")}
    except Exception:
        return False
    return {"calendar_email", "calendar_provider", "calendar_mode"} <= cols


def _write_schema_stamp(app) -> None:
    path = _stamp_path(app)
    try:
        os.makedirs(app.instance_path, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(schema_fingerprint())
    except Exception as exc:
        _say(f"[BUILD-DB] could not write schema stamp: {exc}")


def init_tenant_system(app):
    db.init_app(app)
    with app.app_context():
        package_name = __name__.rsplit(".", 1)[0]
        package_path = os.path.dirname(__file__)
        for _, module_name, _ in pkgutil.iter_modules([package_path]):
            if module_name in ("builddb",):
                continue
            importlib.import_module(f"{package_name}.{module_name}")

        skip_evolve = _schema_is_current(app)
        if skip_evolve and not _users_schema_ready():
            _say("[BUILD-DB] stamp said current but users columns missing - evolve")
            skip_evolve = False
        if skip_evolve:
            _say("[BUILD-DB] schema current - skip evolve")
        else:
            db.create_all()
            with db.engine.connect() as conn:
                conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))

            ordered_modules = [
                "table_households",
                "table_users",
                "table_items",
                "table_grocery_items",
                "table_tools",
                "table_vehicles",
                "table_vehicle_parts",
                "table_maintenance_records",
                "table_reminders",
                "table_photo_notes",
                "table_notes",
                "table_legal_records",
                "table_legal_files",
                "table_scan_events",
                "table_household_activity",
                "table_grocery_list",
                "table_invites",
                "table_service_passes",
                "table_trusted_emails",
                "table_password_resets",
                "table_platform_owners",
                "table_platform_invites",
                "table_platform_settings",
                "table_platform_audit",
            ]
            evolve_ok = True
            for module_name in ordered_modules:
                try:
                    module = importlib.import_module(f"{package_name}.{module_name}")
                    if hasattr(module, "create_table"):
                        module.create_table()
                except Exception as _build_exc:
                    evolve_ok = False
                    try:
                        _say(f"[BUILD-DB] {module_name} create failed: {_build_exc}")
                    except Exception:
                        pass

            with db.engine.connect() as conn:
                conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
            if evolve_ok and _users_schema_ready():
                _write_schema_stamp(app)
            else:
                _say("[BUILD-DB] evolve incomplete - will retry next boot")

        try:
            from app.utils.hot_cache import register_session_hooks

            register_session_hooks(db)
        except Exception as hook_exc:
            _say(f"[BUILD-DB] cache hooks: {hook_exc}")

        try:
            with db.engine.connect() as conn:
                row = conn.execute(text("SELECT VERSION() AS version")).fetchone()
                _say(f"[FAMILY DB] MariaDB connected  {row.version}")
        except Exception as e:
            _say(f"[FAMILY DB ERROR] ping failed: {e}")

        _say("YES DB CREATED - Family household tables ready")
