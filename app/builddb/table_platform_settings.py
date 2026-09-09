from app.builddb.builddb import db, evolve_table


class PlatformSetting(db.Model):
    """Owner-console config. Secret values are encrypted in app.utils.platform_settings."""

    __tablename__ = "platform_settings"

    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text, nullable=True)
    is_secret = db.Column(db.Boolean, default=False, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )


def create_table():
    evolve_table(
        "platform_settings",
        [
            ("value", "TEXT NULL"),
            ("is_secret", "TINYINT(1) NOT NULL DEFAULT 0"),
            ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ],
    )
