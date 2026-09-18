import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from datetime import datetime
from types import SimpleNamespace

from app.builddb.table_platform_invites import PlatformInvite
from app.utils.calendar import (
    _rrule,
    calendar_target,
    guess_provider,
    household_ics,
    member_subscribe,
    reminder_invite_ics,
    subscribe_links,
    vevent,
)
from app.utils.house_systems import (
    HOUSE_SLOTS,
    HOUSE_SYSTEMS,
    guess_house_slot,
    house_systems_payload,
)
from app.utils.household_delete import confirm_matches
from app.utils.identity import (
    default_household_name,
    norm_handle,
    norm_username,
    suggest_handle,
    valid_handle,
    valid_username,
)
from app.utils.places import DEFAULT_PLACES, _norm
from app.utils.reminders_copy import parse_recurrence, recurrence_label, type_label
from app.utils.search import _like, tokens
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

    def test_tokens_split_and_cap(self):
        self.assertEqual(tokens("Panasonic TV"), ["panasonic", "tv"])
        self.assertEqual(tokens("alternator"), ["alternator"])
        self.assertEqual(tokens("a"), [])


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

    def test_electronics_and_kitchen(self):
        ids = [p["id"] for p in house_systems_payload()]
        self.assertIn("electronics", ids)
        self.assertIn("fitness", ids)
        elec = next(p for p in house_systems_payload() if p["id"] == "electronics")
        slot_ids = [s["id"] for s in elec["slots"]]
        self.assertIn("tv", slot_ids)
        self.assertIn("laptop", slot_ids)
        self.assertIn("threed_printer", slot_ids)
        apps = next(p for p in house_systems_payload() if p["id"] == "appliances")
        app_slots = [s["id"] for s in apps["slots"]]
        self.assertIn("microwave", app_slots)
        self.assertIn("air_fryer", app_slots)
        self.assertIn("fridge", app_slots)

    def test_guess_house_things(self):
        self.assertEqual(guess_house_slot("Samsung 55 TV"), ("electronics", "tv"))
        self.assertEqual(guess_house_slot("Dell XPS laptop"), ("electronics", "laptop"))
        self.assertEqual(guess_house_slot("Ninja air fryer"), ("appliances", "air_fryer"))
        self.assertEqual(guess_house_slot("NordicTrack treadmill"), ("fitness", "treadmill"))
        self.assertEqual(guess_house_slot("GE microwave"), ("appliances", "microwave"))
        self.assertEqual(guess_house_slot("Clorox pool shock"), ("pool", "shock"))
        self.assertEqual(guess_house_slot("Hayward pool pump"), ("pool", "pump"))
        self.assertEqual(guess_house_slot("Purina layer feed"), ("coop", "feed"))
        self.assertEqual(guess_house_slot("timothy hay bale"), ("coop", "hay"))
        self.assertEqual(guess_house_slot("Moen kitchen faucet"), ("plumbing", "faucet"))

    def test_pool_and_coop_systems(self):
        ids = [p["id"] for p in house_systems_payload()]
        self.assertIn("pool", ids)
        self.assertIn("coop", ids)
        pool = next(p for p in house_systems_payload() if p["id"] == "pool")
        self.assertIn("chlorine", [s["id"] for s in pool["slots"]])
        coop = next(p for p in house_systems_payload() if p["id"] == "coop")
        self.assertIn("feed", [s["id"] for s in coop["slots"]])
        self.assertIn("hay", [s["id"] for s in coop["slots"]])

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

    def test_household_label_from_person_name(self):
        self.assertEqual(default_household_name("Maya Fuentes"), "Maya's house")
        self.assertEqual(default_household_name("James"), "James' house")
        self.assertEqual(default_household_name(""), "House")


class DeleteConfirmTests(unittest.TestCase):
    def test_handle_match(self):
        h = SimpleNamespace(handle="fuentes", name="The Fuentes house")
        self.assertTrue(confirm_matches(h, "fuentes"))
        self.assertTrue(confirm_matches(h, "Fuentes"))
        self.assertFalse(confirm_matches(h, "The Fuentes house"))
        self.assertFalse(confirm_matches(h, ""))


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

    def test_member_subscribe_is_personal(self):
        user = SimpleNamespace(name="Maya Fuentes", username="maya")
        house = SimpleNamespace(name="Fuentes")
        links = member_subscribe(
            user, house, "https://family.poweredby.top/reminders/calendar/tok.ics"
        )
        self.assertEqual(links["who"], "Maya")
        self.assertTrue(links["apple"].startswith("webcal://"))
        self.assertIn("calendar.google.com", links["google"])

    def test_subscribe_links(self):
        links = subscribe_links(
            "https://family.poweredby.top/reminders/calendar/tok.ics", "Fuentes"
        )
        self.assertTrue(links["apple"].startswith("webcal://"))
        self.assertIn("calendar.google.com/calendar/render?cid=", links["google"])
        self.assertIn("outlook.live.com/calendar/0/addfromweb", links["outlook"])
        self.assertIn("family.poweredby.top", links["google"])

    def test_guess_provider_from_inbox(self):
        self.assertEqual(guess_provider("maya@gmail.com"), "google")
        self.assertEqual(guess_provider("dad@icloud.com"), "apple")
        self.assertEqual(guess_provider("work@outlook.com"), "outlook")
        self.assertEqual(guess_provider("other@poweredby.top"), "other")

    def test_calendar_target_names_that_email(self):
        user = SimpleNamespace(
            name="Maya Fuentes",
            username="maya",
            email="maya@gmail.com",
            calendar_email="maya.work@outlook.com",
            calendar_provider=None,
            calendar_mode="auto",
        )
        t = calendar_target(user)
        self.assertEqual(t["cal_email"], "maya.work@outlook.com")
        self.assertEqual(t["cal_provider"], "outlook")
        self.assertTrue(t["cal_auto"])
        self.assertIn("Outlook", t["cal_label"])
        self.assertIn("maya.work@outlook.com", t["cal_label"])

    def test_invite_request_names_attendee(self):
        house = SimpleNamespace(name="Fuentes", settings_json={"reminders_via": "both"})
        body = reminder_invite_ics(
            self._row(), house, "maya@gmail.com", organizer_email="family@x.test"
        )
        self.assertIn("METHOD:REQUEST", body)
        self.assertIn("mailto:maya@gmail.com", body)
        self.assertIn("ORGANIZER;CN=Family OS:mailto:family@x.test", body)
        self.assertIn("PARTSTAT=ACCEPTED", body)

    def test_announce_flash_auto_names_google(self):
        from app.utils.notify import announce_flash

        user = SimpleNamespace(
            name="Maya",
            username="maya",
            email="maya@gmail.com",
            calendar_email=None,
            calendar_provider=None,
            calendar_mode="auto",
            notify_via="both",
        )
        row = SimpleNamespace(title="Next oil change — Civic", due_at=datetime(2026, 10, 1))
        msg = announce_flash(user, row)
        self.assertIn("Google Calendar for maya@gmail.com", msg)
        self.assertIn("2026-10-01", msg)

    def test_announce_flash_manual(self):
        from app.utils.notify import announce_flash

        user = SimpleNamespace(
            name="Maya",
            username="maya",
            email="maya@gmail.com",
            calendar_email="maya@gmail.com",
            calendar_provider="google",
            calendar_mode="manual",
            notify_via="email",
        )
        row = SimpleNamespace(title="Next oil", due_at=datetime(2026, 10, 1))
        msg = announce_flash(user, row)
        self.assertIn("manual", msg.lower())


class ByokTests(unittest.TestCase):
    def test_household_never_inherits_owner_env_key(self):
        old = os.environ.get("GEMINI_API_KEY")
        os.environ["GEMINI_API_KEY"] = "owner-secret-key"
        try:
            from app.utils.ai import DEFAULT_PROVIDER, get_ai_config
            from app.utils.household_ai import household_config

            h = SimpleNamespace(settings_json={})
            cfg = household_config(h)
            self.assertFalse(cfg["has_key"])
            self.assertFalse(cfg.get("from_env"))
            self.assertEqual(cfg["source"], "household")
            self.assertEqual(DEFAULT_PROVIDER, "gemini")
            via = get_ai_config(h)
            self.assertFalse(via["has_key"])
            self.assertEqual(via["source"], "household")
            self.assertNotEqual(via.get("api_key"), "owner-secret-key")
            empty = get_ai_config(None, household_only=True)
            self.assertFalse(empty["has_key"])
            self.assertEqual(empty["source"], "household")
        finally:
            if old is None:
                os.environ.pop("GEMINI_API_KEY", None)
            else:
                os.environ["GEMINI_API_KEY"] = old


if __name__ == "__main__":
    unittest.main()

