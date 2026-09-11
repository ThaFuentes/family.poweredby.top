"""Wipe a household and everything in it. Irreversible."""
from __future__ import annotations

import shutil
from pathlib import Path

from flask import current_app

from app.builddb.builddb import db
from app.builddb.table_grocery_items import GroceryItem
from app.builddb.table_grocery_list import GroceryListEntry
from app.builddb.table_households import Household
from app.builddb.table_invites import Invite
from app.builddb.table_items import Item
from app.builddb.table_legal_files import LegalFile
from app.builddb.table_legal_records import LegalRecord
from app.builddb.table_maintenance_records import MaintenanceRecord
from app.builddb.table_notes import Note
from app.builddb.table_password_resets import PasswordReset
from app.builddb.table_photo_notes import PhotoNote
from app.builddb.table_reminders import Reminder
from app.builddb.table_scan_events import ScanEvent
from app.builddb.table_service_passes import ServicePass
from app.builddb.table_tools import Tool
from app.builddb.table_trusted_emails import TrustedEmail
from app.builddb.table_users import User
from app.builddb.table_vehicle_parts import VehiclePart
from app.builddb.table_vehicles import Vehicle


def confirm_phrase(household: Household) -> str:
    return (household.handle or household.name or "").strip()


def confirm_matches(household: Household, typed: str) -> bool:
    want = confirm_phrase(household)
    got = (typed or "").strip()
    if not want or not got:
        return False
    return want.lower() == got.lower()


def _uploads_dir(household_id: int) -> Path:
    root = Path(current_app.root_path).parent / "uploads"
    return (root / str(household_id)).resolve()


def delete_household(household: Household) -> str:
    hid = int(household.id)
    name = household.name or f"household {hid}"
    folder = _uploads_dir(hid)
    root = Path(current_app.root_path).parent / "uploads"
    if folder.exists() and root in folder.parents:
        shutil.rmtree(folder, ignore_errors=True)

    ServicePass.query.filter_by(household_id=hid).delete(synchronize_session=False)
    TrustedEmail.query.filter_by(household_id=hid).delete(synchronize_session=False)
    ScanEvent.query.filter_by(household_id=hid).delete(synchronize_session=False)
    PhotoNote.query.filter_by(household_id=hid).delete(synchronize_session=False)
    LegalFile.query.filter_by(household_id=hid).delete(synchronize_session=False)
    LegalRecord.query.filter_by(household_id=hid).delete(synchronize_session=False)
    Note.query.filter_by(household_id=hid).delete(synchronize_session=False)
    GroceryListEntry.query.filter_by(household_id=hid).delete(synchronize_session=False)
    Reminder.query.filter_by(household_id=hid).delete(synchronize_session=False)
    MaintenanceRecord.query.filter_by(household_id=hid).delete(synchronize_session=False)
    VehiclePart.query.filter_by(household_id=hid).delete(synchronize_session=False)
    GroceryItem.query.filter_by(household_id=hid).delete(synchronize_session=False)
    Tool.query.filter_by(household_id=hid).delete(synchronize_session=False)
    Vehicle.query.filter_by(household_id=hid).delete(synchronize_session=False)
    Invite.query.filter_by(household_id=hid).delete(synchronize_session=False)
    PasswordReset.query.filter_by(household_id=hid).delete(synchronize_session=False)
    Item.query.filter_by(household_id=hid).delete(synchronize_session=False)
    User.query.filter_by(household_id=hid).delete(synchronize_session=False)
    db.session.delete(household)
    db.session.commit()
    return name
