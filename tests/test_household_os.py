import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from datetime import datetime
from types import SimpleNamespace

from app.builddb.table_platform_invites import PlatformInvite
from app.utils.calendar import _rrule, household_ics, subscribe_links, vevent
from app.utils.house_systems import HOUSE_SLOTS, HOUSE_SYSTEMS, house_systems_payload
from app.utils.identity import norm_handle, norm_username, suggest_handle, valid_handle, valid_username
from app.utils.places import DEFAULT_PLACES, _norm
from app.utils.reminders_copy import parse_recurrence, recurrence_label, type_label
from app.utils.search import _like
from app.utils.vehicle_systems import group_parts, systems_payload, valid_slot, valid_system


class PlacesTests(unittest.TestCase):
    def test_norm_collapses_space(self):
        self.assertEqual(_norm("  Garage   shelf 2 "), "Garage shelf 2")

    def test_defaults_exist(self):
        self.assertIn("Fridge", DEFAULT_PLACES)
        self.assertIn("Garage", DEFAULT_PLACES)


class SearchEscapeTests(unittest.TestCase):
    def test_short_rejected(self):
        self.assertEqual(_like("a"), "")
        self.assertEqual(_like("  "), "")

    def test_wildcards_escaped(self):
        like = _like("10%_off")
        self.assertIn(r"\%", like)
        self.assertIn(r"\_", like)
        self.assertTrue(like.startswith("%"))
        self.assertTrue(like.endswith("%"))


class ReminderCopyTests(unittest.TestCase):
    def test_oil_english(self):
        self.assertEqual(type_label("oil_change"), "Oil change")
        self.assertEqual(recurrence_label("180d"), "Every 6 months")
        self.assertEqual(recurrence_label("5000mi"), "Every 5,000 miles")

    def test_parse_rejects_garbage(self):
        self.assertIsNone(parse_recurrence("DROP TABLE"))
        self.assertEqual(parse_recurrence("90d"), "90d")
        self.assertIsNone(parse_recurrence(""))


class HouseSystemTests(unittest.TestCase):
    def test_hvac_filter_slot(self):
        self.assertIn("filter", [s[0] for s in HOUSE_SLOTS["hvac"]])
        payload = house_systems_payload()
        ids = [p["id"] for p in payload]
        self.assertEqual(ids[0], HOUSE_SYSTEMS[0][0])
        self.assertTrue(any(s["id"] == "filter" for s in payload[0]["slots"]))

    def test_vehicle_payload_unchanged_default(self):
        self.assertEqual(valid_system("electrical"), "electrical")
        self.assertEqual(valid_slot("electrical", "battery"), "battery")
        self.assertTrue(systems_payload())
        grouped = group_parts([])
        self.assertTrue(grouped)
        self.assertEqual(grouped[0]["id"], "engine")


class IdentityTests(unittest.TestCase):
    def test_username_rules(self):
        self.assertEqual(norm_username("Maya!"), "maya")
        self.assertTrue(valid_username("dad"))
        self.assertTrue(valid_username("kid_2"))
        self.assertFalse(valid_username("1dad"))
        self.assertFalse(valid_username(""))

    def test_handle_from_house_name(self):
        self.assertEqual(suggest_handle("The Fuentes house"), "fuentes")
        self.assertTrue(valid_handle("fuentes"))
        self.assertEqual(norm_handle("Fuentes!"), "fuentes")


class OwnerKeyTests(unittest.TestCase):
    def test_own_prefix(self):
        code = PlatformInvite.new_code()
        self.assertTrue(code.startswith("OWN-"))
        self.assertGreaterEqual(len(code), 8)


class CalendarIcsTests(unittest.TestCase):
    def _row(self, **kwargs):
        base = dict(
            id=7,
            title="Oil change",
            notes="Civic",
            type="oil_change",
            due_at=datetime(2026, 9, 15, 0, 0, 0),
            recurrence="180d",
            status="open",
            notify_via="both",
            updated_at=datetime(2026, 9, 9, 12, 0, 0),
        )
        base.update(kwargs)
        return SimpleNamespace(**base)

    def test_all_day_and_monthly(self):
        block = vevent(self._row(), "Fuentes")
        self.assertIn("DTSTART;VALUE=DATE:20260915", block)
        self.assertIn("DTEND;VALUE=DATE:20260916", block)
        self.assertIn("RRULE:FREQ=MONTHLY;INTERVAL=6", block)
        self.assertIn("UID:family-rem-7@family.poweredby.top", block)
        self.assertTrue(block.endswith("END:VEVENT"))

    def test_timed_is_floating_not_utc_z(self):
        block = vevent(self._row(due_at=datetime(2026, 9, 15, 9, 30, 0), recurrence=""))
        self.assertIn("DTSTART:20260915T093000", block)
        self.assertNotIn("DTSTART:20260915T093000Z", block)

    def test_mileage_has_no_rrule(self):
        self.assertIsNone(_rrule("5000mi"))
        self.assertEqual(_rrule("30d"), "RRULE:FREQ=MONTHLY;INTERVAL=1")

    def test_feed_is_publish_crlf(self):
        house = SimpleNamespace(name="Fuentes", settings_json={"reminders_via": "both"})
        body = household_ics(house, [self._row()])
        self.assertTrue(body.startswith("BEGIN:VCALENDAR"))
        self.assertIn("METHOD:PUBLISH", body)
        self.assertIn("REFRESH-INTERVAL;VALUE=DURATION:PT1H", body)
        self.assertIn("\r\n", body)
        self.assertTrue(body.endswith("END:VCALENDAR\r\n") or body.strip().endswith("END:VCALENDAR"))

    def test_subscribe_links(self):
        links = subscribe_links(
            "https://family.poweredby.top/reminders/calendar/tok.ics", "Fuentes"
        )
        self.assertTrue(links["apple"].startswith("webcal://"))
        self.assertIn("calendar.google.com/calendar/render?cid=", links["google"])
        self.assertIn("outlook.live.com/calendar/0/addfromweb", links["outlook"])
        self.assertIn("family.poweredby.top", links["google"])


if __name__ == "__main__":
    unittest.main()

