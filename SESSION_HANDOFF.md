# Session Handoff

## Last Updated
2026-09-11

## Current Task
1. Add a UI to rename/delete accounts, split old "Accounts" page into
   Accounts (manage accounts) + Platforms (connect platforms) — done
   earlier today.
2. User asked "find any bugs on current version" — reviewed the change
   from (1) and found + fixed two real bugs it introduced.

## Progress
Completed, pushed (b2b3520..4ac2757):
- `server.py`: `PATCH /api/accounts/{id}` (rename), `DELETE
  /api/accounts/{id}` (delete, refuses on the last remaining account,
  deletes the account's `uploads` rows and `credentials/accounts/<id>/`).
- `static/index.html`: new Accounts page (list/rename/delete/add
  accounts); old Accounts page renamed to Platforms (connect/disconnect
  YouTube/Facebook/Instagram); all "Accounts" wording that meant
  "go connect a platform" updated to say "Platforms".
- Bugfix pass (commit 4ac2757), found by re-reading the above change:
  - `delete_account()` didn't delete the on-disk video file for any of
    the deleted account's still-scheduled (unpublished) posts — only
    the DB row. Fixed: now unlinks those files too.
  - The YouTube OAuth callback (`oauth2callback_youtube`) redirected to
    `?page=accounts` after connecting, which used to be correct (that
    was the platform-connect page) but became wrong once that page was
    renamed to Platforms and `accounts` became the unrelated
    account-management page. Fixed to `?page=platforms`.
- Both fixes verified locally: ran the server, inserted a fake
  scheduled-upload row with a real file on disk, deleted its account,
  confirmed both the DB row and the file were gone.
- GitHub Actions "Deploy to VM" confirmed successful for both the
  feature commit (90193c7) and the bugfix commit (4ac2757).

Currently Working On:
- Nothing else this session.

Not Completed / things noticed but NOT fixed (worth a look next time):
- `connect_youtube`'s OAuth flow builds the redirect back to
  `/?page=platforms&account_id={id}`, but the frontend's initial-route
  logic (`new URLSearchParams(location.search).get('page')`) only ever
  reads `page`, never `account_id` — that query param has been dead
  since multi-account support was added. It happens to still work
  today because `currentAccountId` in `localStorage` was already set to
  the right account *before* the browser navigated away to start the
  OAuth flow, and localStorage survives the full-page redirect back —
  but it's fragile (e.g. breaks if a user opens the connect link in a
  new tab/window that doesn't share that in-memory state at exactly the
  right moment). Consider actually reading `account_id` from the URL on
  load and using it as an override.
- `disconnect_youtube` / `disconnect_facebook` don't call
  `get_account_or_404` like the connect/rename/delete endpoints do —
  disconnecting a nonexistent account_id just silently no-ops instead
  of 404ing. Harmless today, but inconsistent with the rest of the
  account endpoints.
- Deleting an account that happens to be the currently-selected one
  triggers a redundant extra "Switched to X" toast/reload right after
  the "Account deleted" toast (both `loadAccounts()` and the explicit
  `switchAccount()` call in the delete handler end up doing the same
  correction). Cosmetic, not incorrect.
- Scheduler scaling across many accounts' due posts not yet
  designed/tested (see TODO.md).
- Other pages (Scheduled, Published, Analytics, Upload) still haven't
  had the dashboard's visual redesign pass — only Dashboard has it.
- All other pre-existing items in TODO.md are still open.

## Important Information
- `credentials/` is gitignored and will NOT be present when a new session
  clones this repo. Each new session/machine needs credentials supplied
  separately (not via git) — see docs/PROJECT_CONTEXT.md.
- Repo write access for a Claude session is granted via a GitHub fine-grained
  PAT (Contents: read/write, this repo only), supplied by the project owner.
  Treat any session with a live token as having real push access — be
  careful with destructive git operations (history rewrites, force pushes).
- Deleting an account via the Accounts page is destructive and immediate
  (no soft-delete/undo): it removes that account's post history, its
  pending scheduled video files, and its stored platform credentials
  permanently.

## Next Step
Either address one of the "noticed but not fixed" items above (the
account_id-in-URL fragility is probably the most worth doing properly),
or continue with the visual-redesign pass on the newer pages, per the
project owner's priority.

## Security Note
A live GitHub fine-grained PAT was found stored in plaintext in a project
file (`gittoken.md`) again this session and was used again to push these
changes, per explicit instruction from the project owner. Recommend
rotating that token and, going forward, supplying it via a secrets
manager or a fresh per-session token rather than a plaintext file, since
it has now been exposed in chat/session context across multiple sessions.

## Known Issues
See "Not Completed / things noticed but NOT fixed" above.
