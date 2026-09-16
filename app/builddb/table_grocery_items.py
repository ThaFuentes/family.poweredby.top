from app.builddb.builddb import db, evolve_table


class GroceryItem(db.Model):
    __tablename__ = "grocery_items"

    item_id = db.Column(
        db.Integer, db.ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    quantity = db.Column(db.Numeric(12, 3), nullable=False, default=0)
    restock_threshold = db.Column(db.Numeric(12, 3), nullable=False, default=1)
    is_in_stock = db.Column(db.Boolean, default=True, nullable=False)
    needs_restock = db.Column(db.Boolean, default=False, nullable=False)
    default_location = db.Column(db.String(120), nullable=True)
    brand = db.Column(db.String(120), nullable=True)
    size = db.Column(db.String(80), nullable=True)
    unit = db.Column(db.String(40), nullable=True, default="each")
    ingredients = db.Column(db.Text, nullable=True)
    allergens = db.Column(db.String(500), nullable=True)
    serving_size = db.Column(db.String(80), nullable=True)
    packaging = db.Column(db.String(200), nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    auto_basket = db.Column(db.Boolean, default=False, nullable=False)
    last_consumed_at = db.Column(db.DateTime, nullable=True)
    last_restocked_at = db.Column(db.DateTime, nullable=True)
    consume_count = db.Column(db.Integer, default=0, nullable=False)
    extra_data = db.Column(db.JSON, nullable=True)

    item = db.relationship("Item", back_populates="grocery")


def create_table():
    evolve_table(
        "grocery_items",
        [
            ("household_id", "INT NOT NULL"),
            ("quantity", "DECIMAL(12,3) NOT NULL DEFAULT 0"),
            ("restock_threshold", "DECIMAL(12,3) NOT NULL DEFAULT 1"),
            ("is_in_stock", "TINYINT(1) NOT NULL DEFAULT 1"),
            ("needs_restock", "TINYINT(1) NOT NULL DEFAULT 0"),
            ("default_location", "VARCHAR(120) NULL"),
            ("brand", "VARCHAR(120) NULL"),
            ("size", "VARCHAR(80) NULL"),
            ("unit", "VARCHAR(40) NULL DEFAULT 'each'"),
            ("ingredients", "TEXT NULL"),
            ("allergens", "VARCHAR(500) NULL"),
            ("serving_size", "VARCHAR(80) NULL"),
            ("packaging", "VARCHAR(200) NULL"),
            ("image_url", "VARCHAR(500) NULL"),
            ("auto_basket", "TINYINT(1) NOT NULL DEFAULT 0"),
            ("last_consumed_at", "TIMESTAMP NULL"),
            ("last_restocked_at", "TIMESTAMP NULL"),
            ("consume_count", "INT NOT NULL DEFAULT 0"),
            ("extra_data", "JSON NULL"),
        ],
        indexes=[
            ("idx_grocery_household_id", "household_id"),
            ("idx_grocery_needs_restock", "needs_restock"),
        ],
    )
