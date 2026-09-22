# Session Handoff

## Last Updated
2026-09-22

## 2026-09-22 (latest): Upload page cleanup + publish History
Removed the Connected Accounts and Publishing Tips panels from the Upload
page sidebar (per project owner request — Connected Accounts duplicated
the Platforms page). Added a third "History" tab next to Drafts/Templates
that auto-saves every form submitted to /api/publish (any outcome), capped
at 50 entries/account, with a popup (Use/Delete) instead of inline row
buttons. Full detail in CHANGELOG.md's 2026-09-22 entry and
docs/DECISIONS.md 014.

Note: used the existing pill-button tab style for History rather than a
literal `<input type="radio">`, matching Drafts/Templates — project owner
asked for "one more radio button" but the existing UI convention here is
pill-tabs, not native radios; flagged this substitution to them, no
pushback received yet.

## 2026-09-21 (latest): Save as Draft / Save as Template

Worked from TODO.md's own High Priority #1 (written 2026-09-20). Full
detail in CHANGELOG.md's matching entry and docs/DECISIONS.md 013 —
summary here.

New `upload_presets` table backs both drafts and templates — one table
with a `kind` column ('draft'/'template') rather than two, since they
turned out to be the same shape of data (title/caption/tags/platforms/
privacy/checkboxes) with different lifecycles, not different schemas.
New `app/routes/upload_presets.py` (list/create/delete), account-scoped
and ownership-checked the same way as every other account-scoped route.
Account deletion now also cleans up its presets.

Frontend: Upload page gets "Save as Draft"/"Save as Template" buttons
under Video Details, and a new "Drafts & Templates" card in the sidebar
with a tab switcher. Applying a template populates the form without
deleting it; resuming a draft populates the form AND deletes it
afterward (drafts are one-shot, consumed once acted on). Template names
go through a `prompt()`, matching the existing rename-account pattern.

Deliberately does NOT store a video file with a draft/template — see
Decision 013 for the full reasoning (avoids a much bigger file-storage/
cleanup feature; keeps Resume/Apply a pure frontend action that reuses
the existing `/api/publish` flow untouched). This was the one open
design question the TODO item itself flagged, so it's worth a second
look if "resume with the file already attached" turns out to matter in
practice.

Verified: full CRUD lifecycle, template-name-required validation,
empty-title-and-caption rejection, and cross-user ownership isolation
(404, matching the existing pattern) via curl against a running server;
confirmed zero orphaned `upload_presets` rows after deleting an account
that had some. Frontend verified with a headless-browser walkthrough on
both desktop and mobile viewports — save/apply/resume/delete all
behaving correctly, no console errors, no horizontal overflow. No
external platform API involved in this feature at all, so (unlike most
recent sessions' changes) there's no "unverified against a real
connected account" caveat here — this one doesn't depend on YouTube/
Facebook/Instagram credentials to work correctly.

Not done: nothing else from the requested item was left out. The
account_id/session flow, DB writes, and frontend state all match the
same conventions used elsewhere in this codebase (checked against
accounts.py and library.py before writing anything new).

---

## 2026-09-20: Live upload progress panel with cancel

Worked from TODO.md's own High Priority #1, written by an earlier session
today. Full detail in CHANGELOG.md's matching entry and TODO.md's
Completed section — summary here.

Publish Now now opens a slide-in panel (reuses the notifications drawer's
shell) with a step per selected platform, live pending/active/done/failed
state, and a real per-platform error shown inline on failure — not just
one toast at the end. Backend switched from one blocking request to an
in-memory job registry (`app/publish_jobs.py`, new) the frontend polls;
each platform upload now runs via `asyncio.to_thread()` rather than
blocking the event loop directly, which was necessary for polling to see
live progress at all, and incidentally fixes the "whole server blocks
during any publish" issue an earlier audit session had flagged but not
fixed. Scheduling ("Publish later") is untouched, still fully synchronous.

Cancel is cooperative, not forceful, by design — it stops the job before
the next not-yet-started platform step, but can't interrupt an upload
already in flight (Facebook/Instagram's Graph API is effectively
all-or-nothing once started). True mid-upload cancel is a new Medium
Priority TODO item, not attempted this session.

Verified: the job registry's actual logic (create/ownership isolation/
step updates/cancel/cancel-by-wrong-user/finish) exercised directly,
all pass. `pyflakes` clean across `app/`, `node --check` clean on
`app.js`, clean rebuild. **Not verified: an actual real-account publish
through the UI in a browser** — no browser or real platform credentials
in this environment, same limitation as most frontend work here. Flagged
as a new Low Priority TODO item.

## 2026-09-20 (even later): Instagram re-encode-and-retry fallback
Direct follow-on to the "Instagram publish failure diagnosis" entry
below — the project owner's initial guess (moov-atom/faststart, a common
cause of this exact symptom) was tested directly against the real
failing video and disproven: `ffmpeg -c copy -movflags +faststart`
completed cleanly (confirmed moov moved to front) but Instagram still
rejected it with the same error. The project owner then shared a working
local script (`upload_reel.py`) that solves this for a different
pipeline via a full ffmpeg re-encode fallback (H.264 Main profile,
`yuv420p`, AAC, faststart) with a retry-once pattern.

Ported that pattern into `app/uploaders.py`, used by both `/api/publish`
and the scheduler. Only retries via re-encode for the specific failure
mode it can fix (Instagram fetched the file but rejected it while
processing) — not for auth errors or the 5-minute processing timeout,
where re-encoding wouldn't help and would just add a long wait on top of
an already-long one. `ffmpeg` is an optional system dependency; missing
it degrades gracefully to the pre-existing behavior. Full reasoning in
docs/DECISIONS.md 012, full changes in CHANGELOG.md's matching entry.

Verified via a synthetic test video reproducing the real file's
characteristics (H.264 High profile) and a mocked Graph API — confirmed
the re-encode output is genuinely spec-correct, the retry fires only for
the right failure mode, never loops more than once, and a missing-ffmpeg
environment doesn't crash. **Not yet confirmed against the real
Instagram account and the actual failing video on the live VM** — see
TODO.md. Also added an ffmpeg install step to DEPLOYMENT_GUIDE.md /
README.md, since this is a new (optional) system dependency the VM
doesn't have unless installed.

## 2026-09-20 (later): Instagram publish failure diagnosis
Project owner published a video that succeeded on YouTube and Facebook
but failed on Instagram with only "Instagram failed to process the
video." — not enough detail to diagnose. Traced it to Instagram's own
processing step (the public-URL fetch itself succeeded, ruling out a
network/nginx cause — separate from the outage below). Fixed
`app/uploaders.py` to surface Graph API's actual `status` detail instead
of just the generic status_code, and fixed the error toast overflowing on
long messages (`frontend-src/style.css`). Full detail in CHANGELOG.md's
"Instagram publish failure diagnosis + error surfacing" entry.

Not completed: the specific reason THIS video failed couldn't be
recovered (temp file already deleted) — flagged as a TODO for the project
owner to check the video against Reels' requirements directly. The next
Instagram failure will show the real reason instead of a dead end.

While auditing the last 3 commits before this (per a separate request
this session), also found and confirmed already-fixed-by-other-work: a
`.manage-btn` dark-mode background bug and a stale `?page=` OAuth redirect
URL. No action needed on either.

## Current Task
Started as a live bug report (console screenshot: 404s + a publish
failure), ended up covering a real production outage this session itself
caused. Full detail in CHANGELOG.md's 2026-09-20 entry and
docs/DECISIONS.md 011 — this section is a summary, not the record of
truth.

## What happened, in order
1. Fixed a real race condition: `loadStatus()` and the initial page load
   fired before `loadAccounts()` (which validates/corrects a stale
   `currentAccountId`) had resolved — explained the reported 404s.
   Pushed, deployed, not yet re-confirmed fixed by the project owner.
2. Investigating a separate real `ERR_CONNECTION_ABORTED` on video
   publish, added missing `client_body_timeout`/`send_timeout` (both
   defaulted to 60s) to `mediaflow.nginx.conf` — not confirmed as the
   actual cause of that error before #3 below overtook the session.
3. **Caused a ~30 minute HTTPS outage** by instructing
   `sudo cp mediaflow.nginx.conf /etc/nginx/sites-available/mediaflow` —
   this overwrote a certbot-managed HTTPS server block that existed live
   on the VM but was never in this repo. Several wrong theories chased
   before finding the real cause (AWS Security Group, Cloudflare, Chrome
   auto-HTTPS-upgrade — none of them it). Root cause: the repo's
   `server_name _;` placeholder didn't match what certbot had attached to.
4. Fixed by pinning `server_name sohailanalytics.online;` in the repo
   file, letting certbot re-find and re-attach its SSL block. **Confirmed
   working by the project owner.**
5. Documented the incident (docs/DECISIONS.md 011) and added a standing
   rule to CLAUDE_INSTRUCTIONS.md: never copy `mediaflow.nginx.conf` or
   `mediaflow.service` onto the VM without diffing against the live file
   first — live infra config can drift from this repo silently (certbot,
   or a manual fix under pressure) and the repo copy isn't automatically
   authoritative.

## Not completed / still open
- The live VM's nginx config (with certbot's re-added SSL block) has
  **not** been pulled back into this repo — see TODO.md, now High
  Priority. Until that happens, `mediaflow.nginx.conf` here is still an
  incomplete picture of the real config, same underlying gap that caused
  the outage, just currently on the safe side of it (repo is missing
  something live, not the other way around).
- The `client_body_timeout`/`send_timeout` fix (#2 above) was never
  actually confirmed to resolve the original `ERR_CONNECTION_ABORTED` —
  the outage interrupted that investigation. Worth re-testing a real
  publish now that HTTPS (and these timeouts) are both live.
- The race-condition fix (#1) also hasn't had explicit before/after
  confirmation beyond "the 404s stopped happening because of the outage
  distraction" — worth a clean re-check.

## Next Step
Re-test a real video publish end-to-end now that the site is back up,
to confirm both #1 and #2 above actually hold. Then close out the
nginx-config-sync TODO item so this repo file matches live reality again.

---

# Previous Session (2026-09-19)

## Current Task
Small, targeted ask from a screenshot: the Analytics page just shows
plain "Loading…" text with no visual indicator while data fetches — add
a progress bar.

## Progress
Completed, tested, committed, and pushed to `main` (touches
`frontend-src/**` + the generated `static/index.html`, triggers a live
deploy):
- Added an indeterminate, animated progress bar
  (`.analytics-progress-track` / `.analytics-progress-fill`,
  `frontend-src/style.css`) shown above the existing "Loading…" text in
  `#analyticsBody` while `loadAnalytics()` (`frontend-src/app.js`) is
  fetching.
- Indeterminate rather than a real percentage: it's a single `fetch()`
  call with no meaningful step-by-step progress to report, so a sweeping
  bar (visually consistent with the existing `.mini-spinner` used in the
  video modal, just bar-shaped instead of a spinner) is accurate; a fake
  percentage would not be.
- Ran `python3 build.py` after the `frontend-src/` edit, per
  docs/PROJECT_CONTEXT.md's file-architecture rule. Verified: JS syntax
  (`node --check` on the extracted `<script>` block — note `static/
  index.html` now has *two* `<script>` blocks, so a non-greedy regex
  matching all of them and taking the last one is required, not a single
  greedy match across both), Python syntax on `server.py` and every
  `app/**/*.py` file, and confirmed the new CSS/markup actually landed in
  the built `static/index.html` before committing. GitHub Actions "Deploy
  to VM" confirmed successful for this commit.

Currently Working On:
- Nothing else this session — this was a single small, self-contained ask.

Not Completed:
- Only the main Analytics-page load got the progress bar, matching
  exactly what was asked (and shown in the screenshot). There are a few
  other "Loading…" spots in the same page (the video-list panel inside
  analytics, the video detail modal) that still show plain text only —
  worth doing for consistency if wanted, not done here since it wasn't
  what was asked.
- Everything listed as open in prior sessions' handoffs (see "Previous
  Session" blocks below) is unchanged: the `users`-table production
  check, scheduler-at-scale, TikTok decision, GitHub PAT rotation, etc.

## Important Information (carried forward, still true)
- `credentials/` is gitignored and will NOT be present when a new session
  clones this repo. Each new session/machine needs credentials supplied
  separately (not via git) — see docs/PROJECT_CONTEXT.md.
- Frontend is edited under `frontend-src/` (`layout.html`, `style.css`,
  `app.js`, `pages/*.html`), then built into `static/index.html` via
  `python3 build.py` — never edit the generated file directly (per
  CLAUDE_INSTRUCTIONS.md / docs/DECISIONS.md 005). `static/login.html`
  and `static/signup.html` are standalone, edited directly.
- **Login is real multi-user accounts** (Decision 004), **workspace
  accounts are per-user** (Decision 006) with a self-healing guarantee
  every authenticated user owns ≥1 account (Decision 007), and **page
  URLs are path-based** (Decision 008). Signup can optionally be gated
  behind an invite code via `SIGNUP_CODE` (Decision 009). **An admin
  role and panel are live** (Decision 010) — the earliest-created user
  is admin by default; see Settings for the panel.
- Pushing to `main` with changes touching `server.py`, `static/**`,
  `app/**`, or `requirements.txt` auto-deploys to the live VM — see
  `.github/workflows/deploy.yml`.
- A live GitHub fine-grained PAT is stored in plaintext in `gittoken.md`
  and has been flagged as exposed across multiple prior sessions — still
  not rotated.

## Next Step
Nothing this task specifically requires next. From TODO.md, the
longest-standing open items are still: checking the real `users` table
for anyone created 2026-09-12 through 2026-09-14 who isn't the project
owner (Decision 007's Status note — now a two-click fix via the admin
panel once found), and the scheduler-at-scale / TikTok product
decisions.

## Security Note
Unchanged from prior sessions: the GitHub PAT in `gittoken.md` is still
plaintext and still not rotated. Not touched this session — flagged
again for whoever picks this up next.

## Known Issues
See "Not Completed" above.

---

# Previous Session (2026-09-18, SIGNUP_CODE invite-gate + admin panel)

## Current Task
Asked to check TODO.md and work on a feature. Picked the next actionable
High Priority item (`SIGNUP_CODE` invite-gate), then continued to the
next one after that (admin panel) — the remaining open items either need
a human to check production data, or a product decision from the project
owner first (scheduler scaling, TikTok).

## Progress — SIGNUP_CODE invite-gate (pushed, live)
Completed, tested, committed, and pushed to `main` (touches `app/**` and
`static/signup.html`, triggers a live deploy):

- Built the optional `SIGNUP_CODE` env var gate for `POST
  /api/auth/signup` (unset by default — nothing changes for the live
  install unless the project owner sets it). New public `GET
  /api/auth/signup-config` lets the signup page know whether to show the
  invite-code field, without exposing the code itself. A rejected
  attempt (missing/wrong code) 403s before touching the DB, so it can't
  be used to reserve a username.
- While in `static/signup.html`, noticed and fixed a stale, actively
  misleading claim left over from before per-user isolation shipped: the
  brand-panel note still said "everyone who signs up shares the same
  MediaFlow dashboard and connected accounts." Replaced with an accurate
  line.
- Reconciliation: found two commits already on `main`
  (`6f58833`, `7d53e80`) from a different session that were pushed
  without CHANGELOG/TODO/SESSION_HANDOFF updates at the time. Backfilled
  CHANGELOG.md entries for them and fixed a TODO.md item that was still
  listed as open even though `6f58833` had already fixed it (the YouTube
  OAuth callback's stale `account_id` param).
- Also noted, separately from my own work: the project owner made a
  batch of unrelated commits directly (GitHub Actions/cron-schedule
  experiments, `anthropic-wif-test.yml`) — not a security concern, just
  flagging that not everything in `git log` is session work.

Full detail and alternatives considered: docs/DECISIONS.md 009.
CHANGELOG.md's "2026-09-18 (feature: optional SIGNUP_CODE invite-gate for
signup)" entry has the verification list.

## Progress — Admin panel (reviewed, approved, pushed)
Introduces a real privilege distinction (who's an admin) that didn't
exist before — treated with the same caution as the original per-user
isolation migration (Decision 006): built and tested first, held for
explicit project-owner review before pushing (unlike SIGNUP_CODE, which
was safe-by-default), and pushed once approved.

- New `users.is_admin` column. Migration grants it to the single
  earliest-created user only (never every pre-existing user — same
  reasoning as Decision 007's backfill: can't tell "the real owner" apart
  from "someone who signed up early" for anyone past the first row).
- New `require_admin` dependency (separate from `require_login`) gating a
  new `app/routes/admin.py`: list users, list every workspace account +
  owner, reassign an account's owner, force a password reset (also
  invalidates that user's existing sessions), promote/demote admins,
  delete a user.
- Delete-user guards mirroring the existing "last account" pattern:
  can't delete yourself, can't delete someone who still owns accounts,
  can't demote/delete the last remaining admin.
- Settings page gets two new panels (Users, Workspace accounts), hidden
  unless `is_admin` is true, reusing the existing Accounts-page styling.

Full design, every alternative considered, and the exact verification
list (access control, reassignment, forced password reset + session
invalidation, promote/demote including the last-admin guard, delete-user
guards, full regression suite re-run alongside) are in
docs/DECISIONS.md 010 and CHANGELOG.md's "2026-09-18 (feature: admin
panel)" entry — read those rather than re-deriving from memory.

## Not Completed / noticed but NOT fixed
- **The `users`-table check from two sessions ago is still not done** —
  still requires a human looking at the real production database (see
  TODO.md High Priority, unchanged). Now that the admin panel is live,
  fixing anyone found is a two-click reassign from Settings instead of
  direct DB access.
- The remaining High Priority TODO items (scheduler scaling, TikTok) are
  product/scope decisions for the project owner, not picked up this
  session.
- Didn't verify the invite-code field's show/hide behavior, or the new
  admin panel UI, in an actual browser — no browser tooling in this
  environment. Worth a real look on the live VM.
- Everything else in TODO.md is unchanged and still open.

## Important Information (carried forward, still true)
- `credentials/` is gitignored and will NOT be present when a new session
  clones this repo. Each new session/machine needs credentials supplied
  separately (not via git) — see docs/PROJECT_CONTEXT.md.
- **Login is real multi-user accounts** (Decision 004), **workspace
  accounts are per-user** (Decision 006) with a self-healing guarantee
  every authenticated user owns ≥1 account (Decision 007), and **page
  URLs are path-based** (`/dashboard`, not `?page=dashboard`, Decision
  008). Signup can now optionally be gated behind an invite code via
  `SIGNUP_CODE` (Decision 009), but isn't by default. **An admin role and
  panel are live** (Decision 010) — the earliest-created user is admin by
  default; see Settings for the panel, `app/routes/admin.py` for the API.
- Pushing to `main` with changes touching `server.py`, `static/**`, `app/**`,
  or `requirements.txt` auto-deploys to the live VM — see
  `.github/workflows/deploy.yml`.
- A live GitHub fine-grained PAT is stored in plaintext in `gittoken.md`
  and has been flagged as exposed across multiple prior sessions — still
  not rotated.

## Next Step
1. **Verify on the live VM that the admin panel actually works as
   intended** — no browser tooling in this environment, so this was only
   verified via API-level tests, never visually. Log in as the account
   that should now be admin and confirm the Settings page shows the new
   panels.
2. **Check the real `users` table** for anyone created 2026-09-12 through
   2026-09-14 who isn't you — see docs/DECISIONS.md 007's "Status" note.
   With the admin panel now live, fixing anyone found is a two-click
   reassign from Settings instead of direct DB access.
3. Confirm the SIGNUP_CODE deploy is still healthy (Actions tab) — it
   should be, nothing since has touched it.
4. Otherwise, next candidates from TODO.md: the scheduler-at-scale or
   TikTok decisions.

## Security Note
Unchanged from prior sessions: the GitHub PAT in `gittoken.md` is still
plaintext and still not rotated. Not touched this session — flagged again
for whoever picks this up next.

## Known Issues
See "Not Completed / noticed but NOT fixed" above.

---

# Previous Session (2026-09-17, isolation bug-audit + toggle fix + URL routing)

## Current Task
Three things this session: (1) asked to check the previous
per-user-isolation commit (`55f798d`, 2026-09-14, Decision 006) for bugs
it may have caused, and fix them; (2) project owner then reported (with a
screenshot) that toggle switches show two dots when on, asked whether
that's correct; (3) project owner asked to switch page URLs from
`?page=xxx` to real paths like `/dashboard`.

## Progress — path-based page URLs
Completed, tested, committed, and pushed to `main` (touches `server.py`
and `static/**`, triggers a live deploy). `frontend-src/app.js` now sets
the address bar to `/dashboard`, `/accounts`, etc. instead of
`/?page=dashboard`; old `?page=xxx` links still work once and get
normalized to the new form. `server.py` gained one real route per known
page (all serving the same `index.html`, same login gate as `/`) since a
hard refresh/bookmark/shared link on any page besides `/` would otherwise
404 — the SPA's routing only runs client-side after the page has already
loaded. Full detail, alternatives considered, and exactly what was/wasn't
verified are in docs/DECISIONS.md 008 and CHANGELOG.md's matching entry.
**Important**: `_SPA_PAGES` in `server.py` and `PAGE_TITLES` in
`frontend-src/app.js` must be kept in sync — if a future session adds a
new page, both need the new key or the new page's direct URL will 404 on
refresh even though clicking to it in-app still works.

## Progress — toggle double-dot fix
Completed, committed, and pushed to `main` (touches `static/**`, so
triggers a live deploy). Every `.toggle` (dark-mode toggle, Upload page's
"customize" toggle) was showing two overlapping white dots when on: a
dead CSS `.toggle::after` pseudo-element was permanently pinned at the
left/off position while a separate, real JS-created `<span class="dot">`
(`frontend-src/app.js`'s `setDot()`) correctly slid right on "on" — so
you'd see both at once. Predates the recent dark-mode work; not something
that commit introduced. Fix: removed the dead CSS rule, since the JS dot
already fully owns the toggle's visuals. Rebuilt `static/index.html` via
`python3 build.py`, confirmed the removed rule isn't in the compiled
output. **Could not visually verify in an actual browser — no browser
tooling in this environment.** Worth a real check on the live VM. Full
detail in CHANGELOG.md's "2026-09-17 (bug fix: toggle switches showing
two dots when on)" entry.

## Progress — per-user isolation bug audit
Completed, tested, committed, and pushed to `main` (commit — see `git log`
for the exact hash of "Fix: guarantee every user owns at least one
workspace account"; this touches `app/**` so it triggers a live deploy
per `.github/workflows/deploy.yml`):

- **Found a real, reproducible bug.** `55f798d`'s one-time
  `backfill_account_ownership()` migration assigns every pre-existing
  workspace account to a single earliest-created user. Multi-user login
  (Decision 004) had been live for two days before per-user isolation
  (Decision 006) shipped — if a second real person had already signed up
  in that window and was using the shared account, the migration would
  leave them owning zero accounts. Confirmed this isn't just a missing
  feature but a fully broken app for that person:
  `frontend-src/app.js`'s account switcher falls back to `account_id=1`
  when its account list is empty, and account 1 now belongs to someone
  else — every page (dashboard, library, platforms, upload) would 404.
  Reproduced it directly: hand-built a DB with two pre-existing users and
  one shared account, ran the real startup migration, confirmed the
  second user got `[]` back from `/api/accounts`.
- **Fixed it**: `app/auth.py` gets a new `ensure_user_has_account(user_id,
  username)`, called from `require_login` on *every* authenticated
  request (not only login/signup), so anyone who ends up owning zero
  accounts — now or from some future edge case — gets a fresh one on
  their very next request. This self-heals an already-active session too
  (no need to log out and back in). Signup now calls this same helper
  instead of duplicating the logic inline.
- **Also fixed a stale docstring** in `app/auth.py` left over from before
  Decision 006 — it still described workspace accounts as shared with "no
  per-user restriction," which stopped being true once isolation shipped.
- Wrote up docs/DECISIONS.md 007 with the full reasoning, alternatives
  considered, and — important — the limits of this fix (see below).
- Flagged a new High Priority TODO item: **the project owner should check
  the real `users` table for anyone who signed up between 2026-09-12 and
  2026-09-14**, since that's the exact window where someone could have
  been affected. This fix makes their app work again going forward, but
  it can only give them a *fresh, empty* account — there's no record of
  who was using the original shared account under the old model, so any
  actual prior history for that person can't be automatically recovered.
  This needs a human to check; it's not something resolvable by reading
  the code further.
- Audited the rest of `55f798d` beyond this: re-checked every
  `account_id`-taking endpoint (`grep`, not just re-reading my own
  summary) to confirm none were missed, checked the OAuth callback flows
  specifically since they're not directly login-gated (confirmed safe —
  ownership is verified at connect-time, before the account_id ever
  reaches the callback), and confirmed the newer, unrelated commits
  already on `main` (`11d2017`, `569dd0c` — mobile layout + dark mode)
  don't touch or interact with any of this.

Testing done (FastAPI `TestClient`):
- Reproduced the exact failure pre-fix, then confirmed post-fix: the
  previously-locked-out user's very next request (same session, no fresh
  login) returns a new account of their own, and that account works
  normally (200 on `/api/dashboard/summary`) — while the original owner's
  account and access are completely unaffected.
- Re-ran the full 2026-09-14 isolation regression suite (two-user
  cross-account 404s, delete-last-account guard, publish/library smoke
  test) against the fixed code — still all passing.
- `pyflakes app/ server.py` — clean.

Full detail is in docs/DECISIONS.md 007 and CHANGELOG.md's "2026-09-17
(bug fix: users could be left with zero workspace accounts after
per-user isolation)" entry.

## Not Completed / noticed but NOT fixed
- **The `users`-table check above is not done** — it requires looking at
  the real production database, which this session can't reach. This is
  the most important open item right now, ranked accordingly in TODO.md.
- Everything else in TODO.md is unchanged and still open.

## Important Information (carried forward, still true)
- `credentials/` is gitignored and will NOT be present when a new session
  clones this repo. Each new session/machine needs credentials supplied
  separately (not via git) — see docs/PROJECT_CONTEXT.md.
- **Login is real multi-user accounts** (Decision 004), **workspace
  accounts are per-user** (Decision 006), and as of this session **every
  authenticated request guarantees the user owns at least one account**
  (Decision 007) — but see the unresolved TODO item above about possible
  pre-existing users caught by the original migration.
- Pushing to `main` with changes touching `server.py`, `static/**`, `app/**`,
  or `requirements.txt` auto-deploys to the live VM — see
  `.github/workflows/deploy.yml`.
- A live GitHub fine-grained PAT is stored in plaintext in `gittoken.md`
  and has been flagged as exposed across multiple prior sessions — still
  not rotated.

## Next Step
1. **Project owner: check the real `users` table** for anyone created
   2026-09-12 through 2026-09-14 who isn't you — see the High Priority
   TODO item and docs/DECISIONS.md 007's "Status" note for what to look
   for and why.
2. Confirm this session's deploys succeeded (Actions tab), then verify on
   the live VM that login still works normally for the existing user, and
   that the dark-mode/customize toggles now show one dot, not two.
3. Otherwise, next candidates from TODO.md: `SIGNUP_CODE` gate, admin UI
   for user/account management, or the scheduler-at-scale question.

## Security Note
Unchanged from prior sessions: the GitHub PAT in `gittoken.md` is still
plaintext and still not rotated. Not touched this session — flagged again
for whoever picks this up next.

## Known Issues
See "Not Completed / noticed but NOT fixed" above.

---

# Previous Session (2026-09-17, mobile layout / dark mode)

## Current Task
Picked up a task from a different Claude session that hit its usage limit
mid-request (project owner shared screenshots of that session's chat).
Requested: fix Accounts-page mobile alignment, introduce real dark mode,
fix the dark-mode toggle, general UI polish.

## Progress
Completed, committed, and pushed to `main` (commit `11d2017` — this
triggers the live deploy per `.github/workflows/deploy.yml`, touches
`static/**`):

- Fixed `.account-row` (Accounts page): the Active pill + Rename/Delete
  buttons had no wrap/stacking behavior and were overlapping the account
  name on narrow screens. Wrapped them in a new `.acc-row-actions`
  container (`frontend-src/app.js`) that drops to its own full-width,
  right-aligned row on `max-width:720px`.
- Implemented actual dark mode — previously `#darkToggle` only changed its
  own dot color and applied no theme anywhere. Added `html.dark-theme{...}`
  variable overrides in `frontend-src/style.css`, converted ~15
  hardcoded `#fff`/`#f5f6fa`-family surfaces to those variables so dark
  mode actually reaches them, wired the toggle to flip the class and
  persist via `localStorage` (`mf-dark-theme`), and added a pre-paint
  inline script in `frontend-src/layout.html` so reload doesn't flash
  light-then-dark.
- Rebuilt `static/index.html` via `python3 build.py` and verified the
  compiled output before committing (grepped for the new class names /
  variable names / JS symbols to confirm they made it into the build, not
  just the source files).
- Checked Platforms/Scheduled/Published/Settings for the same
  cramped-row pattern that broke Accounts — Platforms already has a
  mobile grid fix from a prior session, Settings is a placeholder,
  nothing else showed the bug. Scope was intentionally limited to what
  was actually reported plus what a quick audit turned up, not a full
  redesign pass.

Full detail (exact CSS/JS diffs, which surfaces were converted and why) is
in CHANGELOG.md's "2026-09-17 (fix: Accounts page mobile layout; feature:
real dark mode)" entry — don't re-derive it from memory later.

## Not Completed / noticed but NOT fixed
- Small semantic-tinted badges (gain-pill, pub-pill.sched/.fail,
  notif.warn) still use light-mode colors in dark mode — low visual
  impact, left for later (see TODO.md).
- Did not visually verify the fix in an actual mobile browser — this
  session has no way to render/screenshot the built page. Worth a real
  check on the live VM after deploy, same caveat as several prior
  sessions' frontend changes.
- Everything else in TODO.md is unchanged and still open.

## Important Information (carried forward, still true)
- `credentials/` is gitignored and will NOT be present when a new session
  clones this repo. Each new session/machine needs credentials supplied
  separately (not via git) — see docs/PROJECT_CONTEXT.md.
- `static/index.html` is a generated file — edit `frontend-src/` and run
  `python3 build.py`, never edit `static/index.html` directly (it says so
  in a comment at the top, but worth restating here since it's an easy
  mistake for a new session to make).
- Pushing to `main` with changes touching `server.py`, `static/**`, or
  `requirements.txt` auto-deploys to the live VM — see
  `.github/workflows/deploy.yml`.
- A live GitHub fine-grained PAT is stored in plaintext in `gittoken.md`
  and has been flagged as exposed across multiple prior sessions — still
  not rotated.

## Next Step
1. Confirm the GitHub Actions deploy for commit `11d2017` succeeded
   (check the Actions tab), then verify on the live VM that the Accounts
   page and dark mode toggle actually work as intended on a real mobile
   device — this session couldn't visually confirm either.
2. If the project owner wants the semantic-badge dark-mode gap closed,
   or a fuller visual-redesign pass on pages other than Dashboard (older
   open item, see TODO.md), that's the natural next task.
3. Otherwise, next candidates from TODO.md: `SIGNUP_CODE` gate, admin UI
   for user/account management, or the scheduler-at-scale question.

---

# Previous Session (2026-09-14)

## Current Task
Per-user data isolation for workspace accounts — the biggest open item in
TODO.md. Before this session, every logged-in user could see and switch
into every workspace account (Decision 003) on the install; signing up
gave a stranger full access to everyone else's connected platforms,
scheduled posts, and analytics. See docs/DECISIONS.md 006 for the full
design writeup.

## Progress
Completed, tested, **not yet committed or pushed** (see "Next Step"):

- `accounts` table now has a `user_id` column. Existing/legacy accounts
  (from before this change) get backfilled to the earliest-created user at
  startup, once at least one user exists — see `backfill_account_ownership()`
  in `app/db.py`.
- `require_login` (`app/auth.py`) now returns `{"id", "username"}` instead
  of just the username, so routes can check ownership. Only one route body
  actually used the old return value (`GET /api/auth/me`) — updated to
  match, everywhere else was just a type-hint change.
- `get_account_or_404(account_id, user_id)` (`app/credentials.py`) now
  checks ownership and 404s either way (account doesn't exist, or isn't
  yours) — same response, so IDs can't be probed.
- Every account-scoped endpoint now goes through that check before doing
  anything with the `account_id` it's given: `/api/status`, `/api/publish`,
  `/api/library`, `/api/dashboard/summary`, YouTube connect, Facebook
  connect, all four Facebook/Instagram/YouTube analytics routes, and
  accounts list/create/rename/delete.
- `list_accounts` filters to the caller's own accounts. `create_account`
  sets the creator as owner. Signup now also auto-creates one default
  account for the new user, so they're not dropped into an empty switcher.
- Found and fixed a real bug along the way: `delete_account`'s "can't
  delete your last account" check used to count `accounts` globally, so it
  could block a user from deleting their last account because *other*
  users happened to have accounts (or the reverse). Now scoped per-user.
- Fixed a pre-existing gap flagged in TODO.md: `disconnect_youtube` /
  `disconnect_facebook` never validated `account_id` at all before; they
  now go through the same ownership check as everything else.
- No frontend changes were needed — `frontend-src/app.js`'s account
  switcher already falls back to `accountsCache[0]` if its cached
  `currentAccountId` isn't in whatever `/api/accounts` returns, which is
  exactly what happens for anyone whose stale `localStorage` pointed at an
  account they no longer see. Verified this directly (see Testing below),
  not just assumed from reading the code.

Full implementation detail (files touched, exact behavior changes,
alternatives considered) is in docs/DECISIONS.md 006 and CHANGELOG.md's
"2026-09-14 (feature: per-user data isolation for workspace accounts)"
entry — short version above, don't re-derive it from memory later.

Testing done (all via FastAPI `TestClient`, this sandbox has no real
platform credentials but none of this needed any):
- **Two-user isolation**, fresh signups: confirmed user B gets a 404
  reaching user A's account via `account_id` on every account-scoped
  route (library, dashboard summary, status, accounts rename/delete,
  Facebook connect/disconnect, YouTube connect, both Facebook and YouTube
  analytics endpoints) — 10 distinct cross-access attempts, all 404.
  Confirmed each user's own account still works normally (200s), and that
  one user's account churn (rename/create/delete) never changes what the
  other user's `/api/accounts` returns.
- **Legacy-upgrade path**: hand-built a pre-migration SQLite DB matching a
  real production install (`accounts` table with no `user_id` column, one
  pre-existing user, matching what's actually on the VM right now).
  Confirmed on startup: the existing account backfills correctly to that
  user, that user keeps full access to their existing data unchanged, and
  a brand-new signup afterward gets a separate account and a 404 touching
  the legacy one.
- **Delete-account edge case**: a user with exactly one account is blocked
  (400) from deleting it; can once they have two.
- **Smoke test** of previously-working flows scoped to one account:
  immediate publish, scheduled publish, `/api/library` (unfiltered and
  status-filtered), `/api/dashboard/summary` — all unchanged.
- `pyflakes app/ server.py` — clean.

Below is the original write-up of the file-architecture bug audit, left
intact for context:

Correction to the previous entry below: it stated the file-architecture
split was "not yet committed or pushed" and left for review. That was
inaccurate as of that session — commit `0793280` ("Split server.py and
static/index.html into per-concern files") is on `main` and already live.
Since it was already deployed, that session treated it as production code
needing a bug pass rather than a pending review.

**Bug found and fixed:** `app/routes/analytics_meta.py` used `datetime`,
`timedelta`, and `timezone` but the split dropped the import. Fixed by
restoring it. Full detail in CHANGELOG.md's "2026-09-14 (bug fix: missing
datetime import in app/routes/analytics_meta.py)" entry.

Everything from prior sessions (multi-user login, workspace accounts,
dashboard interactivity, notifications drawer, resizable sidebar,
subscriber counts, "Today" analytics filter, the `.lib-row` alignment
fix) is unaffected by the file-architecture split — see CHANGELOG.md for
the fuller history if needed.

## Currently Working On
Nothing else this session — the per-user isolation work above is
complete, tested, and ready to review, but **not yet on `main`**.

## Not Completed / things noticed but NOT fixed (worth a look next time)
- **This session's changes have not been committed or pushed.** They're
  sitting as uncommitted local changes (`git status` / `git diff` shows
  exactly what changed) pending the project owner's review, since this is
  a schema-changing, security-relevant change and pushing to `main`
  auto-deploys to the live VM.
- No admin UI or CLI to manually reassign a workspace account's owner, or
  to list/remove users — same gap as before, now also relevant to account
  ownership (see docs/DECISIONS.md 006). Would need direct DB access.
- Sign-up is still fully open to anyone who reaches the app's URL (an
  explicit, unchanged choice by the project owner) — each new signup now
  gets their *own* isolated account rather than shared access to
  everyone's, which meaningfully lowers the blast radius of that being
  open, but doesn't replace an invite gate if one's ever wanted (see
  TODO.md's `SIGNUP_CODE` idea).
- Everything else from prior sessions' "Not Completed" lists is still
  open — see TODO.md (scheduler-at-scale, TikTok decision, CORS
  lockdown, Facebook/Instagram "views today" limitation, visual-redesign
  pass on pages other than Dashboard, etc).

## Important Information
- `credentials/` is gitignored and will NOT be present when a new session
  clones this repo. Each new session/machine needs credentials supplied
  separately (not via git) — see docs/PROJECT_CONTEXT.md.
- **Login is real multi-user accounts** (Decision 004), and as of this
  session **workspace accounts are per-user** too (Decision 006) — anyone
  who signs up gets their own isolated default account, not access to
  everyone else's. There's still no invite gate on signup itself and no
  per-user permission scoping beyond account ownership.
- Deleting a workspace account via the Accounts page is destructive and
  immediate (no soft-delete/undo).
- The sidebar's collapsed/expanded state and width are stored in the
  browser's `localStorage`, so they're per-browser, not per-account or
  server-synced.
- A live GitHub fine-grained PAT is stored in plaintext in `gittoken.md`
  and has been flagged as exposed across multiple prior sessions. Not
  addressed this session (out of scope for this task; still worth
  rotating separately).

## Next Step
1. **Review and decide whether to commit/push this session's changes.**
   They're currently uncommitted local changes only — `git diff` shows
   exactly what changed across `app/db.py`, `app/auth.py`,
   `app/credentials.py`, `app/routes/*.py`, `server.py`, and
   `docs/DECISIONS.md`. Pushing to `main` will trigger a live deploy (see
   `.github/workflows/deploy.yml`) and will run the `user_id` migration +
   backfill against the real production DB on next boot — recommend
   confirming the backfill logic (assigns all pre-existing accounts to
   the earliest-created user) matches what's actually wanted for the live
   install before pushing, since that's a one-way data change.
2. Once pushed and deployed, verify on the live VM directly: existing
   login still reaches the same existing account/data as before, and a
   fresh test signup gets its own separate, empty account rather than
   access to the real one.
3. After that, next candidates from TODO.md: the `SIGNUP_CODE` gate,
   admin UI for user/account management, or the scheduler-at-scale
   question.

## Security Note
Unchanged from prior sessions: the GitHub PAT in `gittoken.md` is still
plaintext and still not rotated. Not touched this session — flagged again
for whoever picks this up next.

## Known Issues
See "Not Completed / things noticed but NOT fixed" above.
