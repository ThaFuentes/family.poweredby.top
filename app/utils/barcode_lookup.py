"""Product lookup across food, non-food, and general UPC catalogs.

Open Food Facts first is wrong for batteries and parts. We hit several
catalogs and pick the hit that matches the thing in your hand.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

import requests

from app.utils.classify import classify_product, classify_text
from app.utils.hot_cache import get as cache_get, put as cache_put

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

_EMPTY = {
    "ok": False,
    "barcode": "",
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
    "kind": "unknown",
    "kind_label": "Unknown",
    "suggested_type": "grocery",
}


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
        "source": full.get("source"),
        "kind": full.get("kind"),
        "kind_label": full.get("kind_label"),
        "suggested_type": full.get("suggested_type"),
        "quantity": full.get("quantity") or "",
    }


_UPC_TTL_HIT = 7 * 24 * 3600
_UPC_TTL_MISS = 30 * 60
_pool = None
_pool_lock = threading.Lock()


def _executor() -> ThreadPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=5, thread_name_prefix="upc")
        return _pool


def lookup_product(barcode: str) -> dict:
    code = (barcode or "").strip()
    out = dict(_EMPTY)
    out["barcode"] = code
    if not code or len(code) < 8 or not code.replace("-", "").isalnum():
        return out
    cached = cache_get(f"upc:{code}")
    if isinstance(cached, dict):
        return cached
    hits = []
    futs = [
        _executor().submit(fn, code)
        for fn in (
            _open_food_facts,
            _open_products_facts,
            _open_beauty_facts,
            _open_pet_facts,
            _upcitemdb,
        )
    ]
    for fut in as_completed(futs):
        try:
            hit = fut.result()
        except Exception:
            hit = {}
        if hit.get("ok") and (hit.get("name") or hit.get("brand")):
            hits.append(hit)
    best = _pick_hit(hits)
    if best:
        out.update({k: v for k, v in best.items() if v})
        out["ok"] = True
    facts = {}
    for key, _label in PRODUCT_FACT_LABELS:
        val = _s(out.get(key))
        if val and val.lower() not in _SKIP:
            facts[key] = val
    out["facts"] = facts
    out["size"] = out.get("quantity") or out.get("size") or ""
    guess = classify_product(out)
    out["kind"] = guess.get("kind")
    out["kind_label"] = guess.get("kind_label")
    out["suggested_type"] = guess.get("item_type") or "grocery"
    out["attach_to"] = guess.get("attach_to")
    out["location_hint"] = guess.get("location_hint")
    cache_put(f"upc:{code}", dict(out), _UPC_TTL_HIT if out.get("ok") else _UPC_TTL_MISS)
    return out


def _pick_hit(hits: list[dict]) -> dict | None:
    if not hits:
        return None
    scored = []
    for hit in hits:
        scored.append((_score_hit(hit), hit))
    scored.sort(key=lambda x: x[0], reverse=True)
    winner = dict(scored[0][1])
    # Fill gaps from runners-up without overwriting a better name.
    for _score, hit in scored[1:]:
        for k, v in hit.items():
            if v and not winner.get(k):
                winner[k] = v
    return winner


def _score_hit(hit: dict) -> int:
    name = _s(hit.get("name"))
    if not name:
        return 0
    score = 3
    if hit.get("brand"):
        score += 1
    if hit.get("image_url"):
        score += 1
    if hit.get("category"):
        score += 1
    if hit.get("ingredients"):
        score += 1
    hay = " ".join(
        _s(hit.get(k)) for k in ("name", "brand", "category", "ingredients")
    )
    kind = classify_text(hay)
    src = (hit.get("source") or "").lower()
    foodish = kind in ("food", "drink", "pet", "beauty", "household")
    partish = kind in (
        "car_battery",
        "aa_battery",
        "motor_oil",
        "filter",
        "auto_part",
        "mower",
        "tool",
        "equipment",
    )
    if foodish and src in ("openfoodfacts", "openpetfoodfacts", "openbeautyfacts"):
        score += 4
    if partish and src in ("openproductsfacts", "upcitemdb"):
        score += 5
    if partish and src == "openfoodfacts":
        score -= 3
    if kind == "unknown" and src == "upcitemdb":
        score += 2
    if kind == "unknown" and src == "openproductsfacts":
        score += 2
    return score


def _off_family(code: str, host: str, source: str) -> dict:
    url = f"https://{host}/api/v2/product/{code}.json"
    try:
        r = requests.get(url, timeout=7, headers=_UA)
        data = r.json() if r.ok else {}
    except Exception:
        return {}
    product = data.get("product") or {}
    if not product:
        return {}
    n = product.get("nutriments") or {}
    img = (
        product.get("image_front_small_url")
        or product.get("image_front_thumb_url")
        or product.get("image_small_url")
        or product.get("image_thumb_url")
        or product.get("image_front_url")
        or product.get("image_url")
        or ""
    )
    if isinstance(img, str) and img.startswith("//"):
        img = "https:" + img
    elif isinstance(img, str) and img.startswith("http://"):
        img = "https://" + img[7:]
    nova = product.get("nova_group")
    name = _s(product.get("product_name") or product.get("generic_name"))
    if not name:
        return {}
    return {
        "ok": True,
        "source": source,
        "name": name,
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


def _open_food_facts(code: str) -> dict:
    return _off_family(code, "world.openfoodfacts.org", "openfoodfacts")


def _open_products_facts(code: str) -> dict:
    return _off_family(code, "world.openproductsfacts.org", "openproductsfacts")


def _open_beauty_facts(code: str) -> dict:
    return _off_family(code, "world.openbeautyfacts.org", "openbeautyfacts")


def _open_pet_facts(code: str) -> dict:
    return _off_family(code, "world.openpetfoodfacts.org", "openpetfoodfacts")


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
    name = _s(it.get("title"))
    if not name:
        return {}
    return {
        "ok": True,
        "source": "upcitemdb",
        "name": name,
        "brand": _s(it.get("brand")),
        "category": _s(it.get("category")).split(">")[-1].strip(),
        "quantity": _s(it.get("size")),
        "ingredients": _s(it.get("description"))[:2000],
        "image_url": (
            ("https://" + images[0][7:] if str(images[0]).startswith("http://") else images[0])
            if images
            else ""
        ),
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
        from app.utils.thumbs import https_url

        g.image_url = https_url(str(lookup["image_url"])) or str(lookup["image_url"])[:500]
    extra = dict(g.extra_data or {})
    facts = lookup.get("facts") or {}
    if facts:
        extra["product"] = facts
        extra["product_source"] = lookup.get("source")
    if lookup.get("kind"):
        extra["kind"] = str(lookup["kind"])[:40]
        extra["kind_label"] = str(lookup.get("kind_label") or "")[:80]
    loc = lookup.get("location_hint")
    if loc and not g.default_location:
        g.default_location = str(loc)[:80]
    g.extra_data = extra
    if lookup.get("category") and item is not None and not item.category:
        item.category = str(lookup["category"])[:100]
    if lookup.get("name") and item is not None and (not item.name or item.name.startswith("Scanned ")):
        item.name = str(lookup["name"])[:200]
    if lookup.get("suggested_type") and item is not None and item.item_type == "grocery":
        # Keep grocery for consumable car parts; only retag true tools if still a stub.
        pass
