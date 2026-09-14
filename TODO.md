# TODO

## High Priority
- [ ] Sign-up is fully open to anyone who reaches the URL (project
      owner's explicit choice) — if that turns out to be too permissive,
      add an optional `SIGNUP_CODE` env var gate: if set, require a
      matching invite code on the signup form; if unset, stays fully
      open as it is now. Not built since it wasn't requested.
- [ ] No admin UI yet to list/remove users, force a password reset, or
      manually reassign a workspace account's owner — currently needs
      direct DB access (`users`/`sessions`/`accounts` tables). Consider a
      simple Settings-page panel. (See docs/DECISIONS.md 004 and 006.)
- [ ] Decide how the background scheduler should scale once there are many
      accounts with due posts — currently iterates every due row across all
      accounts each poll; untested at scale
- [ ] Decide whether TikTok support is still a near-term goal; if so, scaffold
      OAuth connect route + DB fields now so UI/schema don't need retrofitting

## Medium Priority
- [ ] Lock down CORS (`allow_origins=["*"]`) to the actual frontend origin
      before any public-VM deployment
- [ ] Add cleanup sweep on startup for orphaned files in the temp media dir
      (in case a crash happens between publish and delete)
- [ ] Add retry/backoff for transient platform API failures during
      scheduled publish, instead of failing permanently on first error

## Low Priority
- [ ] Consider a "dry run" / preview mode before a scheduled post fires
- [ ] `account_id` in the YouTube OAuth callback's redirect URL is never
      actually read by the frontend (only `page` is) — works today only
      because localStorage already holds the right account before the
      redirect; make this explicit/robust instead of relying on that
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
- [ ] The `analytics_meta.py` missing-import fix (2026-09-14) was only
      verified against a mocked Graph API (this dev environment has no
      real Facebook Page credentials and can't reach graph.facebook.com)
      — worth a quick real-account check on the live VM to be thorough.
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
- [x] HTTP Basic Auth for app access (superseded 2026-09-12 — see below)
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
- [x] Bug audit of the last several sessions' changes + mobile alignment
      check via headless-browser rendering; found and fixed a real bug
      where collapsing the sidebar on desktop broke the mobile hamburger
      menu (2026-09-11)
- [x] Replaced HTTP Basic Auth with real multi-user login: custom Sign
      In/Sign Up pages, hashed passwords, session cookies — see
      Decision 004 (2026-09-12)
- [x] Fixed video/upload row layout breaking on long or mixed-script
      titles (thumbnail/button misalignment from align-items:center
      against an unbounded-height title) — reported via live screenshot,
      fixed with 2-line title clamp + top-alignment (2026-09-12)
- [x] File-architecture split (server.py → app/ package + routers;
      static/index.html → frontend-src/ + build.py) — pushed to main and
      live (was pushed by a different session/account than the one that
      wrote it). See docs/DECISIONS.md 005 and SESSION_HANDOFF.md (2026-09-14)
- [x] Fixed a real regression from that split: `app/routes/analytics_meta.py`
      dropped the `datetime`/`timedelta`/`timezone` import the original
      code had, causing a 500 on `/api/analytics/facebook` and
      `/api/analytics/instagram` for any account with those platforms
      actually connected. See CHANGELOG.md (2026-09-14)
- [x] Confirmed scheduler behavior when a scheduled video file is missing
      at publish time: it already fails loudly and correctly — marks the
      row `failed` with a clear per-platform error, sets `video_path` to
      NULL, and (since the poll query only selects `status = 'scheduled'`)
      never retries it again on later polls. Verified empirically by
      queuing a row pointing at a nonexistent file, running the poll
      twice, and confirming it goes `failed` once and stays `failed`
      (2026-09-14) — no code change was needed, this was already correct
- [x] Full feature-regression audit of the file-architecture split
      (comparing the pre-split monolith against the post-split `app/` +
      `frontend-src/` across all 27 routes, all 61 functions body-by-body,
      every module-level constant, the full static/index.html output, and
      the CI workflow) — confirmed nothing else was lost beyond the
      `analytics_meta.py` import above (2026-09-14)
- [x] Per-user data isolation: workspace accounts now belong to exactly
      one user (new `accounts.user_id`), every account-scoped endpoint
      checks ownership (404 if not yours), `list_accounts` only returns
      your own, and a new signup gets its own default account instead of
      the old shared pool. Fixed a real bug found along the way
      (`delete_account`'s "last account" check was counting globally
      instead of per-user) and a pre-existing gap (`disconnect_youtube`/
      `disconnect_facebook` not validating `account_id`). See
      docs/DECISIONS.md 006 and CHANGELOG.md (2026-09-14)
