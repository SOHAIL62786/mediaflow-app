# Session Handoff

## Last Updated
2026-09-11

## Current Task
Add a UI to rename/delete accounts (the multi-account feature's "workspaces",
e.g. Sohail, Moiz — not app login), and split the old combined "Accounts"
page into a dedicated Accounts (manage accounts) page and a renamed
"Platforms" page (connect/disconnect YouTube/Facebook/Instagram).

## Progress
Completed, pushed (b2b3520..90193c7):
- `server.py`: added `PATCH /api/accounts/{id}` (rename) and
  `DELETE /api/accounts/{id}` (delete — refuses on the last remaining
  account; otherwise deletes that account's `uploads` rows and its
  `credentials/accounts/<id>/` directory).
- `static/index.html`:
  - New **Accounts** nav item/page — list accounts, Rename (prompt),
    Delete (confirm, disabled when only one account left), Add, and
    click-a-row-to-switch.
  - The old **Accounts** page (platform connect/disconnect) renamed to
    **Platforms** — `data-page`, element ids, and
    `loadAccountsPage()` → `loadPlatformsPage()`.
  - All "go connect a platform from Accounts" wording (toasts, buttons,
    analytics empty-states, and matching `server.py` error strings) now
    says "Platforms".
  - `promptCreateAccount()` extracted as a shared function used by both
    the top-right dropdown's "+ Add account" and the new Accounts page.
- Verified locally: JS passed `node --check`; ran the FastAPI server
  locally and exercised create/rename/delete via curl, including the
  "can't delete the last account" 400 case — all worked as expected.
- GitHub Actions "Deploy to VM" run queued for this push at time of
  writing — not confirmed live on the VM yet (see Next Step).

Currently Working On:
- Nothing else this session.

Not Completed:
- Confirm on the actual VM that the deploy succeeded and the new
  Accounts/Platforms pages work end-to-end in production (was only
  tested locally with a fresh throwaway DB in this session's sandbox).
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
- Deleting an account via the new UI is destructive and immediate (no
  soft-delete/undo): it removes that account's post history and stored
  platform credentials permanently. The confirm() dialog says this, but
  worth knowing if support questions come up.

## Next Step
Verify the live VM deploy for commit `90193c7` succeeded (check the
"Deploy to VM" GitHub Actions run, then load the app and click through
Accounts and Platforms). After that, consider the visual-redesign pass
(semantic color, brand-icon tiles, pill-styled controls from the
Dashboard redesign) on the new Accounts page and on Scheduled/Published/
Analytics for consistency, if wanted.

## Security Note
A live GitHub fine-grained PAT was found stored in plaintext in a project
file (`gittoken.md`) again this session and was used once more to push
this change, per the "Repo write access" note above and explicit
instruction from the project owner to proceed. Recommend rotating that
token and, going forward, supplying it via a secrets manager or a fresh
per-session token rather than a plaintext file, since it has now been
exposed in chat/session context across at least two sessions.

## Known Issues
None currently tracked beyond what's listed in TODO.md.
