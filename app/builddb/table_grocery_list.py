from app.builddb.builddb import db, evolve_table


class GroceryListEntry(db.Model):
    __tablename__ = "grocery_list"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    item_id = db.Column(db.Integer, db.ForeignKey("items.id", ondelete="SET NULL"), nullable=True)
    name = db.Column(db.String(200), nullable=False)
    quantity_needed = db.Column(db.Numeric(12, 3), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="open")
    added_reason = db.Column(db.String(80), nullable=True)
    note = db.Column(db.String(120), nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    completed_at = db.Column(db.DateTime, nullable=True)


def create_table():
    evolve_table(
        "grocery_list",
        [
            ("household_id", "INT NOT NULL"),
            ("item_id", "INT NULL"),
            ("name", "VARCHAR(200) NOT NULL"),
            ("quantity_needed", "DECIMAL(12,3) NULL"),
            ("status", "VARCHAR(20) NOT NULL DEFAULT 'open'"),
            ("added_reason", "VARCHAR(80) NULL"),
            ("note", "VARCHAR(120) NULL"),
            ("created_by", "INT NULL"),
            ("completed_at", "TIMESTAMP NULL"),
        ],
        indexes=[
            ("idx_glist_household_id", "household_id"),
            ("idx_glist_status", "status"),
        ],
    )
