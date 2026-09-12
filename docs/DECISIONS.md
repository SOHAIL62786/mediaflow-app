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

---

## Decision 004

Date: 2026-09-12

Decision:
Replace the single shared login (HTTP Basic Auth, one APP_USERNAME/
APP_PASSWORD for the whole install) with real multi-user accounts: a
`users` table, hashed passwords, session-cookie auth, and custom Sign In
/ Sign Up pages. This directly reverses the login part of Decision 003
("accounts are not separate user logins") — that still holds for the
*workspace* accounts feature (Decision 003's "accounts" — independent
sets of platform connections/posts/analytics), which is unchanged and
remains unrelated to user identity. What changed is that multiple
*people* can now each have their own login, and all of them see the same
shared dashboard and the same set of workspace-accounts — there's no
per-user data separation, only per-user credentials.

Implementation:
- New `users` (id, username, password_hash, created_at) and `sessions`
  (token, user_id, created_at, expires_at) tables.
- Passwords hashed with PBKDF2-HMAC-SHA256, random per-user salt, 260,000
  iterations (OWASP's 2023 recommended minimum) — no new dependency,
  stdlib `hashlib`/`secrets` only.
- Session identity is a random token in an HttpOnly, SameSite=Lax cookie
  (`mf_session`, 30-day expiry), not HTTP Basic Auth — this is what makes
  a custom login page possible instead of the browser's native auth
  popup. `require_login` kept its old return signature (just the
  username) so none of the ~20 existing route signatures needed to
  change, only how that identity gets established.
- New pages/routes: `GET /login`, `GET /signup` (public, redirect to `/`
  if already logged in), `POST /api/auth/{signup,login,logout}`,
  `GET /api/auth/me`. `GET /` now redirects to `/login` instead of
  raising a 401 when not authenticated.
- Sign-up is fully open — anyone who reaches the URL can create an
  account with full access to the dashboard and connected platforms, by
  the project owner's explicit choice over a gated/invite-only option.
  Access control is therefore the network's job (firewall / who can
  reach the VM), not the app's.
- Backward compatibility: if `APP_USERNAME`/`APP_PASSWORD` env vars are
  set and no `users` row exists yet, one account is seeded from them on
  first boot so an existing install isn't locked out; if neither is set,
  a one-time random-password account is created and printed to the
  server log instead. Either way this only happens once — from then on
  it's an ordinary account like any other, and new people should use
  Sign Up rather than share it.

Reason:
Project owner wants different people to have their own login rather than
sharing one password, while still all working out of the same MediaFlow
instance and data.

Alternatives Considered:
- Admin-created users only, no public self-signup (offered as an option;
  project owner chose fully open sign-up instead)
- Just restyling the login as a nicer single-password page, no real
  per-user accounts (offered as an option; rejected — project owner
  specifically wanted separate logins per person)

Status:
Accepted. Not yet done: any admin UI to list/remove users or reset a
password (currently would require direct DB access); an optional
invite-code gate on sign-up was proposed but not requested — noted in
TODO.md in case open sign-up turns out to be too permissive later.
