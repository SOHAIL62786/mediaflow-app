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
