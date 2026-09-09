#!/usr/bin/env python3
"""Seed a few households with people, groceries, a mower, a truck, and photos."""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

from werkzeug.datastructures import FileStorage

from app import create_app
from app.builddb.builddb import db
from app.builddb.table_grocery_items import GroceryItem
from app.builddb.table_households import Household
from app.builddb.table_items import Item
from app.builddb.table_maintenance_records import MaintenanceRecord
from app.builddb.table_notes import Note
from app.builddb.table_reminders import Reminder
from app.builddb.table_tools import Tool
from app.builddb.table_users import User
from app.builddb.table_vehicles import Vehicle
from app.routes.items import save_item_photo
from app.utils.qr_labels import item_payload
from app.utils.scan import clamp_qty, set_quantity, _sync_grocery_list
from app.utils.vehicle_systems import install_part
from app.builddb.table_vehicle_parts import VehiclePart


PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)
PASSWORD = "FamilyTest1!"


def _user(username, **kwargs):
    row = User.query.filter_by(username=username).first()
    if row:
        for k, v in kwargs.items():
            setattr(row, k, v)
        row.set_password(PASSWORD)
        db.session.flush()
        return row, False
    u = User(username=username, **kwargs)
    u.set_password(PASSWORD)
    db.session.add(u)
    db.session.flush()
    return u, True


def _photo(item, user_id, caption):
    fs = FileStorage(stream=BytesIO(PNG), filename="snap.png", content_type="image/png")
    save_item_photo(item, fs, caption, user_id)


def _grocery(hid, user_id, name, qty, **extra):
    item = Item(
        household_id=hid,
        name=name,
        item_type="grocery",
        category=extra.pop("category", None),
        barcode=extra.pop("barcode", None),
        created_by=user_id,
        linked_item_id=extra.pop("linked_item_id", None),
    )
    db.session.add(item)
    db.session.flush()
    if not item.barcode:
        item.barcode = extra.get("force_barcode") or item_payload(hid, item.id)
    g = GroceryItem(
        item_id=item.id,
        household_id=hid,
        quantity=clamp_qty(qty),
        restock_threshold=extra.get("threshold", 1),
        brand=extra.get("brand"),
        size=extra.get("size"),
        unit=extra.get("unit") or "each",
        default_location=extra.get("location"),
        extra_data=extra.get("extra_data"),
    )
    set_quantity(g, qty)
    g.needs_restock = g.quantity <= g.restock_threshold
    db.session.add(g)
    db.session.flush()
    _sync_grocery_list(g, item, user_id)
    return item, g


def seed():
    app = create_app()
    with app.app_context():
        families = []

        # 1. Fuentes — full garage + pantry
        h = Household.query.filter_by(name="Fuentes house").first()
        if h is None:
            h = Household(name="Fuentes house")
            h.rotate_invite_code()
            db.session.add(h)
            db.session.flush()
        clark, _ = _user(
            "clark",
            household_id=h.id,
            name="Clark",
            email="clark@fuentes.test",
            role="admin",
            is_leader=True,
        )
        lois, _ = _user(
            "lois",
            household_id=h.id,
            name="Lois",
            email="lois@fuentes.test",
            role="member",
            is_leader=False,
        )
        jon, _ = _user(
            "jon",
            household_id=h.id,
            name="Jon",
            email=None,
            role="child",
            is_leader=False,
        )
        truck = Item.query.filter_by(household_id=h.id, name="Gray truck").first()
        if truck is None:
            truck = Item(
                household_id=h.id,
                name="Gray truck",
                item_type="vehicle",
                created_by=clark.id,
            )
            db.session.add(truck)
            db.session.flush()
            truck.barcode = item_payload(h.id, truck.id)
            db.session.add(
                Vehicle(
                    item_id=truck.id,
                    household_id=h.id,
                    make="Ford",
                    model="F-150",
                    year=2018,
                    plate="FAM-150",
                    color="Gray",
                    oil_type="5W-30",
                    filter_type="FL-820S",
                    battery_type="Group 65",
                    current_mileage=87210,
                    fuel_type="Gasoline",
                )
            )
            _photo(truck, clark.id, "The actual truck")
            rec = MaintenanceRecord(
                household_id=h.id,
                parent_type="vehicle",
                parent_id=truck.id,
                type="oil_change",
                date=date.today() - timedelta(days=40),
                mileage_or_hours=Decimal("86400"),
                notes="Filter housing was rusty. Photo of the connectors on the alternator.",
                created_by=clark.id,
            )
            db.session.add(rec)
            db.session.flush()
            photo = save_item_photo(
                truck,
                FileStorage(stream=BytesIO(PNG), filename="alt.png", content_type="image/png"),
                "Alternator connectors",
                clark.id,
            )
            rec.photos = [photo.id] if photo else []
            db.session.add(
                Reminder(
                    household_id=h.id,
                    linked_item_id=truck.id,
                    type="oil_change",
                    title="Next oil change — Gray truck",
                    due_at=datetime.utcnow() + timedelta(days=140),
                    recurrence="180d",
                    status="open",
                    created_by=clark.id,
                )
            )
        if truck and not VehiclePart.query.filter_by(vehicle_item_id=truck.id).first():
            alt = install_part(
                hid=h.id,
                vehicle_item_id=truck.id,
                user_id=clark.id,
                system="electrical",
                slot="alternator",
                name="Motorcraft 130A",
                brand="Motorcraft",
                spec="130A · 3-pin",
                status="installed",
                installed_mileage=86400,
            )
            batt = install_part(
                hid=h.id,
                vehicle_item_id=truck.id,
                user_id=clark.id,
                system="electrical",
                slot="battery",
                name="DieHard Gold Group 65",
                brand="DieHard",
                spec="Group 65 · AGM",
                status="installed",
                installed_mileage=85000,
            )
            install_part(
                hid=h.id,
                vehicle_item_id=truck.id,
                user_id=clark.id,
                system="engine",
                slot="oil",
                name="5W-30 synthetic",
                spec="5W-30 · Dexos1",
                status="installed",
                installed_mileage=86400,
            )
            install_part(
                hid=h.id,
                vehicle_item_id=truck.id,
                user_id=clark.id,
                system="engine",
                slot="oil_filter",
                name="Motorcraft FL-820S",
                spec="FL-820S",
                status="installed",
                installed_mileage=86400,
            )
            if alt:
                save_item_photo(
                    truck,
                    FileStorage(stream=BytesIO(PNG), filename="alt2.png", content_type="image/png"),
                    "Alternator 3-pin connector",
                    clark.id,
                    part_id=alt.id,
                )
            if batt:
                save_item_photo(
                    truck,
                    FileStorage(stream=BytesIO(PNG), filename="batt.png", content_type="image/png"),
                    "Battery terminals",
                    clark.id,
                    part_id=batt.id,
                )
        mower = Item.query.filter_by(household_id=h.id, name="Honda mower").first()
        if mower is None:
            mower = Item(
                household_id=h.id,
                name="Honda mower",
                item_type="tool",
                category="mower",
                created_by=clark.id,
            )
            db.session.add(mower)
            db.session.flush()
            mower.barcode = item_payload(h.id, mower.id)
            db.session.add(
                Tool(
                    item_id=mower.id,
                    household_id=h.id,
                    type="mower",
                    power_source="gas",
                    oil_type="10W-30",
                    fuel_type="87",
                    usage_notes="Prime 3x. Blade bolt is reverse-threaded.",
                    maintenance_interval_hours=25,
                )
            )
            _photo(mower, clark.id, "The actual mower")
            _photo(mower, clark.id, "Serial plate")
        if not Item.query.filter_by(household_id=h.id, name="DieHard Gold Group 65").first():
            batt, g = _grocery(
                h.id,
                clark.id,
                "DieHard Gold Group 65",
                1,
                brand="DieHard",
                location="garage",
                category="auto",
                linked_item_id=truck.id,
                extra_data={"kind": "car_battery", "kind_label": "Car battery"},
            )
            _photo(batt, clark.id, "Battery terminals / connectors")
        if not Item.query.filter_by(household_id=h.id, name="Horizon Whole Milk").first():
            _grocery(h.id, lois.id, "Horizon Whole Milk", 1, brand="Horizon", location="fridge", category="Dairy")
        if not Item.query.filter_by(household_id=h.id, name="Lucky Charms").first():
            _grocery(h.id, jon.id, "Lucky Charms", 0, brand="General Mills", location="pantry", extra_data={"kind": "food"})
        if not Note.query.filter_by(household_id=h.id, title="Alternator notes").first():
            db.session.add(
                Note(
                    household_id=h.id,
                    user_id=clark.id,
                    item_id=truck.id,
                    visibility="household",
                    title="Alternator notes",
                    body="Connector is a 3-pin on the back. Photo on the truck.",
                )
            )
        families.append(("Fuentes house", ["clark", "lois", "jon"]))

        # 2. Rivera
        h2 = Household.query.filter_by(name="Rivera house").first()
        if h2 is None:
            h2 = Household(name="Rivera house")
            h2.rotate_invite_code()
            db.session.add(h2)
            db.session.flush()
        ana, _ = _user("ana", household_id=h2.id, name="Ana", email="ana@rivera.test", role="admin", is_leader=True)
        luis, _ = _user("luis", household_id=h2.id, name="Luis", email="luis@rivera.test", role="member", is_leader=False)
        if not Item.query.filter_by(household_id=h2.id, name="Civic").first():
            car = Item(household_id=h2.id, name="Civic", item_type="vehicle", created_by=ana.id)
            db.session.add(car)
            db.session.flush()
            car.barcode = item_payload(h2.id, car.id)
            db.session.add(
                Vehicle(
                    item_id=car.id,
                    household_id=h2.id,
                    make="Honda",
                    model="Civic",
                    year=2016,
                    plate="RVR-216",
                    oil_type="0W-20",
                    current_mileage=118400,
                )
            )
            _grocery(
                h2.id,
                ana.id,
                "Mobil 1 0W-20",
                2,
                brand="Mobil 1",
                location="garage",
                linked_item_id=car.id,
                extra_data={"kind": "motor_oil", "kind_label": "Motor oil"},
            )
        if not Item.query.filter_by(household_id=h2.id, name="Corn tortillas").first():
            _grocery(h2.id, luis.id, "Corn tortillas", 0, location="fridge")
        families.append(("Rivera house", ["ana", "luis"]))

        # 3. Chen
        h3 = Household.query.filter_by(name="Chen house").first()
        if h3 is None:
            h3 = Household(name="Chen house")
            h3.rotate_invite_code()
            db.session.add(h3)
            db.session.flush()
        mei, _ = _user("mei", household_id=h3.id, name="Mei", email="mei@chen.test", role="admin", is_leader=True)
        wei, _ = _user("wei", household_id=h3.id, name="Wei", email="wei@chen.test", role="member", is_leader=False)
        lily, _ = _user("lily", household_id=h3.id, name="Lily", email=None, role="child", is_leader=False)
        if not Item.query.filter_by(household_id=h3.id, name="AA batteries").first():
            _grocery(
                h3.id,
                wei.id,
                "AA batteries",
                8,
                brand="Duracell",
                location="junk drawer",
                extra_data={"kind": "aa_battery", "kind_label": "Household battery"},
            )
        if not Item.query.filter_by(household_id=h3.id, name="Soy sauce").first():
            _grocery(h3.id, mei.id, "Soy sauce", 1, location="pantry")
        families.append(("Chen house", ["mei", "wei", "lily"]))

        db.session.commit()
        print("Seeded households (password for all: FamilyTest1!)")
        for name, people in families:
            print(f"  {name}: {', '.join(people)}")


if __name__ == "__main__":
    seed()
