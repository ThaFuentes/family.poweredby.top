# ===========================================================
# File: app/builddb/builddb.py
# Household OS schema init. CREATE IF NOT EXISTS on boot only —
# never DDL on every request beyond the one-time evolve pass.
# ===========================================================
import os
import importlib
import pkgutil
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, inspect

db = SQLAlchemy()


def evolve_table(table_name, columns, indexes=None):
    """Add missing columns / indexes. Never drops data."""
    inspector = inspect(db.engine)
    if table_name not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns(table_name)}
    with db.engine.begin() as conn:
        for col_name, col_type in columns:
            if col_name not in existing:
                conn.execute(text(f"ALTER TABLE `{table_name}` ADD COLUMN `{col_name}` {col_type}"))
                print(f"[BUILD-DB] added {table_name}.{col_name}")
        if indexes:
            have = {i["name"] for i in inspector.get_indexes(table_name)}
            for idx_name, idx_cols in indexes:
                if idx_name not in have:
                    try:
                        conn.execute(text(f"CREATE INDEX `{idx_name}` ON `{table_name}` ({idx_cols})"))
                        print(f"[BUILD-DB] added index {idx_name}")
                    except Exception as idx_e:
                        print(f"[BUILD-DB] index {idx_name}: {idx_e}")


def init_tenant_system(app):
    db.init_app(app)
    with app.app_context():
        package_name = __name__.rsplit(".", 1)[0]
        package_path = os.path.dirname(__file__)
        for _, module_name, _ in pkgutil.iter_modules([package_path]):
            if module_name in ("builddb",):
                continue
            importlib.import_module(f"{package_name}.{module_name}")

        with db.engine.connect() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))

        ordered_modules = [
            "table_households",
            "table_users",
            "table_items",
            "table_grocery_items",
            "table_tools",
            "table_vehicles",
            "table_maintenance_records",
            "table_reminders",
            "table_photo_notes",
            "table_scan_events",
            "table_grocery_list",
            "table_invites",
        ]
        db.create_all()
        for module_name in ordered_modules:
            try:
                module = importlib.import_module(f"{package_name}.{module_name}")
                if hasattr(module, "create_table"):
                    module.create_table()
            except Exception as _build_exc:
                try:
                    print(f"[BUILD-DB] {module_name} create failed: {_build_exc}")
                except Exception:
                    pass

        with db.engine.connect() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

        try:
            with db.engine.connect() as conn:
                row = conn.execute(text("SELECT VERSION() AS version")).fetchone()
                print(f"[FAMILY DB] MariaDB connected  {row.version}")
        except Exception as e:
            print(f"[FAMILY DB ERROR] ping failed: {e}")

        print("YES DB CREATED - Family household tables ready")
