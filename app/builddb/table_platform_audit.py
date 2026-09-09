from app.builddb.builddb import db, evolve_table


class PlatformAudit(db.Model):
    """What the owner did. Leader name/email is allowed; pantry/notes/photos are not."""

    __tablename__ = "platform_audit"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    owner_id = db.Column(db.Integer, nullable=True)
    action = db.Column(db.String(80), nullable=False)
    household_id = db.Column(db.Integer, nullable=True)
    detail_json = db.Column(db.JSON, nullable=True)
    ip = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())


def create_table():
    evolve_table(
        "platform_audit",
        [
            ("owner_id", "INT NULL"),
            ("action", "VARCHAR(80) NOT NULL"),
            ("household_id", "INT NULL"),
            ("detail_json", "JSON NULL"),
            ("ip", "VARCHAR(64) NULL"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ],
        indexes=[
            ("idx_platform_audit_created", "created_at"),
            ("idx_platform_audit_action", "action"),
            ("idx_platform_audit_household", "household_id"),
        ],
    )
