from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.builddb.builddb import db, evolve_table

ROLES = ("admin", "member", "child")


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    username = db.Column(db.String(80), nullable=False)
    name = db.Column(db.String(150), nullable=False, default="")
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="member")
    permissions_json = db.Column(db.JSON, nullable=True)
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    account_locked_until = db.Column(db.DateTime, nullable=True)
    last_login_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_leader = db.Column(db.Boolean, default=False, nullable=False)
    notify_via = db.Column(db.String(16), nullable=False, default="both")
    calendar_token = db.Column(db.String(64), unique=True, nullable=True)
    calendar_email = db.Column(db.String(120), nullable=True)
    calendar_provider = db.Column(db.String(16), nullable=True)
    calendar_mode = db.Column(db.String(16), nullable=False, default="auto")
    extra_data = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    household = db.relationship("Household", back_populates="users")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_full_name(self):
        return self.name or self.username

    @property
    def is_admin(self):
        return (self.role or "").strip().lower() == "admin"

    @property
    def is_member(self):
        return (self.role or "").strip().lower() == "member"

    @property
    def is_child(self):
        return (self.role or "").strip().lower() == "child"


def create_table():
    evolve_table(
        "users",
        [
            ("household_id", "INT NOT NULL"),
            ("name", "VARCHAR(150) NOT NULL DEFAULT ''"),
            ("email", "VARCHAR(120) NULL"),
            ("role", "VARCHAR(20) NOT NULL DEFAULT 'member'"),
            ("permissions_json", "JSON NULL"),
            ("failed_login_attempts", "INT NOT NULL DEFAULT 0"),
            ("account_locked_until", "TIMESTAMP NULL DEFAULT NULL"),
            ("last_login_at", "TIMESTAMP NULL DEFAULT NULL"),
            ("is_active", "TINYINT(1) NOT NULL DEFAULT 1"),
            ("is_leader", "TINYINT(1) NOT NULL DEFAULT 0"),
            ("notify_via", "VARCHAR(16) NOT NULL DEFAULT 'both'"),
            ("calendar_token", "VARCHAR(64) NULL"),
            ("calendar_email", "VARCHAR(120) NULL"),
            ("calendar_provider", "VARCHAR(16) NULL"),
            ("calendar_mode", "VARCHAR(16) NOT NULL DEFAULT 'auto'"),
            ("extra_data", "JSON NULL"),
        ],
        indexes=[
            ("idx_users_household_id", "household_id"),
            ("idx_users_role", "role"),
            ("idx_users_household_leader", "household_id, is_leader"),
            ("idx_users_calendar_token", "calendar_token"),
        ],
    )
    _scope_usernames()
    _backfill_leaders()


def _scope_usernames():
    """Usernames are unique inside a household, not across Family OS."""
    from sqlalchemy import inspect, text

    try:
        inspector = inspect(db.engine)
        if "users" not in inspector.get_table_names():
            return
        with db.engine.begin() as conn:
            for idx in inspector.get_indexes("users"):
                cols = idx.get("column_names") or []
                if idx.get("unique") and cols == ["username"]:
                    try:
                        conn.execute(text(f"ALTER TABLE users DROP INDEX `{idx['name']}`"))
                        print(f"[BUILD-DB] dropped global unique {idx['name']} on users.username")
                    except Exception as drop_e:
                        print(f"[BUILD-DB] drop username unique: {drop_e}")
            for uq in inspector.get_unique_constraints("users"):
                cols = uq.get("column_names") or []
                if cols == ["username"]:
                    try:
                        conn.execute(text(f"ALTER TABLE users DROP INDEX `{uq['name']}`"))
                    except Exception:
                        pass
            try:
                conn.execute(text("ALTER TABLE users DROP INDEX `idx_users_household_username`"))
            except Exception:
                pass
            try:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX idx_users_household_username "
                        "ON users (household_id, username)"
                    )
                )
                print("[BUILD-DB] unique usernames per household")
            except Exception as idx_e:
                print(f"[BUILD-DB] household username unique: {idx_e}")
    except Exception as exc:
        print(f"[BUILD-DB] scope usernames: {exc}")


def _backfill_leaders():
    """Existing households get their oldest admin (else oldest member) as leader."""
    from sqlalchemy import text

    try:
        with db.engine.begin() as conn:
            houses = conn.execute(
                text(
                    """
                    SELECT h.id
                    FROM households h
                    WHERE NOT EXISTS (
                        SELECT 1 FROM users u
                        WHERE u.household_id = h.id AND u.is_leader = 1
                    )
                    """
                )
            ).fetchall()
            for row in houses:
                hid = row[0]
                picked = conn.execute(
                    text(
                        """
                        SELECT id FROM users
                        WHERE household_id = :hid AND is_active = 1
                        ORDER BY CASE WHEN role = 'admin' THEN 0 WHEN role = 'member' THEN 1 ELSE 2 END, id ASC
                        LIMIT 1
                        """
                    ),
                    {"hid": hid},
                ).fetchone()
                if picked:
                    conn.execute(
                        text("UPDATE users SET is_leader = 1 WHERE id = :uid"),
                        {"uid": picked[0]},
                    )
    except Exception as exc:
        print(f"[BUILD-DB] leader backfill: {exc}")
