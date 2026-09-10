# Session Handoff

## Last Updated
2026-09-10

## Current Task
Multi-account support: replaced the single-tenant admin pill with a real
account switcher. Each account now has fully independent platform
connections, scheduled/published posts, and analytics, behind one shared
app login.

## Progress
Completed:
- Repo initialized and pushed to GitHub (SOHAIL62786/mediaflow-app)
- Secret-scanning incident resolved (see docs/DECISIONS.md 001) — history
  reset, credentials/ gitignored
- Documentation system created: docs/PROJECT_CONTEXT.md, docs/DECISIONS.md,
  CHANGELOG.md, TODO.md, this file, CLAUDE_INSTRUCTIONS.md
- `static/index.html` admin-pill: "Sohail"/"S" → "Moiz"/"M". Committed and
  pushed to `main` (fbb1483..6f8cbfc)
- Multi-account support (see docs/DECISIONS.md 003):
  - `accounts` DB table + `account_id` column on `uploads`, migration-safe
  - Account 1 auto-seeded as "Moiz" — original install unaffected
  - Per-account credential dirs under `credentials/accounts/<id>/`, with
    one-time migration of legacy `credentials/token.json` /
    `facebook.json` into Account 1's folder
  - Every relevant backend endpoint takes `account_id` (default 1)
  - New `GET/POST /api/accounts`
  - Frontend: top-right pill is now an account switcher dropdown with
    "+ Add account"; all fetch calls scope to the current account
  - Verified: `python3 -m py_compile server.py` passes; ran the app
    locally to confirm the DB migration creates Account 1 = "Moiz";
    extracted and `node --check`'d the page JS

Currently Working On:
- Nothing else this session — about to commit and push

Not Completed:
- No UI to rename/delete an account (create/list only)
- Scheduler scaling across many accounts' due posts not yet
  designed/tested (see TODO.md)
- All other pre-existing items in TODO.md are still open

## Important Information
- `credentials/` is gitignored and will NOT be present when a new session
  clones this repo. Each new session/machine needs credentials supplied
  separately (not via git) — see docs/PROJECT_CONTEXT.md.
- Repo write access for a Claude session is granted via a GitHub fine-grained
  PAT (Contents: read/write, this repo only), supplied by the project owner.
  Treat any session with a live token as having real push access — be
  careful with destructive git operations (history rewrites, force pushes).

## Next Step
Test the multi-account flow live on the VM: switch accounts, connect a
second account's YouTube/Facebook, confirm posts and analytics stay
separated from Account 1. Then pick up UI for renaming/deleting an
account, or the next item from TODO.md.

## Security Note
A live GitHub fine-grained PAT was found stored in plaintext in a project
file (`gittoken.md`) during this session and was used once to push this
change, per the "Repo write access" note above. Recommend rotating that
token and, going forward, supplying it via a secrets manager or a fresh
per-session token rather than a plaintext file, since it's now been
exposed in chat/session context.

## Known Issues
None currently tracked beyond what's listed in TODO.md.
