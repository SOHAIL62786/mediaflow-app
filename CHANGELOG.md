# Changelog

## 2026-09-20 (fix: HTTPS outage caused by overwriting a live-only nginx block; also: race-condition 404s, nginx upload timeouts)

### Fixed
- **Race condition causing stale-account 404s on page load.** `loadStatus()`
  and the initial `showPage()` (which loads the dashboard) both fired
  immediately on script load, before `loadAccounts()` — which validates
  `currentAccountId` against accounts the user actually owns, and corrects
  it if stale — had resolved. Anyone whose `localStorage` still pointed at
  an account they no longer owned (reassigned or deleted) would get one
  round of 404s on `/api/dashboard/summary` and `/api/status` before the
  correction landed. Reported via console screenshot. Fix:
  `frontend-src/app.js` — `loadAccounts()` now returns its promise
  (`accountsReady`), and both calls chain off it instead of firing
  independently.
- **nginx `client_body_timeout`/`send_timeout` were never set** (default
  60s) — too short for a large video over a slow/unstable connection.
  Added both at 600s, matching the existing `proxy_read_timeout`/
  `proxy_send_timeout` pair. Investigated as a possible cause of a
  real `ERR_CONNECTION_ABORTED` during publish; not confirmed as the
  actual cause before the incident below overtook the session, but a
  real gap worth having fixed regardless.

### Fixed — and caused, same session (see docs/DECISIONS.md 011)
- **A ~30 minute HTTPS outage**, caused by an assistant instruction:
  `sudo cp mediaflow.nginx.conf /etc/nginx/sites-available/mediaflow`
  overwrote a certbot-managed HTTPS server block that existed live on the
  VM but was never captured in this repo (the repo only ever had the
  generic `server_name _;` placeholder). HTTP kept working throughout,
  which made this a slow, confusing diagnosis — Security Group, Cloudflare,
  and Chrome's automatic HTTPS upgrade were all incorrectly suspected
  before the real cause surfaced. Fix: `mediaflow.nginx.conf` now pins
  `server_name sohailanalytics.online;` so certbot can find and re-attach
  to this exact block. A standing rule was added to CLAUDE_INSTRUCTIONS.md:
  never copy this file (or `mediaflow.service`) onto the VM without first
  diffing it against what's actually live there.

Modified By:
Claude (via chat session)

---

## 2026-09-19 (small feature: Analytics loading progress bar)

### Added
- `frontend-src/style.css` / `frontend-src/app.js` — while the Analytics
  page's data is fetching, `#analyticsBody` now shows a slim animated
  progress bar (`.analytics-progress-track` / `.analytics-progress-fill`,
  `@keyframes mf-analytics-progress`) above the existing "Loading…" text,
  instead of the text alone.

Indeterminate, not a real percentage: there's a single `fetch()` call
behind this with no meaningful multi-step progress to surface, so an
animated sweeping bar (same idea as the existing `.mini-spinner`, just
styled as a bar) is what's actually accurate here, not a fake percentage.

Reason:
Directly requested, from a screenshot of the Analytics page stuck on
plain "Loading…" text with no visual indicator.

Modified By:
Claude (via chat session)

---

## 2026-09-18 (feature: admin panel)

### Added
- Admin role: `users.is_admin`, granted by migration to the single
  earliest-created user only (never every pre-existing user — same
  reasoning as the Decision 007 backfill). New `require_admin` dependency,
  separate from `require_login`, gating a new `app/routes/admin.py`:
  list users, list every workspace account with its owner, reassign an
  account's owner, force a password reset (invalidates that user's
  existing sessions), promote/demote admins, delete a user.
- Delete-user safety guards mirroring the existing "last account" pattern:
  can't delete yourself, can't delete a user who still owns accounts,
  can't demote/delete the last remaining admin.
- Settings page: two new panels (Users, Workspace accounts), visible only
  to an admin, reusing the existing Accounts-page row/button styling.

### Note for the project owner
Unlike the SIGNUP_CODE gate (safe by default, opt-in), this decides who
gets elevated access over other users' accounts — held for your review
before pushing, and pushed once you gave the go-ahead. Full reasoning,
every alternative considered, and the exact verification list are in
docs/DECISIONS.md 010.

## 2026-09-18 (feature: optional SIGNUP_CODE invite-gate for signup)

### Added
- Optional `SIGNUP_CODE` env var (`app/config.py`). Unset by default —
  signup stays exactly as open as it's always been. If set, `POST
  /api/auth/signup` requires a matching `signup_code` field (checked with
  `secrets.compare_digest`, before any DB write, so a wrong attempt
  doesn't create a user row or let someone reserve a username).
- New public `GET /api/auth/signup-config` → `{"require_code": bool}`, so
  the signup page can decide whether to show the invite-code field
  without hardcoding or guessing the server's configuration. Never
  exposes the code itself.
- `static/signup.html`: invite-code field, hidden by default, shown (and
  marked required) only when `signup-config` says it's needed.

### Fixed
- The signup page's brand-panel note still said "everyone who signs up
  shares the same MediaFlow dashboard and connected accounts" — true
  before Decision 006, false and actively misleading since per-user
  isolation shipped. Replaced with an accurate line about each account
  being private.

### Verified
- Gate off: identical behavior to before, any/no code accepted.
- Gate on: missing or wrong code → 403, no user row created either way;
  correct code → 200, resulting user is fully functional (owns their own
  account, etc.). `signup-config` reports the right state in both modes.
- Re-ran the full isolation + path-routing regression suite — still
  passing. `pyflakes` clean.
- Not verified: the field's show/hide behavior in an actual browser — no
  browser tooling in this environment.

Full design detail and alternatives considered: docs/DECISIONS.md 009.

## 2026-09-17 (reconciliation note)

The two entries below (`6f58833`, `7d53e80`) were pushed directly by a
different session without CHANGELOG/TODO/SESSION_HANDOFF updates at the
time — added retroactively here for the record, since TODO.md still
listed one of them as unfixed.

## 2026-09-17 (bug fix: dark-mode + stale OAuth redirect, from audit)

### Fixed
- `.manage-btn` (Accounts page "Add account", Upload page "Manage
  Platforms") was still hardcoded to `background:#fff`, missed in the
  earlier dark-mode conversion pass — now uses `var(--card-bg)`/
  `var(--hover-bg)`.
- YouTube OAuth callback redirected to the old
  `/?page=platforms&account_id=X` scheme instead of the new `/platforms`
  path from the routing change (Decision 008). The `account_id` query
  param was already dead — the frontend reads the active account from
  `localStorage`, not the URL — so it was simply dropped rather than
  ported forward.

## 2026-09-17 (feature: loading skeleton for dashboard platform counts)

### Added
- The dashboard's platform subscriber/follower count spans (e.g. "144
  subscribers") stayed blank with no indication anything was loading
  while `/api/status` was in flight — reported via screenshot. Added a
  shimmering skeleton placeholder shown until the real count (or the
  empty/disconnected state) replaces it.

### Fixed
- The fetch-failure path previously left that skeleton shimmering
  forever if the request errored — now resolves to an error/empty state
  instead.

## 2026-09-17 (feature: path-based page URLs instead of ?page= query string)

### Added
- `server.py`: `/dashboard`, `/accounts`, `/platforms`, `/upload`,
  `/scheduled`, `/published`, `/analytics`, `/settings`, and `/help` are
  now real routes, each serving the same login-gated `index.html` as `/`
  always has. Needed because the SPA's client-side routing only runs
  after `index.html` has loaded — without a matching server route, a
  hard refresh, bookmark, or shared link on any page but `/` would 404.

### Changed
- `frontend-src/app.js`: the address bar now shows `/dashboard`,
  `/accounts`, etc. instead of `/?page=dashboard`, `/?page=accounts`.
  Old `?page=xxx` links still work once and get normalized to the new
  `/xxx` form automatically. See docs/DECISIONS.md 008 for full detail.

### Verified
- Every new page path returns 200 for a logged-in user and a 307 to
  `/login` for a logged-out one; an unrelated/unknown path still 404s;
  existing `/api/*` routes unaffected. Unit-tested the JS's
  page-detection logic directly (path-based, legacy-query fallback, bare
  `/`, and garbage-path cases) via Node. `pyflakes` clean.
- Not verified: real browser back/forward behavior, or a visual check on
  the live VM — no browser tooling in this environment.

## 2026-09-17 (bug fix: toggle switches showing two dots when on)

### Fixed
- Every `.toggle` switch (dark-mode toggle, the Upload page's "customize"
  toggle) showed two overlapping white dots instead of one whenever it
  was on. Reported by the project owner with a screenshot. Cause: two
  separate things were drawing a dot — a CSS `.toggle::after`
  pseudo-element permanently pinned at the left/off position, and a real
  `<span class="dot">` element that `frontend-src/app.js`'s `setDot()`
  creates and actually slides left/right on click. When off, both sat on
  top of each other on the left and looked like one dot; when on, the JS
  dot correctly moved right but the CSS pseudo-element was left behind on
  the left. Predates the recent dark-mode work — not something that
  commit introduced, just apparently not noticed until now.
- Fix: removed the dead `.toggle::after` rule from `frontend-src/style.css`
  (the JS-managed `span.dot` already owns 100% of the toggle's visuals —
  position, color, and transition — so nothing else needed to change).
  Rebuilt `static/index.html` via `python3 build.py` and confirmed the
  removed rule doesn't appear in the compiled output.

### Note
Couldn't render/screenshot the fix in an actual browser from this
environment (no browser tooling available here) — worth a quick visual
check on the live VM after deploy, same caveat as the mobile-layout/
dark-mode session's changes.

## 2026-09-17 (bug fix: users could be left with zero workspace accounts after per-user isolation)

### Fixed
- **Real risk of users being locked out of a fully broken app.** Auditing
  the 2026-09-14 per-user isolation commit (`55f798d`) found that its
  one-time `backfill_account_ownership()` migration assigns every
  pre-existing (orphaned) workspace account to a single earliest-created
  user. Multi-user login (Decision 004) had been live for two days before
  isolation (Decision 006) shipped — if a second real person had already
  signed up in that window and was using the shared account, the
  migration would have left them owning zero accounts. That's worse than
  a missing feature: `frontend-src/app.js`'s account switcher falls back
  to `account_id=1` when its cache is empty, so that person's dashboard,
  library, platforms, and upload pages would all 404 on every request,
  since account 1 now belongs to someone else.
- Added `ensure_user_has_account(user_id, username)` (`app/auth.py`),
  called from `require_login` on every authenticated request (not just
  login/signup), so any user who somehow ends up owning zero accounts —
  now or in the future — gets a fresh one automatically on their very
  next request. This self-heals an already-active session too; it
  doesn't require the person to log out and back in.
- `POST /api/auth/signup` now calls this same helper instead of
  duplicating the "create a starter account" logic inline.
- Fixed a stale module docstring in `app/auth.py` left over from before
  Decision 006 — it still described workspace accounts as shared across
  every logged-in user with "no per-user restriction," which has been
  false since the isolation commit.

### Note for the project owner
If a second person actually did sign up between 2026-09-12 (Decision 004)
and 2026-09-14 (Decision 006) and was relying on access to the original
shared account, this fix gives them a working app again on their next
request, but with a **fresh, empty account** — it does not and cannot
restore their access to the original account's history, since there's no
record of who was using it under the old shared model. Worth checking
your `users` table for any account created in that window that you don't
recognize, and manually reviewing whether they need anything recovered
from the original account (currently only possible via direct DB access
— see the open TODO item for an admin UI to reassign account ownership).

### Verified
- `pyflakes app/ server.py` — clean.
- Reproduced the exact failure: simulated two users who already existed
  before the isolation migration ran (one shared account), confirmed the
  second user got `[]` from `/api/accounts` pre-fix, then confirmed
  post-fix that same user's very next request (no fresh login) returns a
  new account of their own and `/api/dashboard/summary` for it returns
  200 — while the original owner's account and access are unaffected.
- Re-ran the full 2026-09-14 isolation regression suite (two-user cross-
  access, delete-last-account guard, publish/library smoke test) — still
  all passing.

## 2026-09-17 (fix: Accounts page mobile layout; feature: real dark mode)

### Fixed
- `.account-row` (Accounts page) had no wrap/stacking behavior — icon,
  name, "Active" pill, Rename button, and Delete button were all forced
  onto one unbreakable flex line. On narrow screens this overlapped and
  wrapped mid-word (reported via live screenshots from a session that hit
  its usage limit mid-task). Fix: wrapped the pill + buttons in a new
  `.acc-row-actions` container (`frontend-src/app.js`) so it can be
  targeted independently in CSS; on `max-width:720px` it now drops to its
  own full-width, right-aligned row under the icon+name, with a divider
  between account rows.

### Added
- Real dark mode. Previously `#darkToggle`'s click handler only changed
  the toggle's own dot color — no theme was ever applied anywhere.
  - Added `html.dark-theme{...}` in `frontend-src/style.css` overriding
    the existing theme CSS variables (`--page-bg`, `--card-bg`,
    `--border`, `--text-dark/mid/light`, plus new `--hover-bg`,
    `--active-bg`, `--danger-hover-bg`).
  - Converted ~15 previously-hardcoded `#fff`/`#f5f6fa`/`#f1f2f6`/etc
    surfaces (topbar, account dropdown panel, notifications drawer, video
    metrics modal, Accounts page buttons, Analytics pill/select controls)
    to use those variables — without this, dark mode would only have
    reached the small subset of elements already using `var(--card-bg)`.
  - `frontend-src/app.js`: `darkToggle` now toggles a `dark-theme` class
    on `<html>` (not `<body>` — chosen so the flash-prevention script
    below can run before `<body>` exists) and persists the choice to
    `localStorage` under `mf-dark-theme`. Also removed a dead, never-called
    `paint()` function that was left over in the same toggle-wiring block.
  - `frontend-src/layout.html`: added a small inline script as the first
    thing in `<head>` (ahead of the stylesheet) that applies the saved
    class before first paint, so reloading in dark mode doesn't flash
    light-then-dark.

### Known limitation (see TODO.md)
- Small semantic-tinted badges (gain-pill, pub-pill.sched/.fail,
  notif.warn) still use their light-mode colors in dark mode — low visual
  impact, not addressed this session.

Modified By:
Claude (via chat session, continuing from a different session that hit
its usage limit mid-task — see screenshots referenced above)

---

## 2026-09-14 (feature: per-user data isolation for workspace accounts)

### Added
- `accounts.user_id` column — every workspace account (docs/DECISIONS.md
  003) is now owned by exactly one logged-in user (docs/DECISIONS.md 004).
  See docs/DECISIONS.md 006 for the full writeup, alternatives considered,
  and what's still open.
- `app/db.py`: `backfill_account_ownership()` (assigns any pre-existing
  account with no owner to the earliest-created user, run once at startup
  after the legacy-user seed step) and `create_workspace_account(name,
  user_id)` (shared helper for manual account creation and the new
  auto-created signup account below).
- `POST /api/auth/signup` now also creates one default workspace account
  for the new user, so a fresh signup isn't dropped into an empty account
  switcher.

### Changed
- `app/auth.py`: `require_login` now returns `{"id", "username"}` instead
  of just the username string, so route handlers can check account
  ownership. Every existing `Depends(require_login)` call site's type hint
  was updated (`str` → `dict`); the one place that used the return value
  directly (`GET /api/auth/me`) now reads `user["username"]`.
- `app/credentials.py`: `get_account_or_404(account_id, user_id)` now
  takes the requesting user's id and 404s if the account either doesn't
  exist or belongs to someone else — same response in both cases, so
  account IDs can't be probed.
- Every account-scoped endpoint now checks ownership before doing anything
  with the `account_id` it was given: `/api/status`, `/api/publish`,
  `/api/library`, `/api/dashboard/summary`, YouTube connect, Facebook
  connect, all four Facebook/Instagram/YouTube analytics routes, and
  accounts list/create/rename/delete.
- `list_accounts` (`GET /api/accounts`) now filters to the requesting
  user's own accounts instead of returning every account on the install.
- `delete_account`'s "can't delete your last account" guard now counts
  only the requesting user's own accounts, not every account across every
  user — the previous global count was a real bug once more than one user
  existed (a user could be blocked from deleting their last account
  because *other* users had accounts, or allowed to delete their only one
  because the global count looked fine).

### Fixed
- `disconnect_youtube` and `disconnect_facebook` previously never
  validated `account_id` at all (flagged in TODO.md) — silently no-op'd on
  a bad or someone-else's account_id instead of 404ing. Now go through the
  same ownership check as every other account-scoped route.

### Verified
- `pyflakes app/ server.py` — clean, no undefined names or unused imports.
- Two-user isolation test (fresh `FastAPI TestClient` per user, real
  signup flow): confirmed a second user gets a 404 attempting to reach the
  first user's account via `account_id` on every account-scoped route
  (`/api/library`, `/api/dashboard/summary`, `/api/status`, accounts
  rename/delete, Facebook connect/disconnect, YouTube connect, both
  Facebook and YouTube analytics endpoints), while each user's own account
  continues to work normally (200s).
- Legacy-upgrade test: hand-built a pre-migration SQLite DB matching a
  real production install (an `accounts` table with no `user_id` column,
  one pre-existing user). Confirmed on startup the existing account gets
  correctly backfilled to that pre-existing user, that user keeps full
  access to their existing account/data exactly as before, and a brand-new
  signup afterward gets its own separate account and a 404 when trying to
  touch the legacy account.
- Smoke test of previously-working flows on an isolated account: immediate
  publish, scheduled publish, `/api/library` (all + status-filtered),
  `/api/dashboard/summary` — all still behave as before.
- Delete-account behavior specifically: confirmed a user with one account
  is blocked from deleting it (400), and can delete it once they have two.

## 2026-09-14 (bug fix: missing datetime import in app/routes/analytics_meta.py)

### Fixed
- `app/routes/analytics_meta.py` — the file-architecture split earlier
  today (commit "Split server.py and static/index.html into per-concern
  files") moved the Facebook/Instagram analytics endpoints out of
  `server.py` but dropped the `from datetime import datetime, timedelta,
  timezone` import that the original monolithic file had. Both
  `/api/analytics/facebook` and `/api/analytics/instagram` used
  `datetime`/`timedelta`/`timezone` unconditionally right after their
  first real Graph API call — so any account with Facebook/Instagram
  actually connected would get a real response back from Meta and then
  hit an immediate `NameError` (500) on every request to either
  endpoint. Restored the import.

### Why this wasn't caught before merging
The split's own regression test (28/28 checks matched, per that
commit's message) ran in this dev environment, which has no real
Facebook Page credentials — `get_facebook_credentials()` returns `None`
here, so both endpoints short-circuit to a 401 *before* ever reaching
the line that uses `datetime`. The bug was invisible to any test that
doesn't have a live Facebook/Instagram connection to exercise past that
guard clause.

### Verification
- `python3 -m pyflakes app/ server.py build.py` — confirmed this was
  the *only* undefined-name issue across the entire split (everything
  else compiles clean).
- `python3 -m py_compile` on every file under `app/` — all pass.
- Diffed this commit (`0793280`, the split) against the prior
  monolithic `server.py` to confirm the import genuinely existed before
  and was dropped during the refactor, not a pre-existing bug.
- Ran both endpoints end-to-end via FastAPI's `TestClient` with
  `_graph_get` mocked to return realistic Facebook/Instagram Graph API
  payloads (bypassing the sandbox's lack of real network access to
  graph.facebook.com) — both returned `200` with correctly-shaped data
  after the fix; both would have 500'd before it.
- Rebuilt `static/index.html` via `build.py` and confirmed it's
  byte-for-byte unchanged (this fix is backend-only).

Modified By:
Claude (via chat session)

---

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

---

## 2026-09-20 (Instagram publish failure diagnosis + error surfacing)

### Fixed
- `app/uploaders.py` — `_upload_to_instagram()`'s processing-failure branch
  only reported the generic `status_code == "ERROR"` and discarded Graph
  API's actual `status` field, which carries the real reason (bad aspect
  ratio, duration, codec, file size, etc.). Now requests and surfaces both,
  so a future failure is actually diagnosable instead of a dead end.
- `frontend-src/style.css` — the `.toast` error banner had no `max-width`,
  so a longer error message (like the one above now produces) could
  overflow the screen instead of wrapping. Added a bounded max-width and
  word-wrapping.

Reason:
Project owner published a video that succeeded on YouTube and Facebook but
failed on Instagram with only "Instagram failed to process the video." —
not enough detail to know why. Traced the failure to Instagram's own
processing step (the public-URL fetch itself succeeded, ruling out a
network/nginx cause), but the code was throwing away the one piece of
information that would explain it.

Verified:
- `python3 -m py_compile` on the changed file
- `node --check` on the rebuilt static/index.html's JS
- Confirmed via code inspection that this specific video's actual failure
  reason can't be retroactively recovered (the temp file is deleted right
  after each publish attempt) — flagged the common Reels rejection causes
  (aspect ratio, duration, codec, file size) for the project owner to
  check against that file directly

Not fixed here (out of scope, just noted): two other minor issues found
during an unrelated commit-comparison audit earlier this session
(`.manage-btn` dark-mode background, a stale `?page=` OAuth redirect) had
already been fixed by other work that landed in between — confirmed both
are resolved in the current codebase, no action needed.

Deployed:
Pushed to `main`, triggering the GitHub Actions auto-deploy.

Modified By:
Claude (via chat session)
