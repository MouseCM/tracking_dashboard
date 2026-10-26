# Tracking dashboard

Followers, posts and per-post views / likes / comments / shares for the accounts in `data/accounts.json`
(TikTok, Instagram, Facebook, YouTube; Threads not supported yet). Data comes from the free official APIs where an account is connected; paid Apify
scrapers are only the last resort (accounts not connected, or an API call that failed). Without `APIFY_TOKEN`
only connected accounts are fetched.

## Run

```bash
cp .env.example .env        # then fill in the Instagram app values, and APIFY_TOKEN only if needed
(cd web && npm install && npm run build)
python3 server.py           # http://127.0.0.1:8080
```

Opening the page refreshes the data at most once per day; a day nobody opens it costs nothing. Accounts not
connected to an official API are billed by Apify on each refresh (about $0.45 when none are connected) and takes a few minutes; the page updates when it is done. `python3 server.py --refresh` refreshes once and exits.

## Accounts

Edit `data/accounts.json`: one entry per channel with its profile links. Leave a link empty to skip that
platform. Never put passwords in this file.

## Connect Instagram (official API)

For Instagram Business/Creator accounts you own, the official API replaces the scraper (free, adds views from
insights). Create a Meta app with the *Instagram API with Instagram Login* product, register the redirect URI, and
set `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET`, `INSTAGRAM_REDIRECT_URI` in `.env`. Then click **Kết nối tài khoản**
on an Instagram row and log in as that account. Tokens go to `data/tokens.json` (gitignored, owner-only) and refresh
automatically; the next daily refresh uses them.

## Connect Facebook Pages (official API)

Same idea for Facebook Pages (not personal profiles): add the *Facebook Login* product to a Meta app, register
`.../api/connect/facebook/callback`, and set `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET`, `FACEBOOK_REDIRECT_URI`.
Click **Kết nối tài khoản** on a Facebook row and grant every Page you manage; one login connects them all, and
their tokens do not expire. A Page is matched by its `profile.php?id=` or direct link; `/share/...` links cannot
be matched, so replace them with the Page's direct link in `data/accounts.json`. Views are not fetched yet.

Full roadmap: `docs/social_account_monitoring_plan.md`.

## Tests

```bash
python3 -m pytest
```
