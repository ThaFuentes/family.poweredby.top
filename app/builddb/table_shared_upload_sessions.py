"""An in-flight resumable share upload. Deleted when finished or abandoned."""
from app.builddb.builddb import db, evolve_table


class ShareUploadSession(db.Model):
    """Encrypted bytes already received for one upload, plus its share settings."""

    __tablename__ = "share_upload_sessions"

    id = db.Column(db.String(64), primary_key=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    created_by = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    original_name = db.Column(db.String(200), nullable=False)
    ext = db.Column(db.String(16), nullable=False)
    title = db.Column(db.String(200), nullable=False, default="")
    mime = db.Column(db.String(80), nullable=True)
    share_mode = db.Column(db.String(20), nullable=False, default="family")
    password_hash = db.Column(db.String(256), nullable=True)
    expiry_days = db.Column(db.Integer, nullable=False, default=0)
    people_json = db.Column(db.Text, nullable=True)
    size_bytes = db.Column(db.BigInteger, nullable=False)
    received_bytes = db.Column(db.BigInteger, nullable=False, default=0)
    stored_path = db.Column(db.String(400), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False)


def create_table():
    evolve_table(
        "share_upload_sessions",
        [
            ("id", "VARCHAR(64) NOT NULL"),
            ("household_id", "INT NOT NULL"),
            ("created_by", "INT NOT NULL"),
            ("original_name", "VARCHAR(200) NOT NULL"),
            ("ext", "VARCHAR(16) NOT NULL"),
            ("title", "VARCHAR(200) NOT NULL DEFAULT ''"),
            ("mime", "VARCHAR(80) NULL"),
            ("share_mode", "VARCHAR(20) NOT NULL DEFAULT 'family'"),
            ("password_hash", "VARCHAR(256) NULL"),
            ("expiry_days", "INT NOT NULL DEFAULT 0"),
            ("people_json", "TEXT NULL"),
            ("size_bytes", "BIGINT NOT NULL"),
            ("received_bytes", "BIGINT NOT NULL DEFAULT 0"),
            ("stored_path", "VARCHAR(400) NOT NULL"),
            ("created_at", "TIMESTAMP NOT NULL"),
            ("updated_at", "TIMESTAMP NOT NULL"),
        ],
        indexes=[
            ("idx_share_upload_sessions_household", "household_id"),
            ("idx_share_upload_sessions_user", "created_by"),
        ],
    )
