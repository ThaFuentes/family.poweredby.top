from app.builddb.builddb import db, evolve_table


class HouseholdActivity(db.Model):
    """What people did in this house. Parents can put it back."""

    __tablename__ = "household_activity"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    user_id = db.Column(db.Integer, nullable=True)
    action = db.Column(db.String(40), nullable=False)
    summary = db.Column(db.String(240), nullable=False)
    target_table = db.Column(db.String(40), nullable=True)
    target_id = db.Column(db.Integer, nullable=True)
    item_id = db.Column(db.Integer, nullable=True)
    old_json = db.Column(db.JSON, nullable=True)
    new_json = db.Column(db.JSON, nullable=True)
    reversible = db.Column(db.Boolean, nullable=False, default=True)
    reversed_at = db.Column(db.DateTime, nullable=True)
    reversed_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())


def create_table():
    evolve_table(
        "household_activity",
        [
            ("household_id", "INT NOT NULL"),
            ("user_id", "INT NULL"),
            ("action", "VARCHAR(40) NOT NULL"),
            ("summary", "VARCHAR(240) NOT NULL"),
            ("target_table", "VARCHAR(40) NULL"),
            ("target_id", "INT NULL"),
            ("item_id", "INT NULL"),
            ("old_json", "JSON NULL"),
            ("new_json", "JSON NULL"),
            ("reversible", "TINYINT(1) NOT NULL DEFAULT 1"),
            ("reversed_at", "TIMESTAMP NULL"),
            ("reversed_by", "INT NULL"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ],
        indexes=[
            ("idx_hact_household", "household_id"),
            ("idx_hact_created", "household_id, created_at"),
            ("idx_hact_item", "item_id"),
        ],
    )
