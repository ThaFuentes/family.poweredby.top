from app.builddb.builddb import db, evolve_table


class Reminder(db.Model):
    __tablename__ = "reminders"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    linked_item_id = db.Column(db.Integer, db.ForeignKey("items.id", ondelete="SET NULL"), nullable=True)
    type = db.Column(db.String(80), nullable=False)
    title = db.Column(db.String(200), nullable=False, default="")
    due_at = db.Column(db.DateTime, nullable=True)
    recurrence = db.Column(db.String(40), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="open")
    notes = db.Column(db.Text, nullable=True)
    notify_via = db.Column(db.String(16), nullable=True)
    email_sent_at = db.Column(db.DateTime, nullable=True)
    calendar_pushed_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )


def create_table():
    evolve_table(
        "reminders",
        [
            ("household_id", "INT NOT NULL"),
            ("linked_item_id", "INT NULL"),
            ("type", "VARCHAR(80) NOT NULL"),
            ("title", "VARCHAR(200) NOT NULL DEFAULT ''"),
            ("due_at", "TIMESTAMP NULL"),
            ("recurrence", "VARCHAR(40) NULL"),
            ("status", "VARCHAR(20) NOT NULL DEFAULT 'open'"),
            ("notes", "TEXT NULL"),
            ("notify_via", "VARCHAR(16) NULL"),
            ("email_sent_at", "TIMESTAMP NULL"),
            ("calendar_pushed_at", "TIMESTAMP NULL"),
            ("created_by", "INT NULL"),
        ],
        indexes=[
            ("idx_reminders_household_id", "household_id"),
            ("idx_reminders_due", "due_at"),
            ("idx_reminders_status", "status"),
        ],
    )
