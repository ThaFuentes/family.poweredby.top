from app.builddb.builddb import db, evolve_table


class PasswordReset(db.Model):
    """One-household reset tokens. Never used to reach another tenant."""

    __tablename__ = "password_resets"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    requested_by = db.Column(db.Integer, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())


def create_table():
    evolve_table(
        "password_resets",
        [
            ("household_id", "INT NOT NULL"),
            ("user_id", "INT NOT NULL"),
            ("token_hash", "VARCHAR(64) NOT NULL"),
            ("requested_by", "INT NULL"),
            ("expires_at", "TIMESTAMP NOT NULL"),
            ("used_at", "TIMESTAMP NULL"),
        ],
        indexes=[
            ("idx_pwreset_hash", "token_hash"),
            ("idx_pwreset_user", "user_id"),
            ("idx_pwreset_household", "household_id"),
        ],
    )
