from app.builddb.builddb import db, evolve_table
import secrets


class ServicePass(db.Model):
    """Temp key onto Family OS itself. Not a household invite."""

    __tablename__ = "service_passes"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    code = db.Column(db.String(32), unique=True, nullable=False)
    created_by = db.Column(db.Integer, nullable=True)
    household_id = db.Column(db.Integer, nullable=True)
    label = db.Column(db.String(120), nullable=True)
    max_uses = db.Column(db.Integer, nullable=False, default=1)
    use_count = db.Column(db.Integer, nullable=False, default=0)
    expires_at = db.Column(db.DateTime, nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)
    last_used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())

    @staticmethod
    def new_code():
        raw = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8].upper()
        return f"SRV-{raw}"


def create_table():
    evolve_table(
        "service_passes",
        [
            ("code", "VARCHAR(32) NOT NULL"),
            ("created_by", "INT NULL"),
            ("household_id", "INT NULL"),
            ("label", "VARCHAR(120) NULL"),
            ("max_uses", "INT NOT NULL DEFAULT 1"),
            ("use_count", "INT NOT NULL DEFAULT 0"),
            ("expires_at", "TIMESTAMP NULL"),
            ("revoked_at", "TIMESTAMP NULL"),
            ("last_used_at", "TIMESTAMP NULL"),
        ],
        indexes=[
            ("idx_service_passes_code", "code"),
            ("idx_service_passes_household", "household_id"),
        ],
    )
