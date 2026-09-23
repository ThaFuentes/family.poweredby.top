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
    plate = db.Column(db.String(20), nullable=True)
    color = db.Column(db.String(40), nullable=True)
    trim = db.Column(db.String(80), nullable=True)
    body_class = db.Column(db.String(80), nullable=True)
    drive_type = db.Column(db.String(80), nullable=True)
    fuel_type = db.Column(db.String(80), nullable=True)
    engine = db.Column(db.String(160), nullable=True)
    transmission = db.Column(db.String(80), nullable=True)
    doors = db.Column(db.String(8), nullable=True)
    manufacturer = db.Column(db.String(160), nullable=True)
    oil_type = db.Column(db.String(80), nullable=True)
    filter_type = db.Column(db.String(80), nullable=True)
    tire_size = db.Column(db.String(40), nullable=True)
    battery_type = db.Column(db.String(80), nullable=True)
    last_oil_change_mileage = db.Column(db.Integer, nullable=True)
    last_oil_change_date = db.Column(db.Date, nullable=True)
    oil_needs = db.Column(db.String(200), nullable=True)
    oil_capacity = db.Column(db.String(40), nullable=True)
    oil_interval_miles = db.Column(db.Integer, nullable=True)
    oil_interval_months = db.Column(db.Integer, nullable=True)
    next_oil_due_date = db.Column(db.Date, nullable=True)
    next_oil_due_mileage = db.Column(db.Integer, nullable=True)
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
            ("plate", "VARCHAR(20) NULL"),
            ("color", "VARCHAR(40) NULL"),
            ("trim", "VARCHAR(80) NULL"),
            ("body_class", "VARCHAR(80) NULL"),
            ("drive_type", "VARCHAR(80) NULL"),
            ("fuel_type", "VARCHAR(80) NULL"),
            ("engine", "VARCHAR(160) NULL"),
            ("transmission", "VARCHAR(80) NULL"),
            ("doors", "VARCHAR(8) NULL"),
            ("manufacturer", "VARCHAR(160) NULL"),
            ("oil_type", "VARCHAR(80) NULL"),
            ("filter_type", "VARCHAR(80) NULL"),
            ("tire_size", "VARCHAR(40) NULL"),
            ("battery_type", "VARCHAR(80) NULL"),
            ("last_oil_change_mileage", "INT NULL"),
            ("last_oil_change_date", "DATE NULL"),
            ("oil_needs", "VARCHAR(200) NULL"),
            ("oil_capacity", "VARCHAR(40) NULL"),
            ("oil_interval_miles", "INT NULL"),
            ("oil_interval_months", "INT NULL"),
            ("next_oil_due_date", "DATE NULL"),
            ("next_oil_due_mileage", "INT NULL"),
            ("current_mileage", "INT NULL"),
            ("manual_url", "VARCHAR(500) NULL"),
            ("extra_data", "JSON NULL"),
        ],
        indexes=[("idx_vehicles_household_id", "household_id")],
    )
