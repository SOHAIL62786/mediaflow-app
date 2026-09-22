# TODO

## High Priority
- [ ] **Pull the live VM's nginx config back into this repo.** After the
      2026-09-20 HTTPS outage (docs/DECISIONS.md 011), certbot re-added
      its `listen 443 ssl` block directly on the VM — that block still
      isn't reflected in `mediaflow.nginx.conf` here. Run `diff
      mediaflow.nginx.conf /etc/nginx/sites-available/mediaflow` on the VM
      and fold the SSL block into this file, so the repo stops being an
      incomplete picture of the real live config.
- [ ] **Check the `users` table for anyone who signed up between**
      **2026-09-12 and 2026-09-14** (before per-user isolation shipped)
      **and verify they don't need data recovered.** The isolation
      migration would have assigned any pre-existing shared account
      solely to the earliest-created user; a fix on 2026-09-17 stops
      anyone from being left with zero accounts going forward (see
      docs/DECISIONS.md 007), but can only give a second person a fresh
      empty account, not their old data back. Needs a human to check —
      not resolvable by looking at the code.
- [ ] Sign-up is fully open to anyone who reaches the URL (project
      owner's explicit choice). An optional `SIGNUP_CODE` env var gate is
      now built and ready if that ever turns out to be too permissive —
      unset by default (nothing changes unless you opt in). See
      docs/DECISIONS.md 009 for how to turn it on.
- [ ] Decide how the background scheduler should scale once there are many
      accounts with due posts — currently iterates every due row across all
      accounts each poll; untested at scale
- [ ] Decide whether TikTok support is still a near-term goal; if so, scaffold
      OAuth connect route + DB fields now so UI/schema don't need retrofitting

## Medium Priority
- [ ] True mid-upload cancel (2026-09-20 follow-up). The new publish
      progress panel's Cancel is cooperative only — it stops the job
      before the *next* platform step starts, but can't interrupt a
      platform upload already in flight. YouTube's resumable upload API
      could support real interruption; Facebook/Instagram's Graph API
      publish calls are likely all-or-nothing once started — worth
      confirming before promising more than "abandon the local wait."
- [ ] Lock down CORS (`allow_origins=["*"]`) to the actual frontend origin
      before any public-VM deployment
- [ ] Add cleanup sweep on startup for orphaned files in the temp media dir
      (in case a crash happens between publish and delete)
- [ ] Add retry/backoff for transient platform API failures during
      scheduled publish, instead of failing permanently on first error

## Low Priority
- [ ] The new live publish progress panel (2026-09-20) was only verified
      by exercising the job registry logic directly (create/ownership/
      step updates/cancel/finish, all pass) and a clean rebuild — not an
      actual real-account publish through the UI in a browser. Check on
      the live VM: panel opens on Publish Now, steps update live, Cancel
      actually stops the next not-yet-started step, panel Close doesn't
      kill the job.
- [ ] Dark mode (2026-09-17) covers all major surfaces (cards, topbar,
      dropdowns, notif drawer, modal, buttons) via theme variables, but
      small semantic-tinted badges (gain-pill, pub-pill.sched/.fail,
      notif.warn) were deliberately left with their light-mode colors —
      they'll look slightly washed out on a dark card. Low visual impact,
      not fixed yet.
- [ ] Consider a "dry run" / preview mode before a scheduled post fires
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
- [ ] The Instagram ffmpeg re-encode-and-retry fallback (2026-09-20,
      Decision 012) was only verified against a mocked Graph API and a
      synthetic test video with the same characteristics as the real
      failing one — needs confirming on the live VM: (1) `ffmpeg` is
      actually installed there (`sudo apt install ffmpeg` per
      DEPLOYMENT_GUIDE.md), (2) the specific video that was failing
      (`0919.mp4`, CapCut export, H.264 High profile) actually publishes
      successfully now via the app, not just via the standalone
      `upload_reel.py` script.
- [ ] Facebook/Instagram Analytics still can't show "which posts got
      views today" the way YouTube now can — Meta's Graph API doesn't
      expose a per-day, per-video/media view breakdown, only lifetime
      totals at the video/media level. Would need a different approach
      (e.g. periodic snapshotting + diffing) if this is wanted later.

## Completed
- [x] Save as Draft / Save as Template for the Upload form (2026-09-21).
      New `upload_presets` table (one table, `kind` column, rather than
      two — see Decision 013), full CRUD via `/api/upload-presets`,
      account-scoped like everything else. Drafts are unnamed/one-shot
      (Resume populates the form then deletes the draft); templates are
      named/reusable (Apply populates the form, doesn't delete).
      Deliberately doesn't store a video file — see Decision 013 for why.
      Backend verified via curl (CRUD, validation, cross-user isolation,
      account-delete cleanup); frontend verified with a headless-browser
      walkthrough on desktop + mobile.
- [x] Live upload progress panel with cancel — Publish Now opens a
      slide-in panel with a step per selected platform
      (pending → active → done/failed, real per-platform error shown
      inline). Backend: `/api/publish` now returns a `job_id` immediately
      instead of blocking, via an in-memory job registry
      (`app/publish_jobs.py`); `GET /api/publish/jobs/{id}` polls status,
      `POST .../cancel` requests cancellation (cooperative — see Medium
      Priority follow-up above). Each platform upload now runs via
      `asyncio.to_thread()`, which also fixes a pre-existing issue where
      the whole server blocked for the full duration of any publish call.
      Commit `b88e9c8` (2026-09-20)
- [x] Instagram publishing (immediate and scheduled) now automatically
      re-encodes with ffmpeg and retries once when Instagram's own
      processing step rejects a video (undocumented error, e.g. code
      2207077) — but only for that specific failure mode, not for
      auth errors or processing timeouts. See docs/DECISIONS.md 012
      (2026-09-20)
- [x] Admin panel: an admin can list users, force a password reset,
      promote/demote admins, delete a user (once they own no accounts),
      and reassign a workspace account's owner. `is_admin` granted only
      to the single earliest-created user by default. Reviewed and
      approved by the project owner before push. See docs/DECISIONS.md
      010 (2026-09-18)
- [x] Built the optional `SIGNUP_CODE` invite-gate for signup (env var,
      unset by default so nothing changes unless the project owner opts
      in) — see docs/DECISIONS.md 009. Also fixed a stale claim on the
      signup page ("everyone shares the same dashboard") left over from
      before per-user isolation shipped (2026-09-18)
- [x] Fixed two bugs found in an audit (undocumented at the time by the
      session that made them — reconciled here): `.manage-btn` (Accounts
      "Add account", Upload "Manage Platforms") was still hardcoded white
      in dark mode, missed in the earlier dark-mode pass; and the YouTube
      OAuth callback redirected to the old `/?page=platforms&account_id=X`
      scheme instead of the new `/platforms` path — the `account_id` param
      was already dead (frontend reads the active account from
      `localStorage`, not the URL) so it was simply dropped. Commit
      `6f58833` (2026-09-17)
- [x] Added a loading skeleton for the dashboard's platform
      subscriber/follower counts, which previously stayed blank with no
      indication anything was loading; also fixed the fetch-failure path,
      which left the skeleton shimmering forever on error. Commit
      `7d53e80` (2026-09-17)
- [x] Switched page URLs from `?page=xxx` query strings to real paths
      (`/dashboard`, `/accounts`, etc.) — each now a real server route so
      a hard refresh/bookmark/shared link works; old `?page=xxx` links
      still work once and self-normalize. See docs/DECISIONS.md 008
      (2026-09-17)
- [x] Fixed toggle switches (dark-mode toggle, Upload page's customize
      toggle) showing two overlapping dots when on — a dead CSS
      `::after` pseudo-element was left drawing a static dot on top of
      the real JS-managed one. Reported by project owner with a
      screenshot (2026-09-17)
- [x] Fixed a real bug in the 2026-09-14 per-user isolation change: any
      user who ended up owning zero accounts (possible for anyone who'd
      already signed up in the two-day window before isolation shipped)
      would hit a fully broken app — every page 404ing via the frontend's
      account_id=1 fallback. `require_login` now guarantees every
      authenticated request has a user with ≥1 account, self-healing even
      an already-active session. See docs/DECISIONS.md 007. Flagged a
      High Priority item above for the project owner to manually check
      whether anyone was actually affected (2026-09-17)
- [x] Fixed Accounts page mobile layout: the Active pill + Rename/Delete
      buttons were overlapping the account name on narrow screens (no
      wrap/stacking behavior existed). Also implemented actual dark mode —
      the toggle previously only changed its own dot color and did nothing
      else; now applies a real dark theme, persists via localStorage, and
      avoids a flash on reload (2026-09-17)
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
- [x] Instagram publish failure now surfaces Graph API's actual `status`
      detail instead of just the generic "failed to process" message; also
      fixed the error toast overflowing on long messages (2026-09-20)
- [ ] Project owner to check the video that failed on Instagram against
      Reels' actual requirements (vertical aspect ratio, duration limits,
      H.264/AAC codec, ~1GB file size cap) — the specific failure reason
      for that video couldn't be recovered since the temp file is deleted
      right after each publish attempt; next failure will show the real
      reason now (2026-09-20)
- [x] Upload page: removed Connected Accounts and Publishing Tips panels;
      added a History tab (auto-logs every submitted publish form, popup
      with Use/Delete). See docs/DECISIONS.md 014 (2026-09-22)
