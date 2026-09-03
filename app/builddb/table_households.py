from app.builddb.builddb import db, evolve_table
import secrets


class Household(db.Model):
    __tablename__ = "households"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(150), nullable=False)
    invite_code = db.Column(db.String(32), unique=True, nullable=True)
    settings_json = db.Column(db.JSON, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    extra_data = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    users = db.relationship("User", back_populates="household")

    def rotate_invite_code(self):
        self.invite_code = secrets.token_urlsafe(8).replace("-", "").replace("_", "")[:12].upper()
        return self.invite_code


def create_table():
    evolve_table(
        "households",
        [
            ("invite_code", "VARCHAR(32) NULL"),
            ("settings_json", "JSON NULL"),
            ("is_active", "TINYINT(1) NOT NULL DEFAULT 1"),
            ("extra_data", "JSON NULL"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ],
        indexes=[("idx_households_invite", "invite_code")],
    )
