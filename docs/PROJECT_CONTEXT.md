# Project Context

## Project Name
MediaFlow — Self-hosted multi-platform video publishing dashboard

## Purpose
A local/self-hosted tool for scheduling and publishing videos across multiple
social platforms from one dashboard, instead of paying for a SaaS scheduler
(Buffer/Hootsuite-style, but self-hosted).

## Technologies

Backend:
- Python, FastAPI (`server.py`)
- SQLite (local DB, no external DB server)

Frontend:
- Single-page app, plain HTML/JS (`static/index.html`)

Deployment:
- Designed to run as a systemd service (`mediaflow.service`) behind nginx
  (`mediaflow.nginx.conf`), or locally for dev
- HTTP Basic Auth built in for when exposed on a public VM

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

Credentials (`credentials/token.json`, `credentials/client_secret.json`,
Facebook page tokens) are stored as local JSON files and are gitignored —
they do NOT sync via git. Each machine/session needs them supplied separately.

## Current Status
- Authentication (HTTP Basic Auth for the app itself): done
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
