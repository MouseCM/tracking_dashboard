"""Public stats (followers, posts, per-post views/likes/comments) for the social accounts, via Apify scrapers.

The account list lives in data/accounts.json (links only, never passwords). A refresh runs one Apify actor per
account and platform and caches the normalised result as JSON; the dashboard only reads that cache.
"""
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_env() -> None:
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


_load_env()
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")
ACCOUNTS_FILE = os.path.join(BASE_DIR, "data", "accounts.json")
CACHE_FILE = os.path.join(BASE_DIR, "data", "social_stats.json")
TOKENS_FILE = os.path.join(BASE_DIR, "data", "tokens.json")  # OAuth tokens: Instagram username / "facebook:<page id>"; gitignored, mode 0600
# Instagram API with Instagram Login (Business/Creator accounts): https://developers.facebook.com/docs/instagram-platform/
IG_APP_ID = os.environ.get("INSTAGRAM_APP_ID", "")
IG_APP_SECRET = os.environ.get("INSTAGRAM_APP_SECRET", "")
IG_REDIRECT_URI = os.environ.get("INSTAGRAM_REDIRECT_URI", "")
IG_GRAPH = "https://graph.instagram.com/v21.0"
# Facebook Login + Pages API (Pages you manage): https://developers.facebook.com/docs/pages-api/
FB_APP_ID = os.environ.get("FACEBOOK_APP_ID", "")
FB_APP_SECRET = os.environ.get("FACEBOOK_APP_SECRET", "")
FB_REDIRECT_URI = os.environ.get("FACEBOOK_REDIRECT_URI", "")
FB_GRAPH = "https://graph.facebook.com/v21.0"
PLATFORMS = ("tiktok", "instagram", "threads", "facebook", "youtube")
POSTS_PER_ACCOUNT = 20
_refresh_lock = threading.Lock()
_last_attempt: Optional[date] = None  # day of the last refresh_if_stale attempt
_tokens_lock = threading.Lock()


def _num(d: Dict[str, Any], *keys: str) -> Optional[int]:
    """First numeric value among keys; dotted keys reach into nested dicts. Scrapers rename fields between versions."""
    for key in keys:
        v: Any = d
        for part in key.split("."):
            v = v.get(part) if isinstance(v, dict) else None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return int(v)
    return None


def _iso(v: Any) -> Optional[str]:
    if isinstance(v, (int, float)) and v > 0:
        return datetime.fromtimestamp(v, tz=timezone.utc).isoformat()
    return v if isinstance(v, str) and v else None


def _handle(url: str) -> str:
    return urlsplit(url).path.strip("/").split("/")[0].lstrip("@")


def _run(actor: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Apify scraper: billed, so only the last resort when no free official API covers the account."""
    if not APIFY_TOKEN:
        raise RuntimeError("Chưa kết nối API miễn phí và không có APIFY_TOKEN")
    req = Request(f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items", data=json.dumps(payload).encode(),
                  headers={"Authorization": f"Bearer {APIFY_TOKEN}", "Content-Type": "application/json"})
    with urlopen(req, timeout=330) as resp:  # raises HTTPError on 4xx/5xx
        return [i for i in json.load(resp) if isinstance(i, dict) and not i.get("error")]


def _post(url: Any, time: Any, caption: Any, views: Optional[int], likes: Optional[int],
          comments: Optional[int], shares: Optional[int] = None, kind: str = "") -> Dict[str, Any]:
    return {"url": url or "", "time": _iso(time), "caption": (caption or "")[:140], "type": kind,
            "views": views, "likes": likes, "comments": comments, "shares": shares}


def _http_json(url: str, form: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    try:
        with urlopen(Request(url, data=urlencode(form).encode() if form else None), timeout=60) as resp:
            return json.load(resp)
    except HTTPError as e:  # surface Meta's message ("token expired", "permission missing") instead of "HTTP 400"
        try:
            body = json.load(e)
        except ValueError:
            raise RuntimeError(str(e)) from None
        raise RuntimeError((body.get("error") or {}).get("message") or body.get("error_message") or str(e)) from None


def _graph(path: str, token: str, base: str = IG_GRAPH, **params: Any) -> Dict[str, Any]:
    return _http_json(f"{base}/{path}?" + urlencode({**params, "access_token": token}))


def _meta_time(ts: Optional[str]) -> Optional[str]:
    return ts and datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z").isoformat()  # Meta sends "+0000"


def _free_first(free: Callable[[], Optional[Dict[str, Any]]], scraper: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    """The free official API when the account is connected (free() returns None when it is not); the billed scraper
    only as the last resort. An API failure falls back to the scraper and keeps the reason as api_error."""
    try:
        data = free()
        if data is not None:
            return data
        api_error = None
    except RuntimeError as e:  # revoked/expired token or API outage
        api_error = str(e)[:200]
    if api_error and not APIFY_TOKEN:
        raise RuntimeError(api_error)
    data = scraper()
    return {**data, "api_error": api_error} if api_error else data


def _load_tokens() -> Dict[str, Any]:
    try:
        with open(TOKENS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_tokens(tokens: Dict[str, Any]) -> None:
    tmp = TOKENS_FILE + ".tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
        json.dump(tokens, f)
    os.replace(tmp, TOKENS_FILE)


def _store_token(username: str, resp: Dict[str, Any]) -> None:
    expires = datetime.now(timezone.utc).timestamp() + int(resp.get("expires_in") or 0)
    with _tokens_lock:
        tokens = _load_tokens()
        tokens[username.lower()] = {"access_token": resp["access_token"], "expires_at": _iso(expires)}
        _save_tokens(tokens)


def can_refresh() -> bool:
    """A free API token or the Apify token: something to fetch with."""
    return bool(APIFY_TOKEN or _load_tokens())


def instagram_connect_configured() -> bool:
    return bool(IG_APP_ID and IG_APP_SECRET and IG_REDIRECT_URI)


def facebook_connect_configured() -> bool:
    return bool(FB_APP_ID and FB_APP_SECRET and FB_REDIRECT_URI)


def instagram_authorize_url(state: str) -> str:
    return "https://www.instagram.com/oauth/authorize?" + urlencode({
        "client_id": IG_APP_ID, "redirect_uri": IG_REDIRECT_URI, "response_type": "code", "state": state,
        "scope": "instagram_business_basic,instagram_business_manage_insights"})


def connect_instagram(code: str) -> str:
    """Swap the OAuth code for a 60-day token, store it under the account's username and return that username."""
    short = _http_json("https://api.instagram.com/oauth/access_token", {
        "client_id": IG_APP_ID, "client_secret": IG_APP_SECRET, "grant_type": "authorization_code",
        "redirect_uri": IG_REDIRECT_URI, "code": code})
    short = (short.get("data") or [short])[0]  # documented as {"data": [...]}, observed flat
    long = _http_json("https://graph.instagram.com/access_token?" + urlencode({
        "grant_type": "ig_exchange_token", "client_secret": IG_APP_SECRET, "access_token": short["access_token"]}))
    username = _graph("me", long["access_token"], fields="username")["username"]
    _store_token(username, long)
    return username


def _instagram_token(handle: str) -> Optional[str]:
    """The stored token for this username, refreshed when it expires within a week (long-lived tokens last 60 days)."""
    tok = _load_tokens().get(handle.lower())
    if not tok:
        return None
    if datetime.fromisoformat(tok["expires_at"]).timestamp() - datetime.now(timezone.utc).timestamp() < 7 * 86400:
        resp = _http_json("https://graph.instagram.com/refresh_access_token?" + urlencode({
            "grant_type": "ig_refresh_token", "access_token": tok["access_token"]}))
        _store_token(handle, resp)
        return resp["access_token"]
    return tok["access_token"]


def facebook_authorize_url(state: str) -> str:
    return "https://www.facebook.com/v21.0/dialog/oauth?" + urlencode({
        "client_id": FB_APP_ID, "redirect_uri": FB_REDIRECT_URI, "response_type": "code", "state": state,
        "scope": "pages_show_list,pages_read_engagement"})


def connect_facebook(code: str) -> str:
    """Swap the OAuth code for a long-lived user token and store a Page token for every Page that user manages.
    Page tokens derived from a long-lived user token do not expire (until the user revokes the app)."""
    creds = {"client_id": FB_APP_ID, "client_secret": FB_APP_SECRET}
    short = _http_json(f"{FB_GRAPH}/oauth/access_token?" + urlencode({**creds, "redirect_uri": FB_REDIRECT_URI, "code": code}))
    long = _http_json(f"{FB_GRAPH}/oauth/access_token?" + urlencode({
        **creds, "grant_type": "fb_exchange_token", "fb_exchange_token": short["access_token"]}))
    pages = _graph("me/accounts", long["access_token"], FB_GRAPH, fields="id,name,link,access_token", limit=100).get("data") or []
    if not pages:
        raise RuntimeError("No Facebook Page granted (only Pages can be connected, not personal profiles)")
    with _tokens_lock:
        tokens = _load_tokens()
        for pg in pages:
            tokens[f"facebook:{pg['id']}"] = {"access_token": pg["access_token"], "name": pg.get("name", ""), "link": pg.get("link", "")}
        _save_tokens(tokens)
    return ", ".join(pg.get("name", pg["id"]) for pg in pages)


def _facebook_page(url: str, tokens: Dict[str, Any]) -> Optional[str]:
    """Page id of a connected Page matching this link: profile.php?id=<id>, or a vanity link equal to the Page's.
    shortcut: /share/... links cannot be matched; replace them with the Page's direct link in accounts.json."""
    page_id = parse_qs(urlsplit(url).query).get("id", [""])[0]
    for key, tok in tokens.items():
        if not key.startswith("facebook:"):
            continue
        pid = key.split(":", 1)[1]
        if pid == page_id or (not page_id and _handle(url) not in ("share", "profile.php") and _handle(tok["link"]) == _handle(url)):
            return pid
    return None


def fetch_facebook_api(page_id: str, token: str) -> Dict[str, Any]:
    page = _graph(page_id, token, FB_GRAPH, fields="followers_count,fan_count")
    items = _graph(f"{page_id}/posts", token, FB_GRAPH, limit=POSTS_PER_ACCOUNT,
                   fields="permalink_url,created_time,message,shares,"
                          "reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0)").get("data") or []
    # shortcut: no views; Page post views need per-post insights (read_insights), add when needed.
    posts = [_post(x.get("permalink_url"), _meta_time(x.get("created_time")), x.get("message"), None,
                   _num(x, "reactions.summary.total_count"), _num(x, "comments.summary.total_count"),
                   _num(x, "shares.count") or 0)  # "shares" is absent when there are none
             for x in items]
    # shortcut: the posts count is only the latest posts fetched (≤ POSTS_PER_ACCOUNT); the API exposes no total.
    return {"followers": _num(page, "followers_count", "fan_count"), "posts_count": len(posts), "posts": posts}


def _ig_views(media_id: str, token: str) -> Optional[int]:
    try:
        data = _graph(f"{media_id}/insights", token, metric="views").get("data") or []
        return _num((data[0].get("values") or [{}])[0], "value") if data else None
    except RuntimeError:  # some media types have no views insight
        return None


def fetch_instagram_api(token: str) -> Dict[str, Any]:
    me = _graph("me", token, fields="followers_count,media_count")
    media = _graph("me/media", token, limit=POSTS_PER_ACCOUNT,
                   fields="id,caption,media_type,permalink,timestamp,like_count,comments_count").get("data") or []
    posts = [_post(m.get("permalink"), _meta_time(m.get("timestamp")), m.get("caption"), _ig_views(m["id"], token), _num(m, "like_count"), _num(m, "comments_count"),
                   kind=m.get("media_type", ""))
             for m in media]
    return {"followers": _num(me, "followers_count"), "posts_count": _num(me, "media_count"), "posts": posts}


def _instagram_free(url: str) -> Optional[Dict[str, Any]]:
    token = _instagram_token(_handle(url))
    return fetch_instagram_api(token) if token else None


def fetch_instagram(url: str) -> Dict[str, Any]:
    return _free_first(lambda: _instagram_free(url), lambda: _scrape_instagram(url))


def _scrape_instagram(url: str) -> Dict[str, Any]:
    items = _run("apify~instagram-profile-scraper", {"usernames": [_handle(url)]})
    if not items:
        return {"error": "Không tìm thấy tài khoản"}
    p = items[0]
    posts = [_post(x.get("url"), x.get("timestamp"), x.get("caption"),
                   _num(x, "videoPlayCount", "videoViewCount"), _num(x, "likesCount"), _num(x, "commentsCount"),
                   kind=x.get("type", ""))
             for x in p.get("latestPosts") or []]
    return {"followers": _num(p, "followersCount"), "posts_count": _num(p, "postsCount"), "posts": posts}


def fetch_tiktok(url: str) -> Dict[str, Any]:
    items = _run("clockworks~tiktok-scraper", {"profiles": [_handle(url)], "resultsPerPage": POSTS_PER_ACCOUNT,
                                                "shouldDownloadVideos": False, "shouldDownloadCovers": False})
    if not items:
        return {"error": "Không tìm thấy tài khoản hoặc chưa có video"}
    author = items[0].get("authorMeta") or {}
    posts = [_post(x.get("webVideoUrl"), x.get("createTimeISO") or x.get("createTime"), x.get("text"),
                   _num(x, "playCount"), _num(x, "diggCount"), _num(x, "commentCount"), _num(x, "shareCount"), "Video")
             for x in items]
    return {"followers": _num(author, "fans"), "posts_count": _num(author, "video"), "posts": posts}


def _facebook_free(url: str) -> Optional[Dict[str, Any]]:
    tokens = _load_tokens()
    page_id = _facebook_page(url, tokens)
    return fetch_facebook_api(page_id, tokens[f"facebook:{page_id}"]["access_token"]) if page_id else None


def fetch_facebook(url: str) -> Dict[str, Any]:
    return _free_first(lambda: _facebook_free(url), lambda: _scrape_facebook(url))


def _scrape_facebook(url: str) -> Dict[str, Any]:
    page = (_run("apify~facebook-pages-scraper", {"startUrls": [{"url": url}]}) or [{}])[0]
    items = _run("apify~facebook-posts-scraper", {"startUrls": [{"url": url}], "resultsLimit": POSTS_PER_ACCOUNT})
    posts = [_post(x.get("url"), x.get("time") or x.get("timestamp"), x.get("text"), _num(x, "viewsCount"),
                   # The scraper drops "comments" when there are none.
                   _num(x, "likes", "topReactionsCount"), _num(x, "comments") or 0, _num(x, "shares"),
                   "Video" if x.get("isVideo") else "")
             for x in items]
    # shortcut: the posts count is only what the scraper returned (≤ POSTS_PER_ACCOUNT); Facebook exposes no total.
    return {"followers": _num(page, "followers", "followings", "likes"), "posts_count": len(posts), "posts": posts}


def fetch_youtube(url: str) -> Dict[str, Any]:
    items = _run("streamers~youtube-scraper", {"startUrls": [{"url": url}], "maxResults": POSTS_PER_ACCOUNT,
                                                "maxResultsShorts": POSTS_PER_ACCOUNT})
    first = items[0] if items else {}
    posts = [_post(x.get("url"), x.get("date"), x.get("title"), _num(x, "viewCount"), _num(x, "likes"),
                   _num(x, "commentsCount"), kind="Short" if "/shorts/" in (x.get("url") or "") else "Video")
             for x in items]
    return {"followers": _num(first, "numberOfSubscribers", "aboutChannelInfo.numberOfSubscribers"),
            "posts_count": _num(first, "channelTotalVideos", "aboutChannelInfo.channelTotalVideos"), "posts": posts}


# shortcut: no Threads fetcher yet (no well-established Apify actor); add one here when needed.
FETCHERS = {"instagram": fetch_instagram, "tiktok": fetch_tiktok, "facebook": fetch_facebook, "youtube": fetch_youtube}
# Free official-API connections (OAuth): configured?, authorize URL for a state, code -> connected account name(s).
CONNECTORS = {
    "instagram": (instagram_connect_configured, instagram_authorize_url, connect_instagram),
    "facebook": (facebook_connect_configured, facebook_authorize_url, connect_facebook),
}


def load_accounts() -> List[Dict[str, Any]]:
    with open(ACCOUNTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _read_cache() -> Dict[str, Any]:
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def snapshot() -> Dict[str, Any]:
    """Accounts from the config file, each platform filled from the last refresh (or marked why it has no data)."""
    cache = _read_cache()
    stats = cache.get("stats", {})
    tokens = _load_tokens()
    accounts = []
    for acc in load_accounts():
        platforms = {}
        for p in PLATFORMS:
            url = acc["links"].get(p, "")
            cached = stats.get(f"{acc['group']}:{p}")
            if not url:
                platforms[p] = {"url": "", "status": "no_link"}
            elif p not in FETCHERS:
                platforms[p] = {"url": url, "status": "unsupported"}
            elif cached and cached.get("url") == url:
                platforms[p] = cached
            else:
                platforms[p] = {"url": url, "status": "pending"}
            if p == "instagram" and url:
                platforms[p] = {**platforms[p], "connected": _handle(url).lower() in tokens}
            elif p == "facebook" and url:
                platforms[p] = {**platforms[p], "connected": _facebook_page(url, tokens) is not None}
        accounts.append({**acc, "platforms": platforms})
    return {"fetched_at": cache.get("fetched_at"), "refreshing": _refresh_lock.locked(),
            "configured": can_refresh(),
            "connect": {p: c[0]() for p, c in CONNECTORS.items()}, "accounts": accounts}


def _fetch_one(platform: str, url: str) -> Dict[str, Any]:
    try:
        data = FETCHERS[platform](url)
    except Exception as e:  # one failing account must not sink the whole refresh
        data = {"error": str(e)[:200]}
    return {"url": url, "status": "error" if data.get("error") else "ok", **data}


def _refresh_locked() -> None:
    jobs = {f"{a['group']}:{p}": (p, a["links"][p]) for a in load_accounts()
            for p in FETCHERS if a["links"].get(p)}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = dict(zip(jobs, pool.map(lambda job: _fetch_one(*job), jobs.values())))
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"fetched_at": datetime.now(timezone.utc).isoformat(), "stats": results}, f, ensure_ascii=False)
    os.replace(tmp, CACHE_FILE)


def refresh() -> bool:
    """Re-scrape every linked account and rewrite the cache. False when a refresh is already running."""
    if not _refresh_lock.acquire(blocking=False):
        return False
    try:
        _refresh_locked()
        return True
    finally:
        _refresh_lock.release()


def refresh_if_stale() -> None:
    """Start a background refresh when the data is not from today (local date). Called when the page is opened, so a
    day nobody opens it costs nothing. At most one attempt per day, even if that attempt crashes."""
    global _last_attempt
    today = date.today()
    fetched = _read_cache().get("fetched_at")
    if not can_refresh() or _last_attempt == today or (fetched and datetime.fromisoformat(fetched).astimezone().date() == today):
        return
    if not _refresh_lock.acquire(blocking=False):
        return
    _last_attempt = today

    def work() -> None:
        try:
            _refresh_locked()
        except Exception as e:
            print(f"[social] refresh failed: {e}")
        finally:
            _refresh_lock.release()

    threading.Thread(target=work, daemon=True).start()
