# Technical Decisions

## Decision 001

Date: 2026-09-10

Decision:
Keep `credentials/` gitignored; never commit OAuth tokens, client secrets,
or Facebook page tokens to the repo.

Reason:
An early push attempt included `credentials/token.json` and
`credentials/client_secret.json` (Google OAuth access token, refresh token,
client ID, and client secret). GitHub's push protection blocked it before
it reached the remote. Git history was reset and the repo was reinitialized
to guarantee no trace of the secrets exists in history.

Status:
Accepted. Enforced via `.gitignore`. Any session working on this repo
should treat `credentials/` as local-only and never re-add it to git.

---

## Decision 002

Date: 2026-09-10

Decision:
Use a docs/ + root tracker file structure (PROJECT_CONTEXT, DECISIONS,
CHANGELOG, TODO, SESSION_HANDOFF, CLAUDE_INSTRUCTIONS) to coordinate work
across multiple separate Claude sessions/accounts, since Claude has no
memory shared between sessions.

Reason:
Project owner plans to use multiple Claude accounts due to usage limits.
Without a persistent, session-independent source of truth, each new
session would need to reverse-engineer project state from the code alone.

Alternatives Considered:
- Relying on Claude's per-account memory (rejected — doesn't transfer
  between accounts)
- Google Drive as primary store (rejected — no real version control,
  harder to diff/rollback, sync-conflict risk for code)

Status:
Accepted.

---

## Decision 003

Date: 2026-09-10

Decision:
Add multi-account support as fully independent "accounts" (own platform
connections, scheduled/published posts, and analytics), switched via an
in-app dropdown, on top of a single shared login (APP_USERNAME/PASSWORD
is unchanged — accounts are not separate user logins).

Implementation:
- New `accounts` table (id, name, created_at); `uploads` gets an
  `account_id` column (default 1) via ALTER TABLE migration.
- Platform credentials moved from flat files under `credentials/` to
  `credentials/accounts/<id>/` per account. On first boot after this
  change, any pre-existing `credentials/token.json` and
  `credentials/facebook.json` are copied into `credentials/accounts/1/`
  so the original install keeps working unchanged as "Account 1".
- `credentials/client_secret.json` (the Google OAuth *app* client, not a
  per-user token) stays shareable across accounts by default — an
  account can still drop its own copy in its folder to override it.
- Every relevant endpoint takes an `account_id` query param (default 1)
  and threads it through credential lookup, DB queries, and the OAuth
  `state` for YouTube connect so tokens land in the right account.
- Account 1 is seeded with the name "Moiz" (what the admin pill already
  showed) so the first account is visibly unaffected by this change.

Reason:
Project owner wants to run multiple independent sets of platform
credentials (e.g. different clients/brands) from one MediaFlow install
without deploying separate instances, while keeping login simple (one
shared password, not per-account credentials).

Alternatives Considered:
- Separate username/password per account (rejected by project owner —
  wanted one shared login with an in-app switcher instead)
- Storing credentials in the DB instead of per-account files (rejected —
  bigger change to the existing file-based credential pattern for no
  clear benefit; `credentials/` is already gitignored/VM-local)

Status:
Accepted. Not yet done in this session: UI to rename/delete an account,
and a decision on whether the local scheduler should process all
accounts' due posts in parallel vs. sequentially at scale — both noted
in TODO.md.
