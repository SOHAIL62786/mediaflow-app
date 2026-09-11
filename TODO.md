# TODO

## High Priority
- [ ] Decide how the background scheduler should scale once there are many
      accounts with due posts — currently iterates every due row across all
      accounts each poll; untested at scale
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
- [ ] `account_id` in the YouTube OAuth callback's redirect URL is never
      actually read by the frontend (only `page` is) — works today only
      because localStorage already holds the right account before the
      redirect; make this explicit/robust instead of relying on that
- [ ] `disconnect_youtube` / `disconnect_facebook` don't validate the
      account exists (unlike connect/rename/delete) — silently no-op
      instead of 404ing on a bad account_id
- [ ] Notifications drawer is populated from the dashboard-summary fetch
      only (failed uploads + recent activity) — there's no dedicated
      notifications endpoint/read-state, so it always shows the same
      items as the dashboard and can't be marked "read". Consider a real
      `/api/notifications` source if this needs to grow (e.g. persisted
      read/unread, more event types) beyond a dashboard-derived view.
- [ ] Sidebar collapse/resize state is per-browser (`localStorage`), not
      per-account or server-synced — fine for a single user, would need
      revisiting if this is ever multi-user beyond the shared login.
- [ ] Subscriber/follower counts in the dashboard platform bar haven't
      been visually verified against a real connected account (no
      credentials available in the dev/session environment) — check on
      the live VM.
- [ ] Same for the new YouTube Analytics "Today" filter and per-video
      lifetime/period view counts — verify against a real connected
      YouTube channel with recent uploads.
- [ ] Facebook/Instagram Analytics still can't show "which posts got
      views today" the way YouTube now can — Meta's Graph API doesn't
      expose a per-day, per-video/media view breakdown, only lifetime
      totals at the video/media level. Would need a different approach
      (e.g. periodic snapshotting + diffing) if this is wanted later.

## Completed
- [x] Core FastAPI server with SQLite backend
- [x] YouTube OAuth + upload + analytics
- [x] Facebook publishing via Page Access Token
- [x] Instagram publishing via Facebook Graph API
- [x] Scheduler loop (30s poll, catch-up on restart)
- [x] HTTP Basic Auth for app access
- [x] nginx config + systemd service file for deployment
- [x] Documentation/handoff system set up (2026-09-10)
- [x] Multi-account support: independent platform connections, posts, and
      analytics per account, switched via top-right dropdown (2026-09-10)
- [x] Add UI to rename/delete an account, on a new dedicated Accounts page;
      old combined "Accounts" (platform-connect) page renamed to
      "Platforms" (2026-09-11)
- [x] Make dashboard stat cards + platform tiles clickable (navigate to
      their respective page); add a right-side notifications drawer;
      make sidebar collapsible + drag-resizable (2026-09-11)
- [x] Show subscriber/follower counts in the dashboard's platform bar
      for YouTube/Facebook/Instagram (2026-09-11)
- [x] Add a "Today" period option to YouTube Analytics, showing only
      videos with views today plus their lifetime total + period gain
      (2026-09-11)
