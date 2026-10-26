# Social Media Account Monitoring Plan

## 1. Goal

Build a dashboard to monitor approximately 20 TikTok, Instagram, and Facebook accounts for which access is authorized. Track account growth, new posts, and available engagement metrics over time.

**Scope:** data collection and analytics only. Do not bypass authentication, access controls, platform rate limits, or anti-bot protections. Having a username and password does not by itself grant API permission to retrieve every metric.

## 2. Data to Collect

### Account-level metrics
- Platform and account ID
- Username / display name and profile URL
- Follower count, where exposed by the platform/API
- Following count, where available
- Timestamp of each observation
- Daily/weekly follower growth derived from historical snapshots

### Post-level data
- Platform post ID and permalink
- Caption or text, subject to API permissions
- Media type (photo, video, Reel, etc.), where available
- Publication timestamp
- Views / plays, likes, comments, shares, reposts, and other supported metrics
- Timestamp of each metric snapshot
- Availability status if a post disappears or becomes inaccessible

### Alerts
- New post detected
- Significant follower-count change
- Post engagement or view count crosses a configurable threshold
- Access token expires or API permission is revoked
- Collector errors or quota/rate-limit warnings

Not every platform exposes every metric for every account type. Record only the fields returned and permitted by each API. Historical values are available only after collection begins unless the platform explicitly provides historical data.

## 3. Account-Type Constraints

| Platform / account type | Recommended route | Important limitations |
|---|---|---|
| Instagram Business or Creator | Official Instagram API with account-owner authorization | Requires suitable account type, permissions, and sometimes app review. Insights are limited to eligible accounts and supported metrics. |
| Instagram personal account | Check whether the account can be converted to Business/Creator if appropriate | There is no general-purpose official API for unrestricted analytics on arbitrary personal accounts. |
| Facebook Page | Meta Graph API and a Page access token | Requires suitable Page permissions and authorization. Insights are for eligible Pages and supported metrics. |
| Facebook personal profile | Do not assume general API access is available | Logging in to a profile does not grant a third-party app unrestricted access to private profile analytics. |
| TikTok account | TikTok for Developers APIs with OAuth and approved scopes | Data and scopes depend on the API product and approval. Some APIs are designed for displaying authorized profile/video information rather than unrestricted analytics. |

## 4. Recommended Connection Method

Use OAuth rather than storing account passwords in the application.

1. Register the application in the relevant developer portal.
2. Configure authorized redirect/callback URLs.
3. The account owner clicks **Connect account** in the dashboard.
4. Redirect the owner to the platform's official authorization page.
5. Exchange the returned authorization code on the backend for an access token.
6. Store tokens encrypted, with minimal database/application access.
7. Refresh tokens when supported; handle expiration and revoked consent.
8. Check permissions and show which metrics are actually available for each account.

For 20 accounts, use an account registry so every connected account has its own platform, account ID, authorization status, token metadata, and collection schedule. Never place raw passwords or access tokens in source control, logs, browser storage, or client-side code.

## 5. Architecture

```text
Dashboard (React or similar)
        |
        v
Backend API (Go or Python)
        |
        +---- OAuth / token management
        |
        +---- Scheduled collection workers
        |          |
        |          +---- Instagram connector
        |          +---- Facebook connector
        |          +---- TikTok connector
        |
        v
PostgreSQL
  - connected accounts
  - posts
  - account metric snapshots
  - post metric snapshots
  - collection runs and errors
  - alert events
        |
        v
Dashboard charts + Telegram/Discord/email alerts
```

Suggested components:
- **Backend:** Go or Python
- **Database:** PostgreSQL
- **Scheduler/worker:** a cron-based job or a task queue
- **Frontend:** React
- **Secrets:** environment-based secret injection or a secrets manager; encrypt stored tokens
- **Alerts:** Telegram, Discord, or email

## 6. Suggested Database Tables

### `connected_accounts`
- `id`
- `platform` (`instagram`, `facebook`, `tiktok`)
- `platform_account_id`
- `username`
- `profile_url`
- `account_type` (Page, personal, Business, Creator, etc.)
- `authorization_status`
- `encrypted_access_token`
- `encrypted_refresh_token` (nullable)
- `token_expires_at` (nullable)
- `last_successful_sync_at`
- `created_at`, `updated_at`

### `posts`
- `id`
- `connected_account_id`
- `platform_post_id`
- `permalink`
- `caption_or_text` (nullable)
- `media_type` (nullable)
- `published_at` (nullable)
- `first_seen_at`
- `last_seen_at`
- Unique constraint on `(connected_account_id, platform_post_id)`

### `account_metric_snapshots`
- `id`
- `connected_account_id`
- `captured_at`
- `followers_count` (nullable)
- `following_count` (nullable)
- `other_metrics_json` (only supported, permitted fields)

### `post_metric_snapshots`
- `id`
- `post_id`
- `captured_at`
- `views_count` (nullable)
- `likes_count` (nullable)
- `comments_count` (nullable)
- `shares_count` (nullable)
- `reposts_count` (nullable)
- `other_metrics_json` (only supported, permitted fields)

### `collection_runs`
- `id`
- `connected_account_id`
- `started_at`
- `finished_at`
- `status`
- `items_fetched`
- `error_code` (nullable)
- `error_message_redacted` (nullable)

### `alert_events`
- `id`
- `connected_account_id`
- `post_id` (nullable)
- `alert_type`
- `payload_json`
- `created_at`
- `delivered_at` (nullable)

## 7. Collection Workflow

For each connected account:

1. Confirm authorization and required scopes.
2. Fetch supported account metrics.
3. Save a timestamped account snapshot.
4. Fetch recent posts available through the API.
5. Insert unseen post IDs without duplicating existing records.
6. Fetch supported metrics for each post.
7. Save timestamped post snapshots.
8. Generate alerts for new posts or configured metric changes.
9. Record success/failure and API quota information.
10. Retry transient errors with backoff; do not repeatedly retry permanent permission errors.

Start with a configurable interval such as every 30–60 minutes, then tune it to each API's published limits and the app's actual access. Do not assume a 15-minute schedule is permitted for every endpoint/account.

## 8. Useful Dashboard Views

- **Overview:** all accounts, current follower counts, last sync, connection health
- **Account detail:** follower history and recent posts
- **Post performance:** sort/filter by views, likes, comments, shares, and age of post
- **Growth:** follower change by day/week
- **Activity feed:** newest posts across all connected accounts
- **Alerts:** new posts, unusual growth, API errors, token expiration
- **Coverage report:** metrics available/unavailable per account and platform

To compare posts fairly, capture metrics at consistent post ages where feasible (for example, around 1 hour, 24 hours, and 7 days after publication). The scheduler should collect according to API limits, and the dashboard should clearly label missing or unavailable metrics.

## 9. Implementation Milestones

### Phase 1 — Inventory and eligibility
- Make a list of all 20 profile/Page URLs.
- Identify each platform and account type.
- Confirm which accounts you own or have authorization to monitor.
- Mark which accounts can authorize an API connection.

### Phase 2 — Instagram first
- Create/configure the Meta developer app.
- Implement OAuth and secure token storage.
- Connect one eligible Instagram Business/Creator account.
- Retrieve profile/media data and the metrics exposed to that account.
- Save snapshots and display them in a basic dashboard.

### Phase 3 — Facebook Pages
- Add Page authorization and Page token handling.
- Retrieve permitted Page posts, engagement, and insights.
- Test on one Page before connecting the rest.

### Phase 4 — TikTok
- Register a TikTok developer app.
- Implement OAuth and only the approved API products/scopes.
- Verify which account and video metrics are available before building dashboards around them.

### Phase 5 — Scale to 20 accounts
- Add account connection status and per-account sync schedules.
- Add retries, rate-limit handling, alerting, and monitoring.
- Validate data quality and duplicate prevention.

## 10. Developer Portals and Documentation

- Meta for Developers: https://developers.facebook.com/
- Instagram API documentation: https://developers.facebook.com/docs/instagram-platform/
- Instagram API workspace/reference: https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api
- Facebook Graph API: https://developers.facebook.com/docs/graph-api/
- Facebook Pages API: https://developers.facebook.com/docs/pages-api/
- TikTok for Developers: https://developers.tiktok.com/
- TikTok API documentation: https://developers.tiktok.com/doc/overview/

Check each platform's current documentation for supported account types, scopes, app-review requirements, rate limits, and metric availability before implementation; APIs and permissions can change.

## 11. Input Template for the 20 Accounts

Fill in this list without including passwords or access tokens.

| # | Platform | Profile/Page URL | Account type | Authorized owner? | API connected? | Notes |
|---:|---|---|---|---|---|---|
| 1 | | | | | | |
| 2 | | | | | | |
| 3 | | | | | | |
| 4 | | | | | | |
| 5 | | | | | | |
| 6 | | | | | | |
| 7 | | | | | | |
| 8 | | | | | | |
| 9 | | | | | | |
| 10 | | | | | | |
| 11 | | | | | | |
| 12 | | | | | | |
| 13 | | | | | | |
| 14 | | | | | | |
| 15 | | | | | | |
| 16 | | | | | | |
| 17 | | | | | | |
| 18 | | | | | | |
| 19 | | | | | | |
| 20 | | | | | | |

## Definition of Done

- Authorized connection flow works for each supported account type.
- Tokens are encrypted and never exposed in the frontend or logs.
- Each account's supported follower metrics and posts are saved with timestamps.
- Post records are deduplicated by platform post ID.
- The dashboard shows metric history, new posts, sync health, and unavailable data clearly.
- API rate limits, authorization failures, token expiration, and revocation are handled safely.
