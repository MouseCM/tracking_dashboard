import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import urlopen

import server
import social_stats

ACCOUNTS = [{"group": 1, "name": "Acc", "email": "a@x.test", "note": "",
             "links": {"tiktok": "https://www.tiktok.com/@acc", "instagram": "https://www.instagram.com/acc/",
                       "threads": "https://www.threads.net/@acc", "facebook": "", "youtube": ""}}]

FAKE = {
    "apify~instagram-profile-scraper": [{"username": "acc", "followersCount": 1200, "postsCount": 34, "latestPosts": [
        {"url": "https://www.instagram.com/p/A/", "timestamp": "2026-10-20T10:00:00.000Z", "type": "Video",
         "likesCount": 50, "commentsCount": 4, "videoPlayCount": 900, "caption": "ring"}]}],
    "clockworks~tiktok-scraper": [{"webVideoUrl": "https://www.tiktok.com/@acc/video/1", "createTime": 1761000000,
                                   "playCount": 5000, "diggCount": 300, "commentCount": 12, "shareCount": 7,
                                   "authorMeta": {"fans": 800, "video": 15}}],
}


def setup(tmp_path, monkeypatch):
    accounts = tmp_path / "accounts.json"
    accounts.write_text(json.dumps(ACCOUNTS))
    monkeypatch.setattr(social_stats, "ACCOUNTS_FILE", str(accounts))
    monkeypatch.setattr(social_stats, "CACHE_FILE", str(tmp_path / "cache.json"))
    monkeypatch.setattr(social_stats, "TOKENS_FILE", str(tmp_path / "tokens.json"))
    monkeypatch.setattr(social_stats, "_run", lambda actor, payload: FAKE[actor])
    monkeypatch.setattr(social_stats, "APIFY_TOKEN", "t")
    monkeypatch.setattr(social_stats, "_last_attempt", None)


def test_refresh_normalises_each_platform(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    assert social_stats.snapshot()["accounts"][0]["platforms"]["instagram"]["status"] == "pending"
    assert social_stats.refresh()

    p = social_stats.snapshot()["accounts"][0]["platforms"]
    assert (p["instagram"]["followers"], p["instagram"]["posts_count"]) == (1200, 34)
    assert p["instagram"]["posts"][0] == {"url": "https://www.instagram.com/p/A/", "time": "2026-10-20T10:00:00.000Z",
                                          "caption": "ring", "type": "Video", "views": 900, "likes": 50,
                                          "comments": 4, "shares": None}
    assert (p["tiktok"]["followers"], p["tiktok"]["posts"][0]["views"], p["tiktok"]["posts"][0]["shares"]) == (800, 5000, 7)
    assert p["tiktok"]["posts"][0]["time"].startswith("2025-10-20")
    assert (p["threads"]["status"], p["facebook"]["status"]) == ("unsupported", "no_link")


def test_failing_account_is_marked_not_fatal(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    def boom(actor, payload):
        if actor.startswith("clockworks"):
            raise RuntimeError("blocked")
        return FAKE[actor]
    monkeypatch.setattr(social_stats, "_run", boom)
    social_stats.refresh()
    p = social_stats.snapshot()["accounts"][0]["platforms"]
    assert (p["tiktok"]["status"], p["tiktok"]["error"], p["instagram"]["status"]) == ("error", "blocked", "ok")


def test_server_serves_snapshot(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with urlopen(f"http://127.0.0.1:{httpd.server_port}/api/social") as resp:
            assert json.load(resp)["accounts"][0]["name"] == "Acc"
    finally:
        httpd.shutdown()


def test_refresh_only_once_per_day_when_opened(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    setup(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(social_stats, "_refresh_locked", lambda: calls.append(1))
    monkeypatch.setattr(social_stats.threading, "Thread", lambda target, daemon: type("T", (), {"start": lambda self: target()})())
    cache = tmp_path / "cache.json"

    # Data from today: opening the page costs nothing.
    cache.write_text(json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat()}))
    social_stats.refresh_if_stale()
    assert calls == []

    # Data from yesterday: the first open refreshes, later opens the same day do not, even if that refresh wrote nothing.
    cache.write_text(json.dumps({"fetched_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()}))
    social_stats.refresh_if_stale()
    social_stats.refresh_if_stale()
    assert calls == [1]
    assert not social_stats._refresh_lock.locked()

    # No token: never refresh.
    monkeypatch.setattr(social_stats, "_last_attempt", None)
    monkeypatch.setattr(social_stats, "APIFY_TOKEN", "")
    social_stats.refresh_if_stale()
    assert calls == [1]


def test_instagram_connect_then_fetch_uses_official_api(tmp_path, monkeypatch):
    import os
    from urllib.parse import parse_qs, urlsplit
    setup(tmp_path, monkeypatch)
    monkeypatch.setattr(social_stats, "IG_APP_SECRET", "s")
    calls = []

    def fake_http(url, form=None):
        calls.append(url)
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        path = urlsplit(url).path
        if path == "/oauth/access_token":
            return {"data": [{"access_token": "short", "user_id": "1"}]}
        if path == "/access_token":
            assert q["access_token"] == "short"
            return {"access_token": "long", "expires_in": 5184000}
        assert q["access_token"] == "long"
        if path.endswith("/me") and q["fields"] == "username":
            return {"username": "Acc"}
        if path.endswith("/me"):
            return {"followers_count": 1500, "media_count": 40}
        if path.endswith("/me/media"):
            return {"data": [{"id": "m1", "permalink": "https://www.instagram.com/p/B/", "timestamp": "2026-10-21T08:00:00+0000",
                              "media_type": "VIDEO", "like_count": 70, "comments_count": 5, "caption": "api"}]}
        if path.endswith("/m1/insights"):
            return {"data": [{"name": "views", "values": [{"value": 1234}]}]}
        raise AssertionError(url)

    monkeypatch.setattr(social_stats, "_http_json", fake_http)
    assert social_stats.snapshot()["accounts"][0]["platforms"]["instagram"]["connected"] is False
    assert social_stats.connect_instagram("code") == "Acc"
    assert os.stat(tmp_path / "tokens.json").st_mode & 0o077 == 0  # token file is owner-only

    social_stats.refresh()
    ig = social_stats.snapshot()["accounts"][0]["platforms"]["instagram"]
    assert (ig["connected"], ig["followers"], ig["posts_count"]) == (True, 1500, 40)
    assert ig["posts"][0] == {"url": "https://www.instagram.com/p/B/", "time": "2026-10-21T08:00:00+00:00", "caption": "api",
                              "type": "VIDEO", "views": 1234, "likes": 70, "comments": 5, "shares": None}
    assert not any("refresh_access_token" in c for c in calls)  # 60-day token is not refreshed early


def test_instagram_callback_rejects_unknown_state(tmp_path, monkeypatch):
    from urllib.error import HTTPError
    setup(tmp_path, monkeypatch)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        urlopen(f"http://127.0.0.1:{httpd.server_port}/api/connect/instagram/callback?code=x&state=forged")
        assert False, "forged state accepted"
    except HTTPError as e:
        assert e.code == 400
    finally:
        httpd.shutdown()


def test_apify_is_last_resort(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    social_stats._save_tokens({"acc": {"access_token": "tok", "expires_at": "2099-01-01T00:00:00+00:00"}})
    def revoked(url, form=None):
        raise RuntimeError("Error validating access token")
    monkeypatch.setattr(social_stats, "_http_json", revoked)

    # API fails, Apify token present: the scraper fills in and the API error is kept.
    ig = social_stats._fetch_one("instagram", "https://www.instagram.com/acc/")
    assert (ig["status"], ig["followers"], ig["api_error"]) == ("ok", 1200, "Error validating access token")

    # No Apify token: nothing billed, the API error is shown; refreshing still works off the stored token.
    monkeypatch.setattr(social_stats, "APIFY_TOKEN", "")
    monkeypatch.setattr(social_stats, "_run", lambda actor, payload: (_ for _ in ()).throw(AssertionError("billed")))
    ig = social_stats._fetch_one("instagram", "https://www.instagram.com/acc/")
    assert (ig["status"], ig["error"]) == ("error", "Error validating access token")
    assert social_stats.can_refresh()


def test_facebook_pages_connect_then_fetch_uses_official_api(tmp_path, monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    setup(tmp_path, monkeypatch)

    def fake_http(url, form=None):
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        path = urlsplit(url).path
        if path.endswith("/oauth/access_token"):
            return {"access_token": "long" if q.get("grant_type") == "fb_exchange_token" else "short"}
        if path.endswith("/me/accounts"):
            assert q["access_token"] == "long"
            return {"data": [{"id": "615", "name": "Shop", "link": "https://www.facebook.com/profile.php?id=615", "access_token": "pt"},
                             {"id": "777", "name": "Other", "link": "https://www.facebook.com/otherpage", "access_token": "pt2"}]}
        assert q["access_token"] in ("pt", "pt2")
        if path.endswith("/615"):
            return {"followers_count": 321}
        if path.endswith("/615/posts"):
            return {"data": [{"permalink_url": "https://www.facebook.com/615/posts/1", "created_time": "2026-10-22T09:00:00+0000",
                              "message": "new ring", "reactions": {"summary": {"total_count": 9}},
                              "comments": {"summary": {"total_count": 2}}}]}
        raise AssertionError(url)

    monkeypatch.setattr(social_stats, "_http_json", fake_http)
    monkeypatch.setattr(social_stats, "_run", lambda actor, payload: (_ for _ in ()).throw(AssertionError("billed")))
    assert social_stats.connect_facebook("code") == "Shop, Other"

    fb = social_stats._fetch_one("facebook", "https://www.facebook.com/profile.php?id=615")
    assert (fb["status"], fb["followers"], fb["posts_count"]) == ("ok", 321, 1)
    assert fb["posts"][0] == {"url": "https://www.facebook.com/615/posts/1", "time": "2026-10-22T09:00:00+00:00",
                              "caption": "new ring", "type": "", "views": None, "likes": 9, "comments": 2, "shares": 0}
    tokens = social_stats._load_tokens()
    assert social_stats._facebook_page("https://www.facebook.com/otherpage/", tokens) == "777"
    assert social_stats._facebook_page("https://www.facebook.com/share/1MRFj6XiuS/", tokens) is None  # falls back to Apify
