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
    username = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False, default="")
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="member")
    permissions_json = db.Column(db.JSON, nullable=True)
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    account_locked_until = db.Column(db.DateTime, nullable=True)
    last_login_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
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
            ("extra_data", "JSON NULL"),
        ],
        indexes=[
            ("idx_users_household_id", "household_id"),
            ("idx_users_role", "role"),
        ],
    )
