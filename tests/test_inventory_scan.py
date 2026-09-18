import os
import sys
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils.thumbs import https_url, item_thumb_url
from app.utils.part_icons import icon_for, part_icon_key
from app.utils.stay import same_site_path
from app.utils.barcode_lookup import is_placeholder_name, parse_pack_count, upc_forms, catalog_code
from app.utils.shelf_life import guess_shelf_days, is_meat
from app.utils.vehicle_lookup import diff_vehicle, vehicle_ours, vehicle_theirs, extract_vin, looks_like_vin
from app.utils.scan import (
    _host_wants_scan,
    _sync_grocery_list,
    qty_choices,
    remember_usual,
    usual_amount,
)


class RowPicMacroTests(unittest.TestCase):
    def test_imported_macro_does_not_need_context_name(self):
        from jinja2 import Environment, FileSystemLoader
        import os

        env = Environment(
            loader=FileSystemLoader(os.path.join(ROOT, "app", "templates")),
            autoescape=True,
        )
        env.filters["part_icon"] = icon_for
        src = '{% from "partials/row_pic.html" import row_pic %}\n{{ row_pic(item) }}'
        tmpl = env.from_string(src)
        item = SimpleNamespace(
            name="Cheerios",
            grocery=SimpleNamespace(image_url="https://off.example/c.jpg"),
            photos=[],
        )
        html = tmpl.render(item=item)
        self.assertIn("row-pic", html)
        self.assertIn("https://off.example/c.jpg", html)
        self.assertIn(">C</span>", html)

    def test_nested_pantry_row_qty_filter(self):
        from jinja2 import Environment, FileSystemLoader

        env = Environment(
            loader=FileSystemLoader(os.path.join(ROOT, "app", "templates")),
            autoescape=True,
        )
        env.filters["qty_label"] = lambda v: str(v)
        env.filters["part_icon"] = icon_for
        src = (
            '{% from "partials/row_pic.html" import row_pic %}\n'
            "{% macro pantry_row(item) %}"
            "{{ row_pic(item) }}{{ item.grocery.quantity|qty_label }}"
            "{% endmacro %}\n"
            "{{ pantry_row(item) }}"
        )
        tmpl = env.from_string(src)
        item = SimpleNamespace(
            name="Milk",
            grocery=SimpleNamespace(image_url="", quantity=2),
            photos=[],
        )
        html = tmpl.render(item=item)
        self.assertIn("2", html)
        self.assertIn("row-pic", html)


class PartIconTests(unittest.TestCase):
    def test_alternator_slot(self):
        self.assertEqual(part_icon_key(slot="alternator"), "alternator")

    def test_name_hint(self):
        self.assertEqual(part_icon_key(name="Motorcraft alternator 130A"), "alternator")
        self.assertEqual(part_icon_key(name="DieHard battery"), "battery")

    def test_grocery_kind(self):
        item = SimpleNamespace(
            item_type="grocery",
            name="DieHard Gold",
            slot=None,
            system=None,
            grocery=SimpleNamespace(extra_data={"kind": "car_battery"}),
        )
        self.assertEqual(icon_for(item), "battery")

    def test_cereal_stays_letter(self):
        item = SimpleNamespace(item_type="grocery", name="Cheerios", grocery=None)
        self.assertEqual(icon_for(item), "")


class ShelfLifeTests(unittest.TestCase):
    def test_milk(self):
        self.assertEqual(guess_shelf_days(name="Whole milk", kind="drink", location="fridge"), 10)

    def test_not_oil(self):
        self.assertIsNone(guess_shelf_days(name="5W-30 motor oil", kind="motor_oil"))

    def test_meat_fridge_vs_freezer(self):
        self.assertTrue(is_meat(name="Ground beef"))
        self.assertEqual(guess_shelf_days(name="Ground beef", kind="food"), 4)
        self.assertEqual(guess_shelf_days(name="Ground beef", kind="food", frozen=True), 180)

    def test_cereal(self):
        self.assertEqual(guess_shelf_days(name="Cheerios cereal", kind="food", location="pantry"), 180)
        self.assertEqual(guess_shelf_days(name="Unknown snack", kind="food", location="pantry"), 90)


class PlaceholderNameTests(unittest.TestCase):
    def test_scanned_stub(self):
        self.assertTrue(is_placeholder_name("Scanned 01234567"))
        self.assertTrue(is_placeholder_name("Needs a name · 01234567"))
        self.assertFalse(is_placeholder_name("Cheerios"))
        self.assertTrue(is_placeholder_name(""))


class StayPathTests(unittest.TestCase):
    def test_relative_ok(self):
        self.assertEqual(same_site_path("/groceries/?view=hand"), "/groceries/?view=hand")

    def test_rejects_protocol_relative(self):
        self.assertIsNone(same_site_path("//evil.example/phish"))

    def test_blank(self):
        self.assertIsNone(same_site_path(""))
        self.assertIsNone(same_site_path(None))


class ThumbTests(unittest.TestCase):
    def test_https_upgrade(self):
        self.assertEqual(https_url("http://images.example/x.jpg"), "https://images.example/x.jpg")
        self.assertEqual(https_url("//images.example/x.jpg"), "https://images.example/x.jpg")
        self.assertEqual(https_url("https://ok/x.jpg"), "https://ok/x.jpg")
        self.assertIsNone(https_url(""))
        self.assertIsNone(https_url(None))

    def test_item_thumb_prefers_catalog(self):
        item = SimpleNamespace(
            grocery=SimpleNamespace(image_url="http://off.example/frosted.jpg"),
            photos=[],
        )
        self.assertEqual(item_thumb_url(item), "https://off.example/frosted.jpg")

    def test_item_thumb_none_without_photo(self):
        item = SimpleNamespace(grocery=SimpleNamespace(image_url=""), photos=[])
        self.assertIsNone(item_thumb_url(item))


class VinExtractTests(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(extract_vin("1HGCM82633A004352"), "1HGCM82633A004352")
        self.assertTrue(looks_like_vin("1HGCM82633A004352"))

    def test_code39_stars(self):
        self.assertEqual(extract_vin("*1HGCM82633A004352*"), "1HGCM82633A004352")

    def test_i_prefix(self):
        self.assertEqual(extract_vin("I1HGCM82633A004352"), "1HGCM82633A004352")

    def test_not_upc(self):
        self.assertIsNone(extract_vin("012345678905"))


class VinDiffTests(unittest.TestCase):
    def test_shows_changes_and_fills(self):
        v = SimpleNamespace(
            vin="1FTFW1E84NFA00000",
            year=2018,
            make="Ford",
            model="F-150",
            trim="XL",
            body_class=None,
            drive_type=None,
            fuel_type="Gasoline",
            engine="5.0L",
            transmission=None,
            doors="4",
            manufacturer=None,
            color="Gray",
            plate="ABC123",
        )
        item = SimpleNamespace(name="The gray truck")
        decoded = {
            "vin": "1FTFW1E84NFA00000",
            "name": "2019 Ford F-150 XLT",
            "facts": {
                "year": "2019",
                "make": "Ford",
                "model": "F-150",
                "trim": "XLT",
                "engine": "5.0L V8",
                "body_class": "Pickup",
            },
        }
        diffs = {d["field"]: d for d in diff_vehicle(v, item, decoded)}
        self.assertEqual(diffs["year"]["ours"], "2018")
        self.assertEqual(diffs["year"]["theirs"], "2019")
        self.assertEqual(diffs["year"]["kind"], "change")
        self.assertEqual(diffs["trim"]["theirs"], "XLT")
        self.assertEqual(diffs["body_class"]["kind"], "fill")
        self.assertEqual(diffs["name"]["theirs"], "2019 Ford F-150 XLT")
        self.assertNotIn("make", diffs)
        self.assertNotIn("plate", diffs)

    def test_ours_and_theirs_helpers(self):
        v = SimpleNamespace(vin="ABC", year=None, make="Toyota", model=None, trim=None,
                            body_class=None, drive_type=None, fuel_type=None, engine=None,
                            transmission=None, doors=None, manufacturer=None, color=None, plate=None)
        item = SimpleNamespace(name="Mom's Tacoma")
        ours = vehicle_ours(v, item)
        self.assertEqual(ours["name"], "Mom's Tacoma")
        theirs = vehicle_theirs({"vin": "XYZ", "name": "Tacoma", "facts": {"make": "Toyota"}})
        self.assertEqual(theirs["vin"], "XYZ")
        self.assertEqual(theirs["make"], "Toyota")


class HostScanTests(unittest.TestCase):
    def test_air_filter_on_vehicle(self):
        host = SimpleNamespace(id=1, item_type="vehicle", name="Tacoma")
        item = SimpleNamespace(id=9, name="Fram extra guard air filter", category="filter")
        g = SimpleNamespace(extra_data={"kind": "filter"})
        self.assertTrue(_host_wants_scan(host, item, g))

    def test_any_upc_on_open_host(self):
        host = SimpleNamespace(id=1, item_type="vehicle", name="Tacoma")
        item = SimpleNamespace(id=9, name="Frosted Flakes", category="food")
        g = SimpleNamespace(extra_data={"kind": "food"})
        self.assertTrue(_host_wants_scan(host, item, g))

    def test_not_self(self):
        host = SimpleNamespace(id=1, item_type="tool", name="Generator")
        item = SimpleNamespace(id=1, name="Generator", category="tool")
        self.assertFalse(_host_wants_scan(host, item, None))

    def test_oil_on_mower(self):
        host = SimpleNamespace(id=2, item_type="tool", name="Honda mower")
        item = SimpleNamespace(id=9, name="SAE 30 lawn mower oil", category="")
        g = SimpleNamespace(extra_data={})
        self.assertTrue(_host_wants_scan(host, item, g))


class AutoBasketDecisionTests(unittest.TestCase):
    def test_sync_docstring_mentions_opt_in(self):
        self.assertIn("opted in", _sync_grocery_list.__doc__)


class UpcNormalizeTests(unittest.TestCase):
    def test_upc_a_and_ean13(self):
        forms = upc_forms("012345678905")
        self.assertIn("012345678905", forms)
        self.assertIn("0012345678905", forms)

    def test_ean13_strips_leading_zero(self):
        forms = upc_forms("0012345678905")
        self.assertIn("012345678905", forms)

    def test_catalog_codes(self):
        self.assertEqual(catalog_code("012345678905", ean13=True), "0012345678905")
        self.assertEqual(catalog_code("0012345678905", ean13=False), "012345678905")

    def test_pack_count_chips(self):
        self.assertEqual(parse_pack_count("30 count tortilla chips"), 30)
        self.assertEqual(parse_pack_count({"name": "Lay's", "quantity": "6-pack"}), 6)
        self.assertIsNone(parse_pack_count("Horizon Organic Whole Milk"))
        self.assertIsNone(parse_pack_count("5W-30 motor oil"))


class UsualQtyTests(unittest.TestCase):
    def test_remembers_pack_and_puts_it_first(self):
        g = SimpleNamespace(extra_data={})
        remember_usual(g, "into", 30)
        remember_usual(g, "into", 30)
        remember_usual(g, "into", 12)
        self.assertEqual(usual_amount(g, "into"), 30)
        self.assertEqual(qty_choices(g, "into")[0], 30)
        self.assertIn(1, qty_choices(g, "into"))

    def test_ones_do_not_wipe_pack(self):
        g = SimpleNamespace(extra_data={"usual": {"into": 30, "into_hist": [30]}})
        remember_usual(g, "into", 1)
        self.assertEqual(usual_amount(g, "into"), 30)

    def test_no_usual_defaults(self):
        g = SimpleNamespace(extra_data={})
        self.assertIsNone(usual_amount(g, "into"))
        self.assertEqual(qty_choices(g, "into"), [1, 5, 10])


if __name__ == "__main__":
    unittest.main()
