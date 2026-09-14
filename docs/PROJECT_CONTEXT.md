# Project Context

## Project Name
MediaFlow — Self-hosted multi-platform video publishing dashboard

## Purpose
A local/self-hosted tool for scheduling and publishing videos across multiple
social platforms from one dashboard, instead of paying for a SaaS scheduler
(Buffer/Hootsuite-style, but self-hosted).

## Technologies

Backend:
- Python, FastAPI. `server.py` only wires the app together (app creation,
  middleware, startup, mounting routes); the actual logic lives under
  `app/` — see "File architecture" below.
- SQLite (local DB, no external DB server)

Frontend:
- Single-page app, plain HTML/JS. Shipped as one file (`static/index.html`,
  what the server actually serves), but *edited* as separate files under
  `frontend-src/` (one file per page, plus CSS and JS) — see "File
  architecture" below. Two standalone pages outside the SPA for auth
  (`static/login.html`, `static/signup.html`) are small enough to just
  edit directly — not part of the frontend-src build.

Deployment:
- Designed to run as a systemd service (`mediaflow.service`) behind nginx
  (`mediaflow.nginx.conf`), or locally for dev
- Real multi-user login built in (session cookies, own Sign In/Sign Up
  pages) for when exposed on a public VM — see Decision 004

## Architecture (high level)

```
Frontend (static/index.html)
        │  HTTP requests
        ▼
FastAPI server (server.py)
        │
        ├── SQLite DB — accounts, scheduled posts, tokens metadata
        ├── Scheduler loop (_scheduler_loop) — polls every 30s,
        │     fires publish calls when a post's scheduled time arrives
        └── Platform integrations:
              ├── YouTube  — Google OAuth, real upload API
              ├── Facebook — Page Access Token (manual paste-in)
              └── Instagram — rides on the Facebook Graph API connection
              (TikTok — stubbed in UI, not implemented)
```

## File architecture

Backend (`server.py` + `app/`) — one file per concern, split via FastAPI
`APIRouter`s (see docs/DECISIONS.md 005):

```
server.py                    app creation, middleware, startup, static mount
app/config.py                shared paths + env-derived settings
app/db.py                    SQLite persistence (init, migrations, CRUD)
app/auth.py                  multi-user login (password hashing, sessions)
app/credentials.py           per-account (workspace) credential storage
app/uploaders.py             YouTube/Facebook/Instagram upload calls
app/scheduler.py             background scheduled-post poller
app/routes/status_publish.py     /api/status, /api/publish
app/routes/library.py            /api/library, /api/dashboard/summary
app/routes/accounts.py           /api/accounts (list/create/rename/delete)
app/routes/analytics_youtube.py  /api/analytics/summary, /video/{id}
app/routes/analytics_meta.py     /api/analytics/facebook*, /instagram*
app/routes/youtube_oauth.py      YouTube OAuth connect/callback/disconnect
app/routes/facebook_connect.py   Facebook connect/disconnect
app/routes/media.py              /media/{filename} (Instagram fetch URL)
app/routes/auth_pages.py         /login, /signup, /api/auth/*
```

Frontend (`frontend-src/` → built into `static/index.html`, see
docs/DECISIONS.md 005):

```
frontend-src/layout.html     shared shell — <head>, sidebar, notifications
                              drawer, topbar
frontend-src/style.css       all CSS
frontend-src/app.js          all JavaScript
frontend-src/pages/*.html    one file per page (dashboard, accounts,
                              platforms, scheduled, published, analytics,
                              settings, help, upload)
build.py                     assembles the above into static/index.html —
                              run after any frontend-src/ edit; CI also
                              runs it automatically on push (deploy.yml)
```

`static/index.html` itself is now a **generated file** — it's what the
server actually serves and what's committed to git (so the repo always
reflects what's live even if someone forgets to run the build locally),
but edits should go through `frontend-src/` and `python3 build.py`, not
the generated file directly. `static/login.html` and `static/signup.html`
are NOT part of this build — they're standalone pages, edit them directly.

Credentials (`credentials/accounts/<id>/token.json`, `.../facebook.json`,
plus a shared `credentials/client_secret.json`) are stored as local JSON
files and are gitignored — they do NOT sync via git. Each machine/session
needs them supplied separately.

## Current Status
- Authentication (multi-user login: session cookies, Sign In/Sign Up
  pages, hashed passwords — see Decision 004): done
- YouTube publishing: working (OAuth + upload + analytics)
- Facebook publishing: working (token-based)
- Instagram publishing: working (via Facebook Graph API)
- TikTok: not implemented (UI stub only)
- Scheduler: working, polls every 30s, designed to catch up on restart
- Analytics: working for YouTube (views/watch time/retention) and
  FB/IG (reach/drop-off/saves), with 7/28/90-day windows

## Important Rules
- Do not change the database schema without recording it in DECISIONS.md
- Do not remove existing working functionality without explicit request
- Do not commit anything under `credentials/` — it's gitignored for a reason
  (this repo already had a secret-scanning incident — see DECISIONS.md 001)
- Update CHANGELOG.md and SESSION_HANDOFF.md after any meaningful change
- Check `git diff` / `git log` for what actually changed before writing
  changelog or handoff entries — don't document from memory
