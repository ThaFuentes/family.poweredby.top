"""UPC lookup via Open Food Facts. Best-effort; never blocks scan."""
from __future__ import annotations

import requests


def lookup_upc(barcode: str) -> dict:
    code = (barcode or "").strip()
    out = {"barcode": code, "name": "", "brand": "", "category": "", "size": ""}
    if not code or not code.isdigit() or len(code) < 8:
        return out
    url = f"https://world.openfoodfacts.org/api/v2/product/{code}.json"
    try:
        r = requests.get(url, timeout=4, headers={"User-Agent": "family.poweredby.top/1.0"})
        data = r.json() if r.ok else {}
        product = data.get("product") or {}
        out["name"] = (
            product.get("product_name")
            or product.get("generic_name")
            or ""
        )
        out["brand"] = (product.get("brands") or "").split(",")[0].strip()
        cats = product.get("categories") or ""
        out["category"] = cats.split(",")[0].strip() if cats else ""
        out["size"] = product.get("quantity") or ""
    except Exception:
        pass
    return out
