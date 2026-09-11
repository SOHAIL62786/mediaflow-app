# Changelog

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
