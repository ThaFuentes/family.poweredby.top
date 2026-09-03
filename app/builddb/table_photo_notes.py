from app.builddb.builddb import db, evolve_table


class PhotoNote(db.Model):
    __tablename__ = "photo_notes"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    item_id = db.Column(db.Integer, db.ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    caption = db.Column(db.String(255), nullable=True)
    image_path = db.Column(db.String(400), nullable=False)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())

    item = db.relationship("Item", back_populates="photos")


def create_table():
    evolve_table(
        "photo_notes",
        [
            ("household_id", "INT NOT NULL"),
            ("item_id", "INT NOT NULL"),
            ("caption", "VARCHAR(255) NULL"),
            ("image_path", "VARCHAR(400) NOT NULL"),
            ("created_by", "INT NULL"),
        ],
        indexes=[
            ("idx_photos_household_id", "household_id"),
            ("idx_photos_item_id", "item_id"),
        ],
    )
