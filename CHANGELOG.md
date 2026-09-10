# Changelog

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
