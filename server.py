"""Social accounts dashboard: serves the built page (web/dist) and its data at /api/social.

    python3 server.py            # http://127.0.0.1:8080; opening the page refreshes the data once per day
    python3 server.py --refresh  # one refresh now (billed by Apify), then exit
"""
import json
import os
import secrets
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import social_stats

DIST_DIR = os.path.join(social_stats.BASE_DIR, "web", "dist")
PORT = int(os.environ.get("PORT") or 8080)
_oauth_states = {}  # one-use CSRF value -> platform, handed to the platform's authorize page


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIST_DIR, **kwargs)

    def _redirect(self, url: str) -> None:
        self.send_response(302)
        self.send_header("Location", url)
        self.end_headers()

    def do_GET(self):
        path, query = self.path.split("?")[0], parse_qs(urlsplit(self.path).query)
        platform = path.removeprefix("/api/connect/").removesuffix("/callback")
        if path.startswith("/api/connect/") and platform in social_stats.CONNECTORS:
            configured, authorize_url, connect = social_stats.CONNECTORS[platform]
            if not path.endswith("/callback"):
                if not configured():
                    return self.send_error(503, f"{platform.upper()}_APP_ID / _APP_SECRET / _REDIRECT_URI not set (.env)")
                state = secrets.token_urlsafe(16)
                _oauth_states[state] = platform
                return self._redirect(authorize_url(state))
            if _oauth_states.pop(query.get("state", [""])[0], None) != platform:
                return self.send_error(400, "Unknown or reused OAuth state")
            if "code" not in query:
                return self.send_error(400, query.get("error_description", ["Authorization was not granted"])[0])
            try:
                connect(query["code"][0])
            except Exception as e:
                return self.send_error(502, f"{platform} connect failed: {str(e)[:200]}")
            return self._redirect(f"/?platform={platform}")
        if path == "/api/social":
            social_stats.refresh_if_stale()
            body = json.dumps({"success": True, **social_stats.snapshot()}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


def main() -> None:
    if "--refresh" in sys.argv:
        if not social_stats.can_refresh():
            sys.exit("Connect an account (official API) or set APIFY_TOKEN (.env) first")
        social_stats.refresh()
        print(f"Refreshed, saved to {social_stats.CACHE_FILE}")
        return
    print(f"Dashboard: http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
