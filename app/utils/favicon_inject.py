from __future__ import annotations

import os
import re

from flask import request, send_from_directory


FAVICON_LINKS = (
    '  <link rel="shortcut icon" href="{href}" type="image/jpeg">\n'
    '  <link rel="icon" href="{href}" type="image/jpeg">\n'
    '  <link rel="apple-touch-icon" href="{href}">\n'
)


def register_favicon(app) -> None:
    @app.route("/favicon.ico")
    def _favicon_ico():
        static = app.static_folder or "static"
        img_dir = os.path.join(static, "images")
        path = os.path.join(img_dir, "fav.jpg")
        if os.path.isfile(path):
            return send_from_directory(img_dir, "fav.jpg", mimetype="image/jpeg")
        return ("", 204)

    @app.after_request
    def _inject_favicon(response):
        try:
            if response.status_code != 200:
                return response
            ctype = (response.headers.get("Content-Type") or "").lower()
            if "text/html" not in ctype:
                return response
            data = response.get_data(as_text=True)
            if not data or "<head" not in data.lower():
                return response
            if re.search(r'rel=["\'](?:shortcut )?icon["\']', data, re.I):
                return response
            try:
                from flask import url_for

                href = url_for("static", filename="images/fav.jpg")
            except Exception:
                href = "/static/images/fav.jpg"
            inject = FAVICON_LINKS.format(href=href)
            new_data, n = re.subn(
                r"(<head[^>]*>)",
                r"\1\n" + inject,
                data,
                count=1,
                flags=re.I,
            )
            if n:
                response.set_data(new_data)
                if "Content-Length" in response.headers:
                    response.headers["Content-Length"] = str(len(response.get_data()))
        except Exception:
            pass
        return response
