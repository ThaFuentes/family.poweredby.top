from app.builddb.builddb import db, evolve_table


class ScanEvent(db.Model):
    __tablename__ = "scan_events"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    item_id = db.Column(db.Integer, db.ForeignKey("items.id", ondelete="SET NULL"), nullable=True)
    user_id = db.Column(db.Integer, nullable=True)
    barcode = db.Column(db.String(80), nullable=False)
    action = db.Column(db.String(40), nullable=False)
    amount = db.Column(db.Numeric(12, 3), nullable=True)
    result_json = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())


def create_table():
    evolve_table(
        "scan_events",
        [
            ("household_id", "INT NOT NULL"),
            ("item_id", "INT NULL"),
            ("user_id", "INT NULL"),
            ("barcode", "VARCHAR(80) NOT NULL"),
            ("action", "VARCHAR(40) NOT NULL"),
            ("amount", "DECIMAL(12,3) NULL"),
            ("result_json", "JSON NULL"),
        ],
        indexes=[
            ("idx_scan_household_id", "household_id"),
            ("idx_scan_barcode", "barcode"),
        ],
    )
