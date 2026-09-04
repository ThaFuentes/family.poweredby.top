"""Product lookup: Open Food Facts, then UPCItemDB trial. Best-effort; never blocks scan."""
from __future__ import annotations

import requests

_UA = {"User-Agent": "family.poweredby.top/1.0 (household OS)"}
_SKIP = {"", "unknown", "n/a", "null", "none"}

PRODUCT_FACT_LABELS = (
    ("name", "Name"),
    ("brand", "Brand"),
    ("quantity", "Size"),
    ("serving_size", "Serving"),
    ("packaging", "Packaging"),
    ("category", "Category"),
    ("labels", "Labels"),
    ("ingredients", "Ingredients"),
    ("allergens", "Allergens"),
    ("traces", "Traces"),
    ("nutriscore", "Nutri-Score"),
    ("nova", "NOVA"),
    ("origins", "Origins"),
    ("made_in", "Made in"),
    ("stores", "Stores"),
    ("energy_kcal", "kcal / 100g"),
    ("fat", "Fat / 100g"),
    ("saturated_fat", "Sat. fat / 100g"),
    ("carbs", "Carbs / 100g"),
    ("sugars", "Sugars / 100g"),
    ("fiber", "Fiber / 100g"),
    ("protein", "Protein / 100g"),
    ("salt", "Salt / 100g"),
)


def _s(v) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        v = ", ".join(str(x) for x in v if x)
    return str(v).strip()


def _nut(n: dict, key: str) -> str:
    val = n.get(key)
    if val is None:
        return ""
    try:
        return str(round(float(val), 2)).rstrip("0").rstrip(".")
    except Exception:
        return str(val)


def lookup_upc(barcode: str) -> dict:
    """Back-compat wrapper used by create-item and scan."""
    full = lookup_product(barcode)
    return {
        "barcode": full.get("barcode") or barcode,
        "name": full.get("name") or "",
        "brand": full.get("brand") or "",
        "category": full.get("category") or "",
        "size": full.get("quantity") or full.get("size") or "",
        "image_url": full.get("image_url") or "",
        "ingredients": full.get("ingredients") or "",
        "allergens": full.get("allergens") or "",
        "serving_size": full.get("serving_size") or "",
        "packaging": full.get("packaging") or "",
        "facts": full.get("facts") or {},
        "ok": full.get("ok"),
    }


def lookup_product(barcode: str) -> dict:
    code = (barcode or "").strip()
    out = {
        "ok": False,
        "barcode": code,
        "name": "",
        "brand": "",
        "category": "",
        "quantity": "",
        "size": "",
        "serving_size": "",
        "packaging": "",
        "ingredients": "",
        "allergens": "",
        "traces": "",
        "labels": "",
        "image_url": "",
        "origins": "",
        "made_in": "",
        "stores": "",
        "nutriscore": "",
        "nova": "",
        "energy_kcal": "",
        "fat": "",
        "saturated_fat": "",
        "carbs": "",
        "sugars": "",
        "fiber": "",
        "protein": "",
        "salt": "",
        "facts": {},
        "source": None,
    }
    if not code or len(code) < 8:
        return out
    off = _open_food_facts(code)
    if off.get("ok"):
        out.update({k: v for k, v in off.items() if v})
        out["ok"] = True
        out["source"] = "openfoodfacts"
    upc = _upcitemdb(code)
    if upc.get("ok"):
        for k, v in upc.items():
            if v and not out.get(k):
                out[k] = v
        out["ok"] = True
        if not out.get("source"):
            out["source"] = "upcitemdb"
    facts = {}
    for key, _label in PRODUCT_FACT_LABELS:
        val = _s(out.get(key))
        if val and val.lower() not in _SKIP:
            facts[key] = val
    out["facts"] = facts
    out["size"] = out.get("quantity") or out.get("size") or ""
    return out


def _open_food_facts(code: str) -> dict:
    url = f"https://world.openfoodfacts.org/api/v2/product/{code}.json"
    try:
        r = requests.get(url, timeout=8, headers=_UA)
        data = r.json() if r.ok else {}
    except Exception:
        return {}
    product = data.get("product") or {}
    if not product:
        return {}
    n = product.get("nutriments") or {}
    img = (
        product.get("image_front_url")
        or product.get("image_url")
        or product.get("image_small_url")
        or ""
    )
    nova = product.get("nova_group")
    return {
        "ok": True,
        "name": _s(product.get("product_name") or product.get("generic_name")),
        "brand": _s(product.get("brands")).split(",")[0].strip(),
        "category": _s(product.get("categories")).split(",")[0].strip(),
        "quantity": _s(product.get("quantity")),
        "serving_size": _s(product.get("serving_size")),
        "packaging": _s(product.get("packaging")),
        "ingredients": _s(product.get("ingredients_text")),
        "allergens": _s(product.get("allergens") or product.get("allergens_tags")),
        "traces": _s(product.get("traces")),
        "labels": _s(product.get("labels")),
        "image_url": img,
        "origins": _s(product.get("origins")),
        "made_in": _s(product.get("manufacturing_places")),
        "stores": _s(product.get("stores")),
        "nutriscore": _s(product.get("nutriscore_grade")).upper(),
        "nova": str(nova) if nova else "",
        "energy_kcal": _nut(n, "energy-kcal_100g") or _nut(n, "energy-kcal"),
        "fat": _nut(n, "fat_100g"),
        "saturated_fat": _nut(n, "saturated-fat_100g"),
        "carbs": _nut(n, "carbohydrates_100g"),
        "sugars": _nut(n, "sugars_100g"),
        "fiber": _nut(n, "fiber_100g"),
        "protein": _nut(n, "proteins_100g"),
        "salt": _nut(n, "salt_100g"),
    }


def _upcitemdb(code: str) -> dict:
    url = "https://api.upcitemdb.com/prod/trial/lookup"
    try:
        r = requests.get(url, params={"upc": code}, timeout=6, headers=_UA)
        data = r.json() if r.ok else {}
    except Exception:
        return {}
    items = data.get("items") or []
    if not items:
        return {}
    it = items[0]
    images = it.get("images") or []
    return {
        "ok": True,
        "name": _s(it.get("title")),
        "brand": _s(it.get("brand")),
        "category": _s(it.get("category")).split(">")[-1].strip(),
        "quantity": _s(it.get("size")),
        "ingredients": _s(it.get("description"))[:2000],
        "image_url": images[0] if images else "",
    }


def apply_product_lookup(g, item, lookup: dict) -> None:
    """Write lookup fields onto grocery + item. Safe if lookup is empty."""
    if not lookup:
        return
    if lookup.get("brand") and not g.brand:
        g.brand = str(lookup["brand"])[:120]
    size = lookup.get("quantity") or lookup.get("size")
    if size and not g.size:
        g.size = str(size)[:80]
    if lookup.get("ingredients"):
        g.ingredients = str(lookup["ingredients"])[:8000]
    if lookup.get("allergens"):
        g.allergens = str(lookup["allergens"])[:500]
    if lookup.get("serving_size"):
        g.serving_size = str(lookup["serving_size"])[:80]
    if lookup.get("packaging"):
        g.packaging = str(lookup["packaging"])[:200]
    if lookup.get("image_url"):
        g.image_url = str(lookup["image_url"])[:500]
    extra = dict(g.extra_data or {})
    facts = lookup.get("facts") or {}
    if facts:
        extra["product"] = facts
        extra["product_source"] = lookup.get("source")
        g.extra_data = extra
    if lookup.get("category") and item is not None and not item.category:
        item.category = str(lookup["category"])[:100]
    if lookup.get("name") and item is not None and (not item.name or item.name.startswith("Scanned ")):
        item.name = str(lookup["name"])[:200]
