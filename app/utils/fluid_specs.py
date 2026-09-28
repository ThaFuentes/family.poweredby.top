"""Built-in fluid specs: answer “what rear diff oil does my 06 tundra take” locally.

No AI key, no web call — common year/make/model machines come from this table.
A saved spec on the household record always wins over the table; the table is the
fallback so a missing AI key never dead-ends a fluid question with the ENGINE oil
answer or “add an AI key”.

Sources are owner's-manual / OEM service-guide specs for the common US market
configurations. Where a model has more than one factory option the table keeps the
most common one and says so in “note”.
"""
from __future__ import annotations

import re

# Every spec dict: needs (engine oil), capacity, filter, transmission, transfer_case,
# rear_diff, front_diff, coolant, brake_fluid, power_steering, note, interval_miles,
# interval_months.
SPECS: tuple[dict, ...] = (
    # ── Toyota trucks / SUVs ────────────────────────────────────────────────
    {
        "match": (2000, 2006, "toyota", "tundra"),
        "needs": "5W-30 (SAE 5W-30, API SL or better)",
        "capacity": "6.5 qt",
        "filter": "Toyota 90915-YZZD1 (or equivalent)",
        "transmission": "Dexron III ATF (A340E/A340F auto)",
        "transfer_case": "DEXRON III ATF (push-button 4WD models use it)",
        "rear_diff": "75W-90 GL-5 (synthetic 75W-90 fine; tow packages often 4.0–4.2 qt)",
        "front_diff": "75W-90 GL-5 (4WD)",
        "coolant": "Toyota Long Life Coolant (red, pink OK on later years)",
        "brake_fluid": "DOT 3",
        "power_steering": "Dexron III ATF",
        "interval_miles": "5000",
        "interval_months": "6",
        "note": "First-gen Tundra (2000–2006). Rear diff on 4x4/tow packs: verify fill after change.",
    },
    {
        "match": (2007, 2013, "toyota", "tundra"),
        "needs": "0W-20 synthetic (5W-30 acceptable on the 5.7L per manual)",
        "capacity": "8.0 qt (5.7L) / 6.9 qt (4.7L)",
        "filter": "Toyota 90915-YZZE1 (5.7L) / 90915-YZZD1 (4.7L)",
        "transmission": "Toyota WS ATF",
        "transfer_case": "Toyota WS ATF (4WD, 07+ models)",
        "rear_diff": "75W-90 GL-5 (synthetic 75W-90 fine)",
        "front_diff": "75W-90 GL-5 (4WD)",
        "coolant": "Toyota SLLC (pink)",
        "brake_fluid": "DOT 3",
        "power_steering": "Dexron III ATF",
        "interval_miles": "5000",
        "interval_months": "6",
        "note": "Second-gen Tundra (2007–2013).",
    },
    {
        "match": (2014, 2021, "toyota", "tundra"),
        "needs": "0W-20 synthetic",
        "capacity": "8.0 qt (5.7L) / 6.9 qt (4.6L)",
        "filter": "Toyota 90915-YZZE1 (5.7L)",
        "transmission": "Toyota WS ATF",
        "transfer_case": "Toyota WS ATF (4WD)",
        "rear_diff": "75W-90 GL-5 (synthetic 75W-90 fine)",
        "front_diff": "75W-90 GL-5 (4WD)",
        "coolant": "Toyota SLLC (pink)",
        "brake_fluid": "DOT 3",
        "power_steering": "Dexron III ATF",
        "interval_miles": "10000",
        "interval_months": "12",
        "note": "Third-gen Tundra (2014–2021); 0W-20 is the manual spec on the 5.7L.",
    },
    {
        "match": (2022, 2027, "toyota", "tundra"),
        "needs": "0W-20 synthetic",
        "capacity": "7.4 qt (i-FORCE) / 9.0 qt (i-FORCE MAX)",
        "filter": "Toyota 04152-YZZA6 (i-FORCE)",
        "transmission": "Toyota WS ATF",
        "transfer_case": "Toyota WS ATF (4WD)",
        "rear_diff": "75W-85 GL-5 (standard) / 75W-90 GL-5 (tow packages)",
        "front_diff": "75W-85 GL-5 (4WD)",
        "coolant": "Toyota SLLC (pink)",
        "brake_fluid": "DOT 3",
        "power_steering": "Electric steering — no fluid",
        "interval_miles": "10000",
        "interval_months": "12",
        "note": "Third-gen Tundra (2022+).",
    },
    {
        "match": (1995, 2004, "toyota", "tacoma"),
        "needs": "5W-30",
        "capacity": "5.5 qt (3.4L V6) / 4.9 qt (2.7L 4-cyl)",
        "filter": "Toyota 90915-YZZD1",
        "transmission": "Dexron III ATF (auto) / 75W-90 GL-4 or GL-5 (manual)",
        "transfer_case": "75W-90 GL-4/GL-5",
        "rear_diff": "75W-90 GL-5 (synthetic 75W-90 fine)",
        "front_diff": "75W-90 GL-5 (4WD, pre-runner excl.)",
        "coolant": "Toyota Long Life Coolant (red)",
        "brake_fluid": "DOT 3",
        "power_steering": "Dexron III ATF",
        "interval_miles": "5000",
        "interval_months": "6",
        "note": "First-gen Tacoma (1995–2004).",
    },
    {
        "match": (2005, 2015, "toyota", "tacoma"),
        "needs": "0W-20 synthetic (2TR-FE 4-cyl) / 5W-30 (1GR-FE V6 pre-2015)",
        "capacity": "6.0 qt (V6) / 5.5 qt (4-cyl)",
        "filter": "Toyota 90915-YZZE1",
        "transmission": "Toyota WS ATF",
        "transfer_case": "Toyota WS ATF (4WD, 09+)",
        "rear_diff": "75W-90 GL-5 (synthetic 75W-90 fine)",
        "front_diff": "75W-90 GL-5 (4WD)",
        "coolant": "Toyota SLLC (pink, 2008+)",
        "brake_fluid": "DOT 3",
        "power_steering": "Dexron III ATF",
        "interval_miles": "5000",
        "interval_months": "6",
        "note": "Second-gen Tacoma (2005–2015).",
    },
    {
        "match": (2016, 2027, "toyota", "tacoma"),
        "needs": "0W-20 synthetic",
        "capacity": "6.1 qt (3.5L V6)",
        "filter": "Toyota 04152-YZZA1",
        "transmission": "Toyota WS ATF",
        "transfer_case": "Toyota WS ATF (4WD)",
        "rear_diff": "75W-85 GL-5 (standard) / 75W-90 GL-5 (TRD tow)",
        "front_diff": "75W-85 GL-5 (4WD)",
        "coolant": "Toyota SLLC (pink)",
        "brake_fluid": "DOT 3",
        "power_steering": "Electric steering — no fluid",
        "interval_miles": "10000",
        "interval_months": "12",
        "note": "Third-gen Tacoma (2016+).",
    },
    {
        "match": (1996, 2002, "toyota", "4runner"),
        "needs": "5W-30",
        "capacity": "5.0 qt (3.4L V6)",
        "filter": "Toyota 90915-YZZD1",
        "transmission": "Dexron III ATF",
        "transfer_case": "Dexron III ATF / 75W-90 GL-4/GL-5 (manual)",
        "rear_diff": "75W-90 GL-5",
        "front_diff": "75W-90 GL-5 (4WD)",
        "coolant": "Toyota Long Life Coolant (red)",
        "brake_fluid": "DOT 3",
        "power_steering": "Dexron III ATF",
        "interval_miles": "5000",
        "interval_months": "6",
        "note": "Third-gen 4Runner (1996–2002).",
    },
    {
        "match": (2003, 2009, "toyota", "4runner"),
        "needs": "5W-30 (4.0L V6)",
        "capacity": "5.0 qt",
        "filter": "Toyota 90915-YZZD1",
        "transmission": "Toyota WS ATF (2005+) / Dexron III (2003–04)",
        "transfer_case": "Toyota WS ATF (2005+) / Dexron III (2003–04)",
        "rear_diff": "75W-90 GL-5",
        "front_diff": "75W-90 GL-5 (4WD)",
        "coolant": "Toyota Long Life / SLLC",
        "brake_fluid": "DOT 3",
        "power_steering": "Dexron III ATF",
        "interval_miles": "5000",
        "interval_months": "6",
        "note": "Fourth-gen 4Runner (2003–2009).",
    },
    {
        "match": (2010, 2024, "toyota", "4runner"),
        "needs": "0W-20 synthetic",
        "capacity": "6.1 qt (4.0L V6)",
        "filter": "Toyota 04152-YZZA1",
        "transmission": "Toyota WS ATF",
        "transfer_case": "Toyota WS ATF (4WD)",
        "rear_diff": "75W-85 GL-5 (standard) / 75W-90 GL-5 (tow)",
        "front_diff": "75W-85 GL-5 (4WD)",
        "coolant": "Toyota SLLC (pink)",
        "brake_fluid": "DOT 3",
        "power_steering": "Hydraulic PSD — Dexron III (most trims)",
        "interval_miles": "10000",
        "interval_months": "12",
        "note": "Fifth-gen 4Runner (2010–2024).",
    },
    {
        "match": (1999, 2005, "toyota", "sienna"),
        "needs": "5W-30",
        "capacity": "4.7 qt (3.0L) / 5.0 qt (3.3L)",
        "filter": "Toyota 90915-YZZD1",
        "transmission": "Dexron III ATF (U151E)",
        "rear_diff": "",
        "front_diff": "",
        "coolant": "Toyota Long Life Coolant (red)",
        "brake_fluid": "DOT 3",
        "power_steering": "Dexron III ATF",
        "interval_miles": "5000",
        "interval_months": "6",
        "note": "First-gen Sienna (1998–2003) — FWD; AWD has no rear diff, it has a rear coupling (Dexron III).",
    },
    {
        "match": (2007, 2020, "toyota", "camry"),
        "needs": "0W-20 synthetic (2.5L 2AR-FE) / 5W-30 (2.4L 2AZ-FE pre-2010, 3.5L V6)",
        "capacity": "4.4–6.4 qt depending on engine",
        "filter": "Toyota 04152-YZZA1 (2AR-FE) / 90915-YZZE1 (V6)",
        "transmission": "Toyota WS ATF",
        "rear_diff": "",
        "front_diff": "",
        "coolant": "Toyota SLLC (pink)",
        "brake_fluid": "DOT 3",
        "power_steering": "Electric (2012+) / Dexron III ATF (older)",
        "interval_miles": "10000",
        "interval_months": "12",
        "note": "Camry (2007–2020) — FWD, no diff services.",
    },
    {
        "match": (2007, 2022, "toyota", "highlander"),
        "needs": "0W-20 synthetic (2.7L/3.5L 2011+) / 5W-30 (older)",
        "capacity": "4.9–6.4 qt depending on engine",
        "filter": "Toyota 04152-YZZA1 / 90915-YZZE1",
        "transmission": "Toyota WS ATF",
        "rear_diff": "Toyota WS ATF (AWD rear coupling)",
        "front_diff": "",
        "coolant": "Toyota SLLC (pink)",
        "brake_fluid": "DOT 3",
        "power_steering": "Electric (2014+) / Dexron III ATF (older)",
        "interval_miles": "10000",
        "interval_months": "12",
        "note": "Highlander (2008–2022) — AWD models use a rear coupling, not a true diff.",
    },
    # ── GM trucks / SUVs ────────────────────────────────────────────────────
    {
        "match": (1999, 2007, "chevrolet", "silverado"),
        "match_alt": (("gmc", "sierra"),),
        "needs": "5W-30 (API SL)",
        "capacity": "6.0 qt (4.8/5.3L) / 6.2 qt (6.0L) / 6.0 qt (8.1L)",
        "filter": "AC Delco PF47 / PF61F",
        "transmission": "Dexron III ATF (4L60E/4L80E) — later 6-speeds: Dexron VI",
        "transfer_case": "Autotrak II (Auto 4WD NP8) / Dexron III (NP261)",
        "rear_diff": "75W-90 GL-5 synthetic (G80 locker: SAE 80W-90 GL-5 + GM friction modifier)",
        "front_diff": "75W-90 GL-5 (4WD)",
        "coolant": "Dex-Cool (orange)",
        "brake_fluid": "DOT 3",
        "power_steering": "GM Power Steering Fluid (Dexron III OK)",
        "interval_miles": "5000",
        "interval_months": "6",
        "note": "GMT800 Silverado/Sierra (1999–2007). G80 locking diff needs GM friction modifier additive.",
    },
    {
        "match": (2007, 2019, "chevrolet", "silverado"),
        "match_alt": (("gmc", "sierra"),),
        "needs": "0W-20 (5.3L/6.2L EcoTec3, 2014+) / 5W-30 (2007–2013 Gen IV)",
        "capacity": "8.0 qt (5.3L/6.2L 2014+) / 6.0 qt (2007–2013)",
        "filter": "AC Delco PF63 (2014+) / PF48 (2007–2013)",
        "transmission": "Dexron VI ATF (6L80/8L90)",
        "transfer_case": "Dexron VI (MP 1625 Auto Trac)",
        "rear_diff": "75W-90 GL-5 synthetic (G80: 75W-85 GL-5 + GM friction modifier)",
        "front_diff": "75W-90 GL-5 (4WD)",
        "coolant": "Dex-Cool (orange)",
        "brake_fluid": "DOT 3",
        "power_steering": "GM Power Steering Fluid",
        "interval_miles": "7500",
        "interval_months": "12",
        "note": "GMT900/K2XX Silverado/Sierra (2007–2019).",
    },
    {
        "match": (2020, 2027, "chevrolet", "silverado"),
        "match_alt": (("gmc", "sierra"),),
        "needs": "0W-20 synthetic (5.3L/6.2L) / 15W-40 diesel (3.0L Duramax)",
        "capacity": "8.0 qt (5.3L/6.2L gas)",
        "filter": "AC Delco PF63 (gas) / PF66 (diesel)",
        "transmission": "Dexron VI ATF (10L90/10L80)",
        "transfer_case": "Dexron VI (MP 2025)",
        "rear_diff": "75W-90 GL-5 synthetic (G80: 75W-85 + modifier)",
        "front_diff": "75W-90 GL-5 (4WD)",
        "coolant": "Dex-Cool (orange)",
        "brake_fluid": "DOT 3",
        "power_steering": "Electric steering — no fluid",
        "interval_miles": "7500",
        "interval_months": "12",
        "note": "T1XX Silverado/Sierra (2020+).",
    },
    {
        "match": (2000, 2006, "chevrolet", "tahoe"),
        "match_alt": (("gmc", "yukon"), ("chevrolet", "suburban")),
        "needs": "5W-30",
        "capacity": "6.0 qt",
        "filter": "AC Delco PF47",
        "transmission": "Dexron III ATF",
        "transfer_case": "Autotrak II / Dexron III",
        "rear_diff": "75W-90 GL-5 synthetic (G80: + GM friction modifier)",
        "front_diff": "75W-90 GL-5 (4WD)",
        "coolant": "Dex-Cool (orange)",
        "brake_fluid": "DOT 3",
        "power_steering": "GM Power Steering Fluid",
        "interval_miles": "5000",
        "interval_months": "6",
        "note": "GMT800 Tahoe/Yukon/Suburban (2000–2006).",
    },
    {
        "match": (2015, 2020, "chevrolet", "tahoe"),
        "match_alt": (("gmc", "yukon"), ("chevrolet", "suburban")),
        "needs": "0W-20 synthetic (5.3L/6.2L)",
        "capacity": "8.0 qt",
        "filter": "AC Delco PF63",
        "transmission": "Dexron VI ATF",
        "transfer_case": "Dexron VI",
        "rear_diff": "75W-90 GL-5 synthetic",
        "front_diff": "75W-90 GL-5 (4WD)",
        "coolant": "Dex-Cool (orange)",
        "brake_fluid": "DOT 3",
        "power_steering": "Electric steering — no fluid",
        "interval_miles": "7500",
        "interval_months": "12",
        "note": "K2XX Tahoe/Yukon/Suburban (2015–2020).",
    },
    # ── Ford trucks / SUVs ─────────────────────────────────────────────────
    {
        "match": (2004, 2014, "ford", "f-150"),
        "needs": "5W-20 (4.6L/5.4L Triton) / 5W-30 (4.2L V6)",
        "capacity": "7.0 qt (5.4L) / 6.0 qt (4.6L)",
        "filter": "Motorcraft FL-820S",
        "transmission": "Mercon LV (4R75E/6R80)",
        "transfer_case": "Mercon LV (ESOF BW4419)",
        "rear_diff": "75W-140 synthetic (9.75-in) / 75W-90 GL-5 (8.8-in)",
        "front_diff": "75W-90 GL-5 (4WD)",
        "coolant": "Motorcraft Orange / Gold (2011+)",
        "brake_fluid": "DOT 3",
        "power_steering": "Mercon V (hydro-boost equipped) / EP steering fluid",
        "interval_miles": "5000",
        "interval_months": "6",
        "note": "11th/12th-gen F-150 (2004–2014). 9.75-in rear takes 75W-140 synth — check axle tag.",
    },
    {
        "match": (2015, 2024, "ford", "f-150"),
        "needs": "5W-30 (5.0L Coyote) / 5W-20 (3.5L EcoBoost/2.7L)",
        "capacity": "8.8 qt (5.0L) / 6.0 qt (3.5L Eco)",
        "filter": "Motorcraft FL-2062 (5.0L) / FL-2062A (EcoBoost)",
        "transmission": "Mercon ULV (10R80) / Mercon LV (6R80)",
        "transfer_case": "Mercon LV",
        "rear_diff": "75W-140 synthetic (9.75-in / 8.8-in tow) / 75W-90 GL-5 (standard 8.8)",
        "front_diff": "75W-90 GL-5 (4WD)",
        "coolant": "Motorcraft Yellow (2018+)",
        "brake_fluid": "DOT 4 (2018+) / DOT 3 (2015–2017)",
        "power_steering": "Electric steering — no fluid",
        "interval_miles": "7500",
        "interval_months": "12",
        "note": "13th-gen F-150 (2015–2024). Verify rear axle tag — tow axles need 75W-140 synth.",
    },
    {
        "match": (2011, 2019, "ford", "super duty"),
        "match_alt": ((2011, 2019, "ford", "f-250"), (2011, 2019, "ford", "f-350")),
        "needs": "15W-40 diesel (6.7L Power Stroke) / 5W-30 or 10W-30 (6.2L gas)",
        "capacity": "13.0 qt (6.7L diesel)",
        "filter": "Motorcraft FL-2051S (diesel)",
        "transmission": "Mercon LV (6R140) / TorqShift",
        "transfer_case": "Mercon LV",
        "rear_diff": "75W-140 synthetic (Dana Super 60 / 10.25–10.5-in)",
        "front_diff": "75W-140 synthetic (Dana 50/60, 4WD)",
        "coolant": "Motorcraft Gold (pre-2020 diesel: + SCA additive)",
        "brake_fluid": "DOT 3",
        "power_steering": "Mercon LV (hydro-boost)",
        "interval_miles": "7500",
        "interval_months": "6",
        "note": "Super Duty (2011–2019). Diesel oil changes per IOLM; heavy tow shortens.",
    },
    {
        "match": (2000, 2007, "ford", "excursion"),
        "needs": "15W-40 diesel (7.3L Power Stroke) / 10W-30 (6.8L V10 / 5.4L)",
        "capacity": "15.0 qt (7.3L)",
        "filter": "Motorcraft FL-1995 (7.3L)",
        "transmission": "Mercon V (4R100) / Mercon LV (5R110 2003+)",
        "transfer_case": "Mercon V (ESOF)",
        "rear_diff": "75W-140 synthetic (Dana 50/60, 10.25-in)",
        "front_diff": "75W-140 synthetic (4WD)",
        "coolant": "Motorcraft Gold Diesel + SCA",
        "brake_fluid": "DOT 3",
        "power_steering": "Mercon V (hydro-boost)",
        "interval_miles": "5000",
        "interval_months": "6",
        "note": "Excursion (2000–2005). Diesel oil is 15 qt — have it on hand.",
    },
    {
        "match": (2003, 2007, "ford", "f-250"),
        "match_alt": ((2003, 2007, "ford", "f-350"),),
        "needs": "15W-40 diesel (6.0L Power Stroke) / 10W-30 gas",
        "capacity": "15.0 qt (6.0L)",
        "filter": "Motorcraft FL-2016 (6.0L)",
        "transmission": "Mercon LV / TorqShift 5R110",
        "transfer_case": "Mercon LV (ESOF)",
        "rear_diff": "75W-140 synthetic (Dana Super 60 / 10.5-in)",
        "front_diff": "75W-140 synthetic (4WD)",
        "coolant": "Motorcraft Gold Diesel (CIM) + SCA",
        "brake_fluid": "DOT 3",
        "power_steering": "Mercon V (hydro-boost)",
        "interval_miles": "5000",
        "interval_months": "6",
        "note": "Super Duty (2003–2007) with 6.0L diesel — oil cooler service is a known item.",
    },
    {
        "match": (2000, 2007, "ford", "f-250"),
        "match_alt": ((2000, 2007, "ford", "f-350"),),
        "needs": "15W-40 diesel (7.3L Power Stroke) / 10W-30 (5.4L/6.8L gas)",
        "capacity": "14.0 qt (7.3L)",
        "filter": "Motorcraft FL-1995 (7.3L)",
        "transmission": "Mercon V (4R100)",
        "transfer_case": "Mercon V / ESOF",
        "rear_diff": "75W-140 synthetic (Dana 80 / 10.25-in)",
        "front_diff": "75W-140 synthetic (4WD, Dana 50/60)",
        "coolant": "Motorcraft Gold Diesel + SCA",
        "brake_fluid": "DOT 3",
        "power_steering": "Mercon V (hydro-boost)",
        "interval_miles": "5000",
        "interval_months": "6",
        "note": "Super Duty (1999–2003) with 7.3L Power Stroke.",
    },
    {
        "match": (2003, 2012, "ford", "econoline"),
        "match_alt": ((2003, 2012, "ford", "e-series"), (2003, 2012, "ford", "e250")),
        "needs": "5W-20 (4.6L/5.4L) / 15W-40 diesel (6.0L Power Stroke)",
        "capacity": "6.0 qt (gas V8) / 15.0 qt (6.0L diesel)",
        "filter": "Motorcraft FL-820S (gas) / FL-2016 (diesel)",
        "transmission": "Mercon V (4R75E/5R110)",
        "rear_diff": "75W-140 synthetic (Dana 60) / 75W-90 (8.8-in)",
        "front_diff": "",
        "coolant": "Motorcraft Gold",
        "brake_fluid": "DOT 3",
        "power_steering": "Mercon V (hydro-boost)",
        "interval_miles": "5000",
        "interval_months": "6",
        "note": "E-Series van (2003–2012) — gas and diesel variants.",
    },
    {
        "match": (1992, 2011, "ford", "ranger"),
        "needs": "5W-30 (4.0L OHV/SOHC)",
        "capacity": "5.0 qt",
        "filter": "Motorcraft FL-1A / FL-400S (SOHC)",
        "transmission": "Mercon V (5R55E) / 75W-90 GL-4 (manual)",
        "transfer_case": "Mercon V (ESOF 1354/1364)",
        "rear_diff": "75W-90 GL-5 (7.5-in/8.8-in)",
        "front_diff": "75W-90 GL-5 (4WD)",
        "coolant": "Motorcraft Green (G05)",
        "brake_fluid": "DOT 3",
        "power_steering": "Mercon V",
        "interval_miles": "5000",
        "interval_months": "6",
        "note": "Ford Ranger (1992–2011).",
    },
    {
        "match": (2011, 2023, "ford", "explorer"),
        "needs": "5W-20 synthetic blend (3.5L V6) / 5W-30 (3.5L Eco)",
        "capacity": "6.0 qt",
        "filter": "Motorcraft FL-500S",
        "transmission": "Mercon LV (6F35/6F50)",
        "rear_diff": "75W-90 GL-5 (AWD PTU uses Mercon LV — do not confuse the two)",
        "front_diff": "",
        "coolant": "Motorcraft Orange",
        "brake_fluid": "DOT 3",
        "power_steering": "Electric steering — no fluid",
        "interval_miles": "7500",
        "interval_months": "12",
        "note": "Explorer (2011–2023) — AWD PTU takes Mercon LV and is commonly missed.",
    },
    # ── Dodge / Ram ────────────────────────────────────────────────────────
    {
        "match": (2003, 2009, "dodge", "ram 2500"),
        "match_alt": ((2003, 2009, "dodge", "ram 3500"), ((2003, 2009, "dodge", "ram 1500"),)),
        "needs": "15W-40 diesel (5.9L Cummins) / 5W-30 (5.7L HEMI)",
        "capacity": "12.0 qt (5.9L Cummins) / 7.0 qt (5.7L)",
        "filter": "Mopar 5083285AA (Cummins) / MO-899 (HEMI)",
        "transmission": "ATF+4 (48RE / 545RFE)",
        "transfer_case": "ATF+4 (NP271/273)",
        "rear_diff": "75W-140 synthetic (AAM 11.5-in) / 75W-90 (9.25-in)",
        "front_diff": "75W-90 GL-5 (4WD, AAM 9.25)",
        "coolant": "HOAT (Hybrid OAT, Mopar orange)",
        "brake_fluid": "DOT 3",
        "power_steering": "Mopar Power Steering Fluid",
        "interval_miles": "7500",
        "interval_months": "6",
        "note": "Third-gen Ram (2003–2009). ATF+4 only in the trans — Dexron harms it.",
    },
    {
        "match": (2010, 2018, "ram", "2500"),
        "match_alt": ((2010, 2018, "ram", "1500"), (2010, 2018, "ram", "3500")),
        "needs": "15W-40 diesel (6.7L Cummins) / 0W-40 or 5W-20 (5.7L HEMI per year)",
        "capacity": "12.0 qt (6.7L) / 7.0 qt (5.7L)",
        "filter": "Mopar 68157990AA (Cummins) / MO-899 (HEMI)",
        "transmission": "ATF+4 (66RFE/68RFE) / ZF 8HP: ZF 8&9 Lifeguard Fluid (2013+ 1500)",
        "transfer_case": "ATF+4 (BW44-44/45)",
        "rear_diff": "75W-140 synthetic (AAM 11.5/11.8-in) / 75W-90 (9.25-in)",
        "front_diff": "75W-90 GL-5 (4WD)",
        "coolant": "OAT (Mopar purple, 2013+) / HOAT (2010–2012)",
        "brake_fluid": "DOT 3",
        "power_steering": "Mopar Power Steering Fluid",
        "interval_miles": "7500",
        "interval_months": "6",
        "note": "Fourth-gen Ram (2010–2018). Verify by engine — HEMI spec changed by year.",
    },
    {
        "match": (2019, 2027, "ram", "1500"),
        "needs": "0W-20 synthetic (3.6L Pentastar) / 5W-30 (5.7L HEMI eTorque)",
        "capacity": "7.0 qt (5.7L) / 6.0 qt (3.6L)",
        "filter": "Mopar MO-899 (HEMI)",
        "transmission": "ZF 8HP75: ZF Lifeguard Fluid 8 (8HP75)",
        "transfer_case": "BW44-45: ATF+4",
        "rear_diff": "75W-90 GL-5 synthetic (9.76-in) / 75W-140 (tow)",
        "front_diff": "75W-90 GL-5 (4WD)",
        "coolant": "OAT (Mopar purple)",
        "brake_fluid": "DOT 3",
        "power_steering": "Electric steering — no fluid",
        "interval_miles": "10000",
        "interval_months": "12",
        "note": "Fifth-gen Ram 1500 (2019+ DT).",
    },
    {
        "match": (2011, 2021, "dodge", "grand caravan"),
        "match_alt": ((2011, 2016, "chrysler", "town & country"),),
        "needs": "5W-20 synthetic blend (3.6L Pentastar)",
        "capacity": "6.0 qt",
        "filter": "Mopar MO-899",
        "transmission": "ATF+4 (62TE)",
        "rear_diff": "",
        "front_diff": "",
        "coolant": "OAT (Mopar purple)",
        "brake_fluid": "DOT 3",
        "power_steering": "ATF+4",
        "interval_miles": "5000",
        "interval_months": "6",
        "note": "Grand Caravan / Town & Country (2011–2016ish, 3.6L).",
    },
    # ── Honda ──────────────────────────────────────────────────────────────
    {
        "match": (2006, 2011, "honda", "civic"),
        "needs": "5W-20 (1.8L R18)",
        "capacity": "3.9 qt",
        "filter": "Honda 15400-PLM-A02",
        "transmission": "Honda ATF DW-1 (auto) / MTF (manual)",
        "rear_diff": "",
        "front_diff": "",
        "coolant": "Honda Type 2 (blue)",
        "brake_fluid": "DOT 3",
        "power_steering": "Honda PS Fluid (pre-2012 hydraulic)",
        "interval_miles": "7500",
        "interval_months": "12",
        "note": "Eighth-gen Civic (2006–2011). FWD — no diff services.",
    },
    {
        "match": (2012, 2020, "honda", "civic"),
        "needs": "0W-20 synthetic (1.8L / 1.5T)",
        "capacity": "3.9–4.4 qt",
        "filter": "Honda 15400-PLM-A02",
        "transmission": "Honda ATF DW-1 (CVT: HCF-2 on 1.5T)",
        "rear_diff": "",
        "front_diff": "",
        "coolant": "Honda Type 2 (blue)",
        "brake_fluid": "DOT 3",
        "power_steering": "Electric steering — no fluid",
        "interval_miles": "7500",
        "interval_months": "12",
        "note": "Ninth/tenth-gen Civic.",
    },
    {
        "match": (2003, 2015, "honda", "pilot"),
        "needs": "5W-20 (3.5L J35)",
        "capacity": "4.5–5.0 qt",
        "filter": "Honda 15400-PLM-A02",
        "transmission": "Honda ATF DW-1 (Z1 on pre-2011)",
        "rear_diff": "Honda DPSF (AWD) — VTM-4 rear diff",
        "front_diff": "",
        "coolant": "Honda Type 2 (blue)",
        "brake_fluid": "DOT 3",
        "power_steering": "Honda PS Fluid",
        "interval_miles": "7500",
        "interval_months": "12",
        "note": "Pilot AWD rear diff takes Honda DPSF (VTM-4) — nothing else.",
    },
    {
        "match": (2016, 2022, "honda", "pilot"),
        "needs": "0W-20 synthetic (3.5L J35)",
        "capacity": "5.7 qt",
        "filter": "Honda 15400-PLM-A02",
        "transmission": "Honda ATF DW-1 (6AT) / HCF-2 (9AT 2019+)",
        "rear_diff": "Honda DPSF (AWD)",
        "front_diff": "",
        "coolant": "Honda Type 2 (blue)",
        "brake_fluid": "DOT 3",
        "power_steering": "Electric steering — no fluid",
        "interval_miles": "7500",
        "interval_months": "12",
        "note": "Third-gen Pilot (2016–2022).",
    },
    {
        "match": (2003, 2016, "honda", "accord"),
        "needs": "5W-20 (2.4L K24) / 0W-20 (2013+ CVT)",
        "capacity": "4.4–4.6 qt",
        "filter": "Honda 15400-PLM-A02",
        "transmission": "Honda ATF DW-1 (auto) / MTF (manual)",
        "rear_diff": "",
        "front_diff": "",
        "coolant": "Honda Type 2 (blue)",
        "brake_fluid": "DOT 3",
        "power_steering": "Honda PS Fluid (hydraulic years)",
        "interval_miles": "7500",
        "interval_months": "12",
        "note": "Accord (2003–2016).",
    },
    # ── Common tools / equipment ───────────────────────────────────────────
    {
        "match": (0, 0, "generator", ""),
        "needs": "SAE 10W-30 (above 40°F) / 5W-30 synthetic (all temps) / SAE 30 (above 40°F, steady load)",
        "capacity": "per model — usually 0.4–1.1 qt",
        "filter": "",
        "transmission": "",
        "rear_diff": "",
        "front_diff": "",
        "coolant": "Air-cooled — none",
        "brake_fluid": "",
        "power_steering": "",
        "interval_miles": "",
        "interval_months": "6",
        "interval_hours": "50",
        "note": "Small engine (Honda GX / Briggs). 10W-30 is the safe default; change at 50 hours or 6 months.",
    },
    {
        "match": (0, 0, "lawn mower", ""),
        "match_alt": ((0, 0, "mower", ""), (0, 0, "lawnmower", "")),
        "needs": "SAE 30 (above 40°F) / 10W-30 (variable temps) / 5W-30 synthetic",
        "capacity": "15–20 oz typical push mower",
        "filter": "",
        "transmission": "",
        "rear_diff": "",
        "front_diff": "",
        "coolant": "Air-cooled — none",
        "brake_fluid": "",
        "power_steering": "",
        "interval_miles": "",
        "interval_months": "12",
        "interval_hours": "25",
        "note": "Push mower small engine — change every season or 25 hours.",
    },
    {
        "match": (0, 0, "pressure washer", ""),
        "needs": "SAE 10W-30 (engine) + pump oil SAE 15W-40 non-detergent (most axial pumps)",
        "capacity": "engine 15–20 oz / pump ~4–8 oz",
        "filter": "",
        "transmission": "",
        "rear_diff": "",
        "front_diff": "",
        "coolant": "Air-cooled — none",
        "brake_fluid": "",
        "power_steering": "",
        "interval_miles": "",
        "interval_months": "12",
        "interval_hours": "50",
        "note": "Two oils: engine oil and pump oil. Pump oil after first 10 hours, then every 50.",
    },
)

def _normalize_alts() -> None:
    """match_alt may be written (make, model) to inherit years, or a full 4-tuple."""
    for row in SPECS:
        lo, hi = row["match"][0], row["match"][1]
        fixed = []
        for alt in row.get("match_alt") or ():
            if len(alt) == 4:
                fixed.append(tuple(alt))
            elif len(alt) == 2:
                fixed.append((lo, hi, alt[0], alt[1]))
            else:
                for inner in alt:
                    if len(inner) == 4:
                        fixed.append(tuple(inner))
        row["match_alt"] = tuple(fixed)


_normalize_alts()


# Words that mean the small-engine wildcard rows (no year/make/model needed).
_TOOL_MODELS = ("generator", "gen", "genset", "mower", "lawn mower", "lawnmower",
                "pressure washer", "weed eater", "chainsaw")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def _norm_model(text: str) -> str:
    t = _clean(text)
    t = t.replace("chevy ", "chevrolet ").replace("gmc ", "gmc ")
    t = re.sub(r"\bf[\s-]?150\b", "f-150", t)
    t = re.sub(r"\bf[\s-]?250\b", "f-250", t)
    t = re.sub(r"\bf[\s-]?350\b", "f-350", t)
    t = t.replace("4 runner", "4runner").replace("4-runner", "4runner")
    t = t.replace("superduty", "super duty")
    t = re.sub(r"\beconoline\b|\be\s?[- ]?series\b", "econoline", t)
    t = re.sub(r"\btown\s*(?:and|&|n)\s*country\b", "town & country", t)
    return t


def _tool_row(text: str) -> dict | None:
    t = _clean(text)
    for row in SPECS:
        model = row["match"][2] or ""
        if not model or row["match"][0] != 0:
            continue
        if model in t or model.replace("lawn ", "") in t:
            return row
    return None


def _row_for(year: int, make: str, model: str) -> dict | None:
    make_n = _norm_model(make)
    model_n = _norm_model(model)
    for row in SPECS:
        lo, hi, rmake, rmodel = row["match"]
        if not _norm_model(rmake) == make_n:
            # match_alt covers badge twins (Silverado/Sierra, Tahoe/Yukon…)
            alts = row.get("match_alt") or ()
            hit = False
            for a in alts:
                lo2, hi2, mk2, md2 = a
                if lo2 <= year <= hi2 and _norm_model(mk2) == make_n and _norm_model(md2) == model_n:
                    hit = True
                    break
            if not hit:
                continue
        elif not (lo <= year <= hi and _norm_model(rmodel) == model_n):
            alts = row.get("match_alt") or ()
            hit = False
            for a in alts:
                lo2, hi2, mk2, md2 = a
                if lo2 <= year <= hi2 and _norm_model(mk2) == make_n and _norm_model(md2) == model_n:
                    hit = True
                    break
            if not hit:
                continue
        return row
    return None


def _years(text: str) -> list[int]:
    out = []
    for m in re.finditer(r"\b(19[89]\d|20[0-3]\d)\b", text or ""):
        y = int(m.group(1))
        if 1980 <= y <= 2035:
            out.append(y)
    # "06 tundra" / "‘06" — two-digit years only when the century word is absent.
    for m in re.finditer(r"(?<![\w])(['’`])?0?\d{2}(?=[\s\w])", text or ""):
        tok = (m.group(0) or "").strip().strip("'’`")
        if not tok or not tok.isdigit() or len(tok) != 2:
            continue
        n = int(tok)
        if n <= 30:
            out.append(2000 + n)
        elif n <= 99:
            out.append(1900 + n)
    return out


def _machine_blob(item) -> str:
    parts = []
    for obj in (item, getattr(item, "vehicle", None), getattr(item, "tool", None)):
        if obj is None:
            continue
        for key in ("name", "notes", "category", "make", "model", "year", "trim", "type"):
            val = getattr(obj, key, None)
            if val:
                parts.append(str(val))
    return _clean(" ".join(parts))


_ALL_MODELS: dict[str, tuple[str, str]] = {}
for _row in SPECS:
    _lo, _hi, _mk, _md = _row["match"]
    if _md:
        _ALL_MODELS[_norm_model(_md)] = (_norm_model(_mk), _md)
    for _alt in _row.get("match_alt") or () :
        if _alt[3]:
            _ALL_MODELS.setdefault(_norm_model(_alt[3]), (_norm_model(_alt[2]), _alt[3]))


def _row_by_model_name(blob: str, year: int | None) -> dict | None:
    """"06 tundra”, “my silverado” — a model word with no make word still matches."""
    text = _norm_model(blob)
    best = None
    for model_key, (make_key, model) in _ALL_MODELS.items():
        if not re.search(rf"\b{re.escape(model_key)}\b", text):
            continue
        for row in SPECS:
            lo, hi, mk, md = row["match"]
            cands = [row["match"]] + list(row.get("match_alt") or ())
            for lo2, hi2, mk2, md2 in cands:
                if _norm_model(md2) == model_key and _norm_model(mk2) == make_key:
                    if year is None or lo2 <= year <= hi2:
                        return row
                    best = best or row
    return best


def spec_for(item) -> dict | None:
    """Built-in spec for a saved vehicle/tool item (its own row, not a dict card)."""
    if item is None:
        return None
    blob = _machine_blob(item)
    if not blob:
        return None
    tool_row = _tool_row(blob)
    if tool_row:
        return dict(tool_row)
    year = None
    vehicle = getattr(item, "vehicle", None)
    if vehicle is not None and getattr(vehicle, "year", None):
        try:
            year = int(str(vehicle.year)[:4])
        except (TypeError, ValueError):
            year = None
    if year is None:
        found = _years(blob)
        year = found[0] if found else None
    make = str(getattr(vehicle, "make", None) or "") if vehicle is not None else ""
    model = str(getattr(vehicle, "model", None) or "") if vehicle is not None else ""
    if not make:
        # Pull make/model words out of the name for rows saved with just a name.
        make, model = _make_model_from_name(blob, year)
    if make and make.lower() not in ("", "unknown"):
        return _row_for(year or 0, make, model) if year else None
    # No make anywhere — a bare model word ("06 tundra") still matches its row.
    return _row_by_model_name(blob, year)


def _make_model_from_name(blob: str, year: int | None) -> tuple[str, str]:
    _MAKES = (
        "toyota", "ford", "chevrolet", "chevy", "gmc", "dodge", "ram", "honda",
        "nissan", "jeep", "chrysler", "lexus", "kia", "hyundai",
    )
    make = ""
    model = ""
    rest = blob
    for m in _MAKES:
        if re.search(rf"\b{re.escape(m)}\b", blob):
            make = "chevrolet" if m == "chevy" else m
            idx = blob.find(m) + len(m)
            rest = blob[idx:]
            break
    if not make:
        return "", ""
    rest = _norm_model(rest)
    if year:
        rest = re.sub(rf"\b{year}\b", " ", rest)
    for m in re.finditer(r"\b(19[89]\d|20[0-3]\d)\b", rest):
        rest = rest.replace(m.group(0), " ")
    for m in re.finditer(r"(?<![\w\d])0?\d{2}(?![\d])", rest):
        tok = m.group(0).strip()
        if tok.isdigit() and int(tok) <= 30:
            rest = rest.replace(m.group(0), " ", 1)
    words = [w for w in rest.split() if len(w) > 1]
    if words:
        # Model words end at common stop words (color, trim, extra descriptors).
        stops = {"xlt", "lariat", "se", "le", "xle", "trd", "sr5", "limited", "white",
                 "black", "blue", "red", "silver", "gray", "grey", "green", "gold",
                 "truck", "pickup", "van", "suv", "car"}
        model_words = []
        for w in words:
            if w in stops:
                break
            model_words.append(w)
        model = " ".join(model_words[:3])
    return make, model


def answer_for(item, label: str) -> dict | None:
    """Built-in spec for one fluid: {spec, note, all, extra} or None.

    label is the display label (Rear differential, Transmission…). The saved spec
    is checked by the caller first — this is only for machines with nothing saved.
    """
    spec = spec_for(item)
    if not spec:
        return None
    key_map = {
        "Rear differential": "rear_diff",
        "Front differential": "front_diff",
        "Transmission": "transmission",
        "Transfer case": "transfer_case",
        "Coolant": "coolant",
        "Brake fluid": "brake_fluid",
        "Power steering": "power_steering",
    }
    # label may come through title-cased or exact; fall back on substring.
    key = key_map.get(label) or ""
    if not key:
        low = (label or "").lower()
        for k, v in key_map.items():
            if low in k.lower() or k.lower() in low:
                key = v
                break
    if key and spec.get(key):
        return {"spec": spec[key], "note": spec.get("note") or "", "extra": spec, "all": False}
    # Whole-card answer: they asked for everything the machine takes.
    return {"spec": "", "note": spec.get("note") or "", "extra": spec, "all": True}


def engine_oil_for(item) -> dict | None:
    """Built-in engine oil spec {needs, capacity, filter, interval_miles, interval_months, note}."""
    spec = spec_for(item)
    if not spec or not spec.get("needs"):
        return None
    return {
        "needs": spec["needs"],
        "capacity": spec.get("capacity") or "",
        "filter": spec.get("filter") or "",
        "interval_miles": spec.get("interval_miles") or "",
        "interval_months": spec.get("interval_months") or "",
        "interval_hours": spec.get("interval_hours") or "",
        "note": spec.get("note") or "",
    }


def fluids_overview_for(item) -> dict | None:
    """Everything the built-in table has on this machine, for the overview card."""
    return spec_for(item)
