import io
import os
from flask import current_app

try:
    import qrcode
except Exception:
    qrcode = None


def item_payload(household_id: int, item_id: int) -> str:
    return f"FAM:{household_id}:{item_id}"


def ensure_item_barcode(item) -> str:
    if item.barcode:
        return item.barcode
    item.barcode = item_payload(item.household_id, item.id)
    return item.barcode


def qr_png_response(payload: str, filename: str = "qr.png"):
    if qrcode is None:
        return ("qrcode package missing", 500)
    img = qrcode.make(payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    from app.utils.crypto import send_bytes

    return send_bytes(buf.getvalue(), "image/png", filename)
