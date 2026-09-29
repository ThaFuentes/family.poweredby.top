import os
import sys
import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils.log_apply import (
    apply_log_to_record,
    is_oil_kind,
    maintenance_fields,
    map_log_kind,
)


def make_vehicle(**over):
    host = SimpleNamespace(
        oil_needs=None,
        oil_capacity=None,
        oil_type=None,
        filter_type=None,
        last_oil_change_date=None,
        last_oil_change_mileage=None,
        oil_interval_miles=5000,
        oil_interval_months=6,
        next_oil_due_date=None,
        next_oil_due_mileage=None,
        current_mileage=70000,
        extra_data={},
    )
    for key, value in over.items():
        setattr(host, key, value)
    item = SimpleNamespace(
        item_type="vehicle", household_id=1, id=7, vehicle=host, tool=None
    )
    return item, host


def make_tool(**over):
    host = SimpleNamespace(
        oil_needs=None,
        oil_capacity=None,
        oil_type=None,
        last_oil_date=None,
        last_oil_hours=None,
        oil_interval_hours=25,
        oil_interval_months=None,
        next_oil_due_date=None,
        next_oil_due_hours=None,
        hours_used=30,
        last_maintenance_at=None,
        extra_data={},
    )
    for key, value in over.items():
        setattr(host, key, value)
    item = SimpleNamespace(
        item_type="tool", household_id=1, id=9, vehicle=None, tool=host
    )
    return item, host


def make_row(**over):
    base = dict(
        kind="repair",
        title=None,
        notes=None,
        reading=None,
        happened_on=None,
        extra_data=None,
        maintenance_id=None,
        created_by=1,
    )
    base.update(over)
    return SimpleNamespace(**base)


class LogApplyTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch(
            "app.utils.log_apply._insert_maintenance", return_value=None
        )
        self.addCleanup(patcher.stop)
        self.insert = patcher.start()

    # 1 ---------------------------------------------------------------------
    def test_oil_change_updates_last_and_next_on_a_vehicle(self):
        item, v = make_vehicle()
        row = make_row(
            kind="repair",
            title="Oil change",
            reading=78000,
            happened_on=date(2026, 3, 19),
        )
        apply_log_to_record(item, row)
        self.assertEqual(v.last_oil_change_date, date(2026, 3, 19))
        self.assertEqual(v.last_oil_change_mileage, 78000)
        self.assertEqual(v.next_oil_due_mileage, 83000)
        self.assertEqual(v.next_oil_due_date, date(2026, 9, 19))
        self.assertEqual(v.current_mileage, 78000)

    # 2 ---------------------------------------------------------------------
    def test_oil_change_reads_grade_capacity_and_filter_from_notes(self):
        item, v = make_vehicle()
        row = make_row(
            kind="repair",
            title="Oil change",
            reading=78000,
            happened_on=date(2026, 3, 19),
            notes="5W-30 full synthetic, 6 qt, filter PH8A",
        )
        apply_log_to_record(item, row)
        self.assertIn("5W-30", v.oil_needs or "")
        self.assertEqual(v.oil_capacity, "6 qt")
        self.assertIn("PH8A", v.filter_type or "")

    # 3 ---------------------------------------------------------------------
    def test_older_oil_change_does_not_move_the_record(self):
        item, v = make_vehicle(
            last_oil_change_date=date(2026, 3, 19),
            last_oil_change_mileage=78000,
            next_oil_due_date=date(2026, 9, 19),
            next_oil_due_mileage=83000,
            current_mileage=78000,
        )
        row = make_row(
            kind="repair",
            title="Oil change",
            reading=70000,
            happened_on=date(2026, 1, 1),
        )
        apply_log_to_record(item, row)
        self.assertEqual(v.last_oil_change_date, date(2026, 3, 19))
        self.assertEqual(v.last_oil_change_mileage, 78000)
        self.assertEqual(v.next_oil_due_date, date(2026, 9, 19))
        self.assertEqual(v.next_oil_due_mileage, 83000)
        self.assertEqual(v.current_mileage, 78000)

    # 4 ---------------------------------------------------------------------
    def test_miles_log_raises_odometer_and_leaves_oil(self):
        item, v = make_vehicle()
        row = make_row(kind="miles", reading=90000, happened_on=date(2026, 4, 1))
        apply_log_to_record(item, row)
        self.assertEqual(v.current_mileage, 90000)
        self.assertIsNone(v.last_oil_change_date)
        self.assertIsNone(v.oil_needs)

    # 5 ---------------------------------------------------------------------
    def test_miles_log_never_rolls_the_odometer_back(self):
        item, v = make_vehicle(current_mileage=90000)
        row = make_row(kind="miles", reading=1000)
        apply_log_to_record(item, row)
        self.assertEqual(v.current_mileage, 90000)

    # 6 ---------------------------------------------------------------------
    def test_tool_oil_change_sets_hours_and_next_hours(self):
        item, t = make_tool()
        row = make_row(
            kind="repair",
            title="Oil change",
            reading=40,
            happened_on=date(2026, 5, 1),
        )
        apply_log_to_record(item, row)
        self.assertEqual(t.last_oil_date, date(2026, 5, 1))
        self.assertEqual(t.last_oil_hours, 40)
        self.assertEqual(t.next_oil_due_hours, 65)
        self.assertEqual(t.hours_used, 40)

    # 7 ---------------------------------------------------------------------
    def test_oil_spec_note_sets_needs_and_leaves_last_oil(self):
        item, t = make_tool()
        row = make_row(kind="note", title="Oil spec", notes="SAE 30")
        apply_log_to_record(item, row)
        self.assertIn("SAE 30", t.oil_needs or "")
        self.assertIsNone(t.last_oil_date)

    # 8 ---------------------------------------------------------------------
    def test_plain_repair_leaves_the_oil_record_alone(self):
        item, v = make_vehicle(
            oil_needs="5W-30",
            last_oil_change_date=date(2026, 3, 19),
            last_oil_change_mileage=78000,
        )
        row = make_row(
            kind="repair",
            title="New belt",
            reading=79000,
            happened_on=date(2026, 4, 2),
        )
        apply_log_to_record(item, row)
        self.assertEqual(v.oil_needs, "5W-30")
        self.assertEqual(v.last_oil_change_date, date(2026, 3, 19))
        self.assertEqual(v.current_mileage, 79000)

    # 9 ---------------------------------------------------------------------
    def test_rear_diff_repair_saves_the_fluid_not_engine_oil(self):
        item, v = make_vehicle(extra_data={})
        row = make_row(
            kind="repair", title="rear diff 75W-90", happened_on=date(2026, 4, 2)
        )
        apply_log_to_record(item, row)
        self.assertIn("rear_diff", v.extra_data.get("fluids", {}))
        self.assertIsNone(v.oil_needs)

    # 10 --------------------------------------------------------------------
    def test_oil_kind_maps_to_a_repair_with_service_oil(self):
        kind, title, service = map_log_kind("oil", None)
        self.assertEqual(kind, "repair")
        self.assertEqual(title, "Oil change")
        self.assertEqual(service, "oil")
        self.assertTrue(is_oil_kind("oil-change"))
        self.assertFalse(is_oil_kind("repair"))

    # maintenance ------------------------------------------------------------
    def test_maintenance_row_fields_for_a_repair(self):
        item, _ = make_vehicle()
        row = make_row(kind="repair", title="New belt", happened_on=date(2026, 4, 2))
        fields = maintenance_fields(item, row, False)
        self.assertEqual(fields["type"], "New belt")
        self.assertEqual(fields["parent_type"], "vehicle")
        self.assertEqual(fields["parent_id"], 7)
        self.assertEqual(fields["mileage_or_hours"], None)

    def test_oil_change_maintenance_type(self):
        item, _ = make_vehicle()
        row = make_row(kind="repair", title="Oil change")
        self.assertEqual(maintenance_fields(item, row, True)["type"], "oil_change")

    def test_linked_repair_does_not_insert_another_maintenance_row(self):
        # The maintenance form already owns the record; maintenance_fields
        # refuses so add_item_log never inserts a second row.
        item, _ = make_vehicle()
        row = make_row(kind="repair", title="New belt", maintenance_id=42)
        self.assertIsNone(maintenance_fields(item, row, True))
        self.assertIsNone(maintenance_fields(item, row, False))

    def test_miles_log_does_not_insert_maintenance(self):
        item, _ = make_vehicle()
        row = make_row(kind="miles", reading=90000)
        self.assertIsNone(maintenance_fields(item, row, False))
        apply_log_to_record(item, row)
        self.insert.assert_not_called()

    def test_repair_inserts_one_maintenance_row(self):
        item, _ = make_vehicle()
        row = make_row(kind="repair", title="New belt")
        apply_log_to_record(item, row)
        self.insert.assert_called_once()

    def test_house_item_is_skipped_without_raising(self):
        item = SimpleNamespace(
            item_type="house", household_id=1, id=3, vehicle=None, tool=None
        )
        row = make_row(kind="repair", title="Oil change", reading=100)
        apply_log_to_record(item, row)  # must not raise


if __name__ == "__main__":
    unittest.main()
