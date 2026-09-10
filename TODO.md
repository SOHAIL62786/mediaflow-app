# TODO

## High Priority
- [ ] Decide whether TikTok support is still a near-term goal; if so, scaffold
      OAuth connect route + DB fields now so UI/schema don't need retrofitting
- [ ] Harden default-password behavior: currently prints a warning if
      `APP_PASSWORD` is left as `change-me-now`; consider refusing to start
      on `0.0.0.0` with the default instead of just warning

## Medium Priority
- [ ] Lock down CORS (`allow_origins=["*"]`) to the actual frontend origin
      before any public-VM deployment
- [ ] Add cleanup sweep on startup for orphaned files in the temp media dir
      (in case a crash happens between publish and delete)
- [ ] Add retry/backoff for transient platform API failures during
      scheduled publish, instead of failing permanently on first error
- [ ] Confirm scheduler behavior when a scheduled video file is missing at
      publish time (should fail loudly + mark row failed, not hang/retry
      forever silently)

## Low Priority
- [ ] Consider a "dry run" / preview mode before a scheduled post fires

## Completed
- [x] Core FastAPI server with SQLite backend
- [x] YouTube OAuth + upload + analytics
- [x] Facebook publishing via Page Access Token
- [x] Instagram publishing via Facebook Graph API
- [x] Scheduler loop (30s poll, catch-up on restart)
- [x] HTTP Basic Auth for app access
- [x] nginx config + systemd service file for deployment
- [x] Documentation/handoff system set up (2026-09-10)
