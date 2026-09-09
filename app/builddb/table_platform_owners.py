from werkzeug.security import generate_password_hash, check_password_hash

from app.builddb.builddb import db, evolve_table


class PlatformOwner(db.Model):
    """You. Not a household user. Never mixed with tenant accounts."""

    __tablename__ = "platform_owners"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False, default="")
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    account_locked_until = db.Column(db.DateTime, nullable=True)
    last_login_at = db.Column(db.DateTime, nullable=True)
    extra_data = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


def create_table():
    evolve_table(
        "platform_owners",
        [
            ("username", "VARCHAR(80) NOT NULL"),
            ("name", "VARCHAR(150) NOT NULL DEFAULT ''"),
            ("email", "VARCHAR(120) NOT NULL"),
            ("password_hash", "VARCHAR(256) NOT NULL"),
            ("is_active", "TINYINT(1) NOT NULL DEFAULT 1"),
            ("failed_login_attempts", "INT NOT NULL DEFAULT 0"),
            ("account_locked_until", "TIMESTAMP NULL DEFAULT NULL"),
            ("last_login_at", "TIMESTAMP NULL DEFAULT NULL"),
            ("extra_data", "JSON NULL"),
        ],
        indexes=[
            ("idx_platform_owners_username", "username"),
            ("idx_platform_owners_email", "email"),
        ],
    )
