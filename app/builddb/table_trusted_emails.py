from app.builddb.builddb import db, evolve_table


class TrustedEmail(db.Model):
    """Email that may sign up anytime without a service key."""

    __tablename__ = "trusted_emails"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    added_by = db.Column(db.Integer, nullable=True)
    household_id = db.Column(db.Integer, nullable=True)
    note = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())


def create_table():
    evolve_table(
        "trusted_emails",
        [
            ("email", "VARCHAR(120) NOT NULL"),
            ("added_by", "INT NULL"),
            ("household_id", "INT NULL"),
            ("note", "VARCHAR(200) NULL"),
        ],
        indexes=[
            ("idx_trusted_emails_email", "email"),
            ("idx_trusted_emails_household", "household_id"),
        ],
    )
