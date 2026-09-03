from app.builddb.builddb import db, evolve_table


class Vehicle(db.Model):
    __tablename__ = "vehicles"

    item_id = db.Column(
        db.Integer, db.ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    make = db.Column(db.String(80), nullable=True)
    model = db.Column(db.String(80), nullable=True)
    year = db.Column(db.Integer, nullable=True)
    vin = db.Column(db.String(32), nullable=True)
    oil_type = db.Column(db.String(80), nullable=True)
    filter_type = db.Column(db.String(80), nullable=True)
    tire_size = db.Column(db.String(40), nullable=True)
    battery_type = db.Column(db.String(80), nullable=True)
    last_oil_change_mileage = db.Column(db.Integer, nullable=True)
    last_oil_change_date = db.Column(db.Date, nullable=True)
    current_mileage = db.Column(db.Integer, nullable=True)
    manual_url = db.Column(db.String(500), nullable=True)
    extra_data = db.Column(db.JSON, nullable=True)

    item = db.relationship("Item", back_populates="vehicle")


def create_table():
    evolve_table(
        "vehicles",
        [
            ("household_id", "INT NOT NULL"),
            ("make", "VARCHAR(80) NULL"),
            ("model", "VARCHAR(80) NULL"),
            ("year", "INT NULL"),
            ("vin", "VARCHAR(32) NULL"),
            ("oil_type", "VARCHAR(80) NULL"),
            ("filter_type", "VARCHAR(80) NULL"),
            ("tire_size", "VARCHAR(40) NULL"),
            ("battery_type", "VARCHAR(80) NULL"),
            ("last_oil_change_mileage", "INT NULL"),
            ("last_oil_change_date", "DATE NULL"),
            ("current_mileage", "INT NULL"),
            ("manual_url", "VARCHAR(500) NULL"),
            ("extra_data", "JSON NULL"),
        ],
        indexes=[("idx_vehicles_household_id", "household_id")],
    )
