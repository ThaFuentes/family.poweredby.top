from flask import current_app, jsonify, make_response, url_for


def register_pwa(app) -> None:
    @app.route("/manifest.webmanifest")
    def _manifest():
        icon = url_for("static", filename="images/pwa-192.png")
        icon512 = url_for("static", filename="images/pwa-512.png")
        data = {
            "name": "Family OS",
            "short_name": "Family",
            "description": "Household operating system — scan, stock, maintain.",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#f4efe6",
            "theme_color": "#2f5d3a",
            "icons": [
                {"src": icon, "sizes": "192x192", "type": "image/png"},
                {"src": icon512, "sizes": "512x512", "type": "image/png"},
            ],
        }
        resp = jsonify(data)
        resp.headers["Content-Type"] = "application/manifest+json"
        return resp

    @app.route("/sw.js")
    def _sw():
        body = (
            "self.addEventListener('install', e => self.skipWaiting());\n"
            "self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));\n"
        )
        resp = make_response(body)
        resp.headers["Content-Type"] = "application/javascript"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    snippet = """
  <meta name="theme-color" content="#2f5d3a">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <link rel="manifest" href="/manifest.webmanifest">
"""

    @app.after_request
    def _inject_pwa(response):
        try:
            if response.status_code != 200:
                return response
            ctype = (response.headers.get("Content-Type") or "").lower()
            if "text/html" not in ctype:
                return response
            data = response.get_data(as_text=True)
            if not data or "manifest.webmanifest" in data:
                return response
            if "<head" not in data.lower():
                return response
            import re

            new_data, n = re.subn(
                r"(<head[^>]*>)",
                r"\1\n" + snippet,
                data,
                count=1,
                flags=re.I,
            )
            if n:
                response.set_data(new_data)
        except Exception:
            pass
        return response
