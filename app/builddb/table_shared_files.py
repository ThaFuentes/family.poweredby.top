"""A household upload that can be shared with the house or by link."""
from app.builddb.builddb import db, evolve_table

SHARE_MODES = ("family", "people", "link", "password")


class SharedFile(db.Model):
    """Encrypted file plus who may open it. The token is the share link."""

    __tablename__ = "shared_files"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    created_by = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title = db.Column(db.String(200), nullable=False, default="")
    original_name = db.Column(db.String(200), nullable=True)
    stored_path = db.Column(db.String(400), nullable=False)
    mime = db.Column(db.String(80), nullable=True)
    size_bytes = db.Column(db.BigInteger, nullable=True)
    token = db.Column(db.String(64), nullable=False)
    share_mode = db.Column(db.String(20), nullable=False, default="family")
    password_hash = db.Column(db.String(256), nullable=True)
    download_count = db.Column(db.Integer, nullable=False, default=0)
    last_download_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    people = db.relationship(
        "SharedFilePerson",
        back_populates="file",
        cascade="all, delete-orphan",
        order_by="SharedFilePerson.id.asc()",
    )


def create_table():
    evolve_table(
        "shared_files",
        [
            ("household_id", "INT NOT NULL"),
            ("created_by", "INT NULL"),
            ("title", "VARCHAR(200) NOT NULL DEFAULT ''"),
            ("original_name", "VARCHAR(200) NULL"),
            ("stored_path", "VARCHAR(400) NOT NULL"),
            ("mime", "VARCHAR(80) NULL"),
            ("size_bytes", "BIGINT NULL"),
            ("token", "VARCHAR(64) NOT NULL"),
            ("share_mode", "VARCHAR(20) NOT NULL DEFAULT 'family'"),
            ("password_hash", "VARCHAR(256) NULL"),
            ("download_count", "INT NOT NULL DEFAULT 0"),
            ("last_download_at", "TIMESTAMP NULL DEFAULT NULL"),
            ("expires_at", "TIMESTAMP NULL DEFAULT NULL"),
            ("revoked_at", "TIMESTAMP NULL DEFAULT NULL"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ],
        indexes=[
            ("idx_shared_files_household", "household_id"),
            ("idx_shared_files_created_by", "created_by"),
            ("uq_shared_files_token", "token", True),
        ],
    )
