# Session Handoff

## Last Updated
2026-09-14

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
