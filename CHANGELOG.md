# Changelog

## 2026-09-12 (bug fix: video row layout breaking on long/mixed-script titles)

### Fixed
- `static/index.html` — `.lib-row` used `align-items:center`, which
  vertically centers flex items against the tallest one in the row. A
  real video title with hashtags and non-Latin script (reported: an
  Arabic salutation glyph after "Biography of prophet Muhammad", plus
  hashtags) wrapped to 4+ lines on mobile, and centering then placed the
  thumbnail and Metrics button partway down the row instead of at the
  top — looking broken/unprofessional. Fixed by clamping the title
  (`.lib-info .n`) to 2 lines with an ellipsis and switching
  `align-items` to `flex-start`, so thumbnail/title/action always
  top-align regardless of title length — same pattern YouTube Studio's
  own video list uses. Affects all three Analytics video-row renderers
  (YouTube/Facebook/Instagram) plus the Dashboard's Recent Activity list,
  since they share `.lib-row`.

### Verification
Reported via a real screenshot from the live mobile site. Reproduced
with the exact reported title in a headless-browser mobile render, and
confirmed thumbnail/title/button now measure identical top offsets in
every row regardless of title length, on both the Analytics video list
and Dashboard Recent Activity.

Modified By:
Claude (via chat session)

---

## 2026-09-12 (real multi-user login: Sign In / Sign Up pages)

### Added
- `server.py` — new `users` and `sessions` tables. Passwords hashed with
  PBKDF2-HMAC-SHA256 (random per-user salt, 260,000 iterations — stdlib
  only, no new dependency). Session identity is a random token in an
  HttpOnly/SameSite=Lax cookie (`mf_session`, 30-day expiry), replacing
  HTTP Basic Auth entirely.
- `server.py` — new routes: `GET /login`, `GET /signup` (public; redirect
  to `/` if already logged in), `POST /api/auth/signup`,
  `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`.
  `GET /` now redirects to `/login` instead of a Basic Auth 401 when not
  logged in.
- `static/login.html`, `static/signup.html` — new standalone pages
  (outside the main SPA) matching MediaFlow's existing visual language —
  dark brand panel + form, collapsing to just the form on mobile. Signup
  has live "passwords match" / min-length validation; both show an
  inline error banner on failure instead of a native browser prompt.
- `static/index.html` — sidebar's user card (previously hardcoded
  "Admin / admin@example.com") now shows the real logged-in username and
  a working Log Out button. Added a global `fetch` wrapper that redirects
  to `/login` on any 401 response, so an expired/invalidated session
  bounces the person to sign in again instead of every page silently
  failing to load its data.
- `require_login` kept its old return signature (just the username) so
  none of the ~20 existing `Depends(require_login)` route signatures
  needed to change — only how that identity gets established did.

### Backward compatibility
If `APP_USERNAME`/`APP_PASSWORD` env vars are set and no `users` row
exists yet, one account is seeded from them on first boot (existing
installs aren't locked out). If neither is set, a one-time
random-password account is created and printed to the server log
instead. Either way this only happens once — from then on it's an
ordinary account, and new people should use Sign Up rather than share it.

### Note — this reverses part of Decision 003
Decision 003 (multi-account support) explicitly kept "one shared login,
not separate user logins." This session's request was specifically for
real per-person accounts, so that part of Decision 003 no longer holds —
see Decision 004 in `docs/DECISIONS.md` for the full reasoning. The
*workspace*-accounts concept from Decision 003 (independent platform
connections/posts/analytics, switched via the top-right dropdown) is
unrelated and unchanged.

### Known limitation (by explicit choice, not an oversight)
Sign-up is fully open — anyone who reaches the app's URL can create an
account with full access to the dashboard and connected platforms. This
was offered as a choice (gated vs. open) and open was explicitly chosen.
An optional invite-code gate was proposed and noted in TODO.md in case
this needs tightening later, but wasn't built since it wasn't requested.

### Verification
Tested locally end-to-end before pushing (this repo's dev environment
has no real platform credentials, but auth itself needed none): signup,
duplicate-username rejection, short-password rejection, wrong-password
login rejection, correct login, logout, post-logout 401, and legacy
env-var seeding all verified via curl. Full UI flow (both pages, desktop
+ mobile, validation states, error states, post-signup/login redirect,
sidebar user card, logout, and both the server-side redirect guard and
the client-side 401 fetch guard for an invalidated session) verified
with a headless-browser walkthrough — no console/page errors.

Modified By:
Claude (via chat session)

---

## 2026-09-11 (bug fix: sidebar collapse breaking mobile menu)

### Fixed
- `static/index.html` — `.sidebar.collapsed{width:0!important}` had no
  responsive guard, so collapsing the sidebar on desktop (state
  persisted in `localStorage`) silently broke the mobile hamburger
  drawer on that same browser: opening it (live resize or fresh mobile
  load) showed the dark backdrop but no visible sidebar, since
  `!important` beat the mobile `.sidebar.open` transform regardless of
  screen width. Scoped the collapsed-state rule to `>720px` only, and
  hardened the mobile `.sidebar` rule with an explicit
  `width:230px!important` so a desktop drag-resized width can't leak
  into the mobile drawer either.

### Verification
Requested a bug/mobile-alignment audit of the last few sessions' changes.
Used a headless Chromium (Puppeteer) to actually render and interact
with the app rather than just reading the CSS:
- Reproduced the bug above via both a live desktop→mobile resize and a
  fresh mobile page load with collapsed state already in localStorage;
  confirmed both fixed after the change.
- Swept every page (Dashboard, Accounts, Platforms, Upload, Scheduled,
  Published, Analytics, Settings, Help) at a 390px mobile viewport —
  no console/page errors, no horizontal overflow.
- Stress-tested with intentionally extreme mock data: very long
  subscriber/follower counts on the dashboard platform tiles, a
  ~120-character video title in Analytics' video list (wraps cleanly,
  thumbnail placeholder space reserved correctly), and long titles in
  the notifications drawer — no overflow or overlap in any case.
- Exercised the notification drawer (open/close/click-through), the
  desktop sidebar drag-resize, and notification-click navigation — all
  worked as expected.

No other bugs or alignment issues found in this pass.

Modified By:
Claude (via chat session)

---

## 2026-09-11 ("Today" filter + per-video total/period views in YouTube Analytics)

### Added
- `server.py` `/api/analytics/summary` — each top video now also returns
  `lifetime_views` (its all-time YouTube view count, via `statistics`
  part on `videos().list`) alongside the existing period-scoped `views`.
- `server.py` — both `/api/analytics/summary` and
  `/api/analytics/video/{id}` now compute their date range using
  `America/Los_Angeles` instead of UTC, since YouTube Analytics' `day`
  dimension is Pacific-Time-bucketed (same as YouTube Studio). Matters
  most for a 1-day window, where a UTC boundary could disagree with
  YouTube's own idea of "today" by several hours.
- `requirements.txt` — added `tzdata`, so `zoneinfo` resolves correctly
  regardless of the deploy VM's OS-level timezone database.
- `static/index.html` — added a "Today" option next to 7d/28d/90d in
  YouTube Analytics. Since the video list already only includes videos
  with activity in the selected period (YouTube Analytics omits
  zero-activity rows), selecting "Today" naturally narrows the list to
  just the videos that actually received views today. Each row now
  shows total lifetime views plus a "+N today" / "+N in Nd" pill for the
  period gain, instead of only ever showing the period-scoped count.

### Known limitation (not fixed, documented instead)
- Facebook/Instagram's video/post lists are unchanged. Meta's Graph API
  only exposes lifetime view counts at the individual video/media level
  (no per-day, per-video breakdown), so an equivalent "only posts with
  views today" list isn't reliably buildable there with the current API.

Reason:
Project owner wanted to see, for a given date/period, only the videos
that actually received views in that window, each showing its total
(lifetime) views plus how many of those came from the selected period.

Modified By:
Claude (via chat session)

---

## 2026-09-11 (platform bar subscriber/follower counts)

### Added
- `server.py` `/api/status` — YouTube now requests `statistics` in
  addition to `snippet` and returns `subscribers` (omitted if the
  channel owner has hidden their subscriber count via
  `hiddenSubscriberCount`). Facebook/Instagram now request
  `followers_count` on the Page and on its linked Instagram Business
  account; if the Page token doesn't have permission for those fields,
  falls back to the original minimal-fields query so connection-status
  detection keeps working either way (counts just won't show).
- `static/index.html` — the dashboard's platform bar (YouTube/Facebook/
  Instagram tiles) now shows a compact count next to the status dot when
  connected and the backend provided one, e.g. "12.4K subscribers" /
  "3.2K followers" (new `fmtCompact()` helper). Blank when not
  connected or the count isn't available.

Reason:
Project owner asked to see subscriber/follower counts in the dashboard's
platform bar.

Modified By:
Claude (via chat session)

---

## 2026-09-11 (dashboard interactivity + notifications + sidebar)

### Added
- `static/index.html` — Dashboard stat cards (Scheduled, Published,
  Connected Accounts) and the YouTube/Facebook/Instagram platform tiles
  are now clickable: they navigate to their respective page (`scheduled`,
  `published`, `platforms`) via the existing `data-goto`/`showPage`
  mechanism, with a hover affordance (lift + shadow) so it's clear
  they're interactive.
- `static/index.html` — "Needs Attention" card now opens the Published
  page pre-loaded with failed uploads only (`goToNeedsAttention()`, using
  the already-existing `GET /api/library?status=failed` support in
  `server.py`, no backend change needed).
- `static/index.html` — new right-side notifications drawer, toggled by
  clicking the bell icon (opens/closes via backdrop click, × button, or
  Escape). Populated client-side from data already fetched for the
  dashboard summary (failed-upload count + recent activity) — no new
  backend endpoint added. The bell badge now shows a real count instead
  of the previous hardcoded `3`, and hides when there's nothing to show.
- `static/index.html` — sidebar is now collapsible (new collapse button
  next to the logo + a small reopen tab on the far left edge when
  collapsed) and resizable by dragging its right edge (handle between
  sidebar and main content, 180–420px range, double-click resets to
  230px). Both the collapsed state and the chosen width persist across
  reloads via `localStorage`. Desktop-only — the existing mobile
  hamburger slide-in behavior (`<720px`) is untouched.

Reason:
Project owner asked for the dashboard to be fully interactive (cards/
platform tiles that don't currently do anything on click), a
notifications panel, and a sidebar that can be resized/collapsed.

Modified By:
Claude (via chat session)

---

## 2026-09-11 (bugfix pass)

### Fixed
- `server.py` `delete_account()` — deleting an account with any
  still-scheduled (unpublished) posts left their video files behind in
  `uploads/` forever, since only the DB rows were deleted. Now collects
  those `video_path` values before the DB delete and unlinks the files
  afterward.
- `server.py` `oauth2callback_youtube()` — after a successful YouTube
  connect, the redirect still pointed to `?page=accounts`, which was
  correct when that page showed platform-connect status but now opens
  the unrelated account-management page after the Accounts/Platforms
  split earlier today. Changed to `?page=platforms`.

Reason:
Found while reviewing the Accounts/Platforms change (see the
2026-09-11 entry below) for bugs on request. Both were introduced or
exposed by that change, not pre-existing.

Modified By:
Claude (via chat session)

---

## 2026-09-11

### Added
- `server.py` — `PATCH /api/accounts/{id}` (rename an account) and
  `DELETE /api/accounts/{id}` (delete an account: refuses if it's the
  last remaining account, otherwise deletes its `uploads` rows and its
  `credentials/accounts/<id>/` directory).
- `static/index.html` — new **Accounts** nav item/page: lists all
  accounts, lets you rename (prompt) or delete (confirm) any of them,
  add a new one, and click a row to switch to it. Delete button is
  disabled when only one account remains.

### Changed
- `static/index.html` — the previous **Accounts** page (connect/
  disconnect YouTube/Facebook/Instagram for the selected account) is
  renamed to **Platforms**: nav label, `data-page` attribute, element
  ids (`accountsPageAccountName` → `platformsPageAccountName`,
  `accountsPageList` → `platformsPageList`), and the JS function
  `loadAccountsPage()` → `loadPlatformsPage()`.
- All user-facing "Accounts" wording that actually meant "go connect a
  platform" — in `server.py` error messages and `static/index.html`
  toasts/buttons/analytics empty-states — now says "Platforms" instead,
  to match the page it points to.
- Refactored the "add account" prompt flow into a shared
  `promptCreateAccount()`, used by both the top-right account-switcher
  dropdown and the new Accounts page, instead of duplicating it.

Reason:
Requested: a way to rename/edit existing accounts (e.g. Sohail, Moiz)
from the UI (previously create + list only — see TODO.md), and split
the old combined "Accounts" page into a dedicated account-management
page plus a "Platforms" page for what it actually did (connect
YouTube/Facebook/Instagram).

Modified By:
Claude (via chat session)

---

## 2026-09-10

### Added
- `docs/PROJECT_CONTEXT.md` — project overview, architecture, current status
- `docs/DECISIONS.md` — technical decisions log
- `TODO.md` — task tracker
- `SESSION_HANDOFF.md` — handoff notes between Claude sessions/accounts
- `CLAUDE_INSTRUCTIONS.md` — standing instructions for any Claude session
  working on this repo

Reason:
Setting up a documentation-as-source-of-truth system so work can continue
across multiple separate Claude accounts without losing context.

Modified By:
Claude (via chat session)

---

## 2026-09-10 (later session)

### Changed
- `static/index.html` — top-right admin-pill label changed from "Sohail"
  to "Moiz"; avatar initial changed from "S" to "M".

Reason:
Requested display-name change for the account shown in the top-right of
the dashboard header. Cosmetic only — no backend, auth, or schema changes.

Deployed:
Pushed to `main`, which triggered the GitHub Actions auto-deploy to the
live VM (this change touches `static/**`).

Modified By:
Claude (via chat session)

---

## 2026-09-10 (multi-account support)

### Added
- New `accounts` DB table (id, name, created_at). Account 1 is
  auto-seeded as "Moiz" on first run after this change, matching the
  previous single-tenant admin-pill name.
- `account_id` column on `uploads` (default 1), backfilling existing
  rows so nothing already scheduled/published loses its data.
- Per-account credential storage: `credentials/accounts/<id>/` for
  YouTube tokens and Facebook Page tokens. On first boot, any existing
  `credentials/token.json` / `credentials/facebook.json` is copied into
  `credentials/accounts/1/` so the original install is unaffected.
- `GET /api/accounts` and `POST /api/accounts` endpoints.
- Frontend: the top-right pill is now an account switcher dropdown
  (shows current account, lists all accounts, "+ Add account" creates a
  new one). Switching accounts re-scopes the current page's data.

### Changed
- Every relevant endpoint (`/api/publish`, `/api/library`,
  `/api/dashboard/summary`, all `/api/analytics/*`, YouTube OAuth
  connect/callback, Facebook connect/disconnect) now takes an
  `account_id` param and uses that account's credentials/DB rows.
- `get_youtube_credentials()` / `get_facebook_credentials()` /
  `get_youtube_client()` now take `account_id` (default 1).
- `.gitignore`: added `__pycache__/` and `*.pyc` (a stray compiled
  `.pyc` had been tracked; removed it from the repo).

Reason:
Project owner wants multiple fully independent sets of platform
connections (different clients/brands) from one MediaFlow install, with
one shared login and an in-app switcher rather than separate per-account
logins. See docs/DECISIONS.md 003 for the full design and alternatives
considered.

Not Done:
- No UI to rename or delete an account yet (create/list only).
- No decision yet on how the background scheduler should scale across
  many accounts' due posts (currently just iterates every due row across
  all accounts each poll — fine at small scale, untested at large scale).

Deployed:
Pushed to `main`, which triggered the GitHub Actions auto-deploy to the
live VM (this change touches `server.py` and `static/**`).

Modified By:
Claude (via chat session)

---

## 2026-09-10 (mobile nav fix + doc corrections)

### Fixed
- `static/index.html` — sidebar nav was completely hidden below 720px with
  no way to get back to it (no hamburger, no alternative navigation). Added
  a hamburger toggle that opens the sidebar as a slide-in overlay with a
  backdrop; closes on nav click or backdrop click.
- Tightened `.stat-grid`, `.platform-grid`, and the account-switcher
  dropdown sizing for narrow screens; truncated long page titles instead of
  letting them overflow the topbar.

### Changed
- `README.md`, `DEPLOYMENT_GUIDE.md` — updated credential path references
  from the old flat `credentials/token.json` / `credentials/facebook.json`
  to the real `credentials/accounts/<id>/...` paths used since multi-account
  support landed; added a note about Google OAuth "Testing" mode requiring
  test users (see the access_denied error hit this session).

Reason:
Requested mobile-friendliness check turned up a real navigation bug on
phone-width screens; fixed it and corrected docs that had gone stale after
the multi-account change.

Verified:
- `python3 -m py_compile server.py` (unaffected by this change, still
  compiles)
- extracted and `node --check`'d the page's JS after edits
- reviewed the full diff before pushing

Deployed:
Pushed to `main`, triggering the GitHub Actions auto-deploy (touches
`static/**`).

Modified By:
Claude (via chat session)

---

## 2026-09-10 (dashboard redesign)

### Added
- Dashboard: new "Connected platforms" strip — YouTube/Facebook/Instagram
  tiles with brand icons and a live green/gray status dot, sourced from
  `/api/status` for the current account.

### Changed
- `static/index.html` — "Needs Attention" stat card now tints red only
  when `failed_count > 0`, instead of a plain white card with red text.
- Recent Activity list thumbnails now show a platform-colored icon
  (YouTube red / Facebook blue / Instagram gradient) instead of a
  decorative purple gradient block.
- Account switcher pill (top right) restyled as a bordered pill with a
  hover state, instead of plain text + caret.

Reason:
Requested UI sample based on the app's own architecture; applied the
approved direction (semantic color usage, at-a-glance platform status,
clearer visual hierarchy) to the real dashboard.

Verified:
- extracted and `node --check`'d the page's JS after edits
- confirmed `/api/status` response shape (`{connected: bool}` per
  platform) matches what the new tile logic reads
- `python3 -m py_compile server.py` (unaffected, still compiles)

Deployed:
Pushed to `main` (d332531..54506b7), triggering the GitHub Actions
auto-deploy (touches `static/**`).

Modified By:
Claude (via chat session)

---

## 2026-09-14 (backend + frontend file-architecture split)

### Added
- `app/` package: `config.py`, `db.py`, `auth.py` (multi-user login),
  `credentials.py`, `uploaders.py`, `scheduler.py`, and `app/routes/*.py`
  (status_publish, library, accounts, analytics_youtube, analytics_meta,
  youtube_oauth, facebook_connect, media, auth_pages)
- `frontend-src/`: `layout.html`, `style.css`, `app.js`, `pages/*.html`
  (one per page) — the new source of truth for the single-page app
- `build.py` — assembles `frontend-src/` into `static/index.html`

### Changed
- `server.py` reduced from ~1930 lines to just app creation, middleware,
  startup, and router registration — all logic moved into `app/`
- `static/index.html` is now a generated file (still committed, still what
  the server serves, but edits should go through `frontend-src/` + `build.py`).
  `static/login.html` / `static/signup.html` are unaffected — not part of
  this build.
- `.github/workflows/deploy.yml`: added a "Build static/index.html from
  frontend-src/" step before rsync, and widened the `paths:` trigger to
  include `app/**`, `frontend-src/**`, and `build.py`

Reason:
Requested ability to touch one API's file or one page's file without
dealing with the whole codebase. See docs/DECISIONS.md 005.

Verified (no behavior change intended or expected):
- Backend: captured a full baseline of every real endpoint's response
  (including signup/login/logout, session cookies, and account
  create/rename/delete guards) from the original server.py using FastAPI's
  TestClient, then diffed the refactored app's responses against that
  baseline — 28/28 checks matched (only difference was a timestamp that's
  naturally different between two separate test runs). Caught and fixed
  one real bug (a missing import) before it shipped.
- Frontend: diffed build.py's output against the original static/index.html
  — byte-for-byte identical aside from one intentional "generated file,
  don't edit" comment. Caught and fixed two off-by-one slicing bugs (a
  missing `</div>` closing `.main`, and a duplicated trailing newline)
  before they shipped.
- `python3 -m py_compile` on every new/changed `.py` file
- `node --check` on the assembled JS in the final generated file

Not deployed yet — this work is on the local session's copy of the repo,
pending review before push (see SESSION_HANDOFF.md).

Modified By:
Claude (via chat session)
