from app.builddb.builddb import db, evolve_table
import secrets


class Invite(db.Model):
    __tablename__ = "invites"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    code = db.Column(db.String(32), unique=True, nullable=False)
    role = db.Column(db.String(20), nullable=False, default="member")
    created_by = db.Column(db.Integer, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    used_by = db.Column(db.Integer, nullable=True)
    used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())

    @staticmethod
    def new_code():
        return secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:10].upper()


def create_table():
    evolve_table(
        "invites",
        [
            ("household_id", "INT NOT NULL"),
            ("code", "VARCHAR(32) NOT NULL"),
            ("role", "VARCHAR(20) NOT NULL DEFAULT 'member'"),
            ("created_by", "INT NULL"),
            ("expires_at", "TIMESTAMP NULL"),
            ("used_by", "INT NULL"),
            ("used_at", "TIMESTAMP NULL"),
        ],
        indexes=[
            ("idx_invites_household_id", "household_id"),
            ("idx_invites_code", "code"),
        ],
    )
