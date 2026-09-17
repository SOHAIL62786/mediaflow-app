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

---

## Decision 005

Date: 2026-09-14

Decision:
Split the monolithic server.py (~1930 lines) into a package under app/
(one file per concern, FastAPI APIRouters per route group), and split the
monolithic static/index.html (~2430 lines) into source files under
frontend-src/ (one file per page, plus separate CSS/JS), assembled back
into static/index.html by a build.py script that also runs automatically
in CI on every push (see .github/workflows/deploy.yml).

Reason:
Editing any one page or API route meant scrolling through the entire file.
Splitting lets you touch just the relevant file (e.g. app/routes/accounts.py,
or frontend-src/pages/upload.html) without the rest of the app being in the
diff or in view.

Implementation:
- Backend: server.py now only does app creation, middleware, startup, and
  `include_router()` calls. Shared logic (DB, credentials, multi-user auth,
  uploaders, scheduler) lives in app/*.py; each group of related routes
  lives in app/routes/*.py, including a new app/routes/auth_pages.py for
  the login/signup/logout/me routes added in Decision 004. No behavior
  change — verified with a real regression test (FastAPI TestClient
  covering signup, login, bad-password rejection, session cookies, account
  create/rename/delete guards, and every other endpoint) comparing the
  refactored app's responses against the original app's responses before
  committing — one real bug (a missing import) was caught and fixed by
  this process before it ever shipped.
- Frontend: static/index.html is now a **generated file** — edits go
  through frontend-src/ (layout.html, style.css, app.js, pages/*.html) and
  `python3 build.py`. Verified byte-for-byte identical output (aside from
  one intentional "generated file, don't edit" comment) before committing
  — this caught two separate off-by-one slicing bugs during development
  (a missing closing `</div>` for `.main`, and a duplicated trailing
  newline), both fixed before anything shipped.
  static/login.html and static/signup.html are standalone pages, small
  enough on their own, and are NOT part of this build — edit them directly.
- .github/workflows/deploy.yml `paths:` filter updated to also watch
  `app/**`, `frontend-src/**`, and `build.py` — otherwise a change to only
  one of those wouldn't have triggered a deploy at all.

Alternatives Considered:
- Frontend: Jinja2 server-side templates (rejected — adds a new dependency
  and changes how routes are served, for no benefit over a pre-build step
  given there's no other reason to add server-side rendering)
- Frontend: client-side fetching of page partials at navigation time
  (rejected — adds a network round-trip per page switch and more moving
  JS parts, for a codebase this size the build-step approach is simpler)

Status:
Accepted.

---

## Decision 006

Date: 2026-09-14

Decision:
Scope every workspace account (docs/DECISIONS.md 003) to exactly one owning
user. Previously, once multi-user login existed (docs/DECISIONS.md 004),
every logged-in user could see and switch into every workspace account —
signing up gave a stranger full access to everyone else's connected
platforms, scheduled posts, and analytics. This was the single biggest
open item in TODO.md. This does not touch login itself (still Decision
004) or the workspace-account concept itself (still Decision 003) — it
only adds an ownership boundary between the two.

Implementation:
- `accounts` gets a new `user_id INTEGER` column (migration: `ALTER TABLE`
  if missing, nullable at first since `users` may not exist yet at that
  point in startup).
- `app/db.py`: new `backfill_account_ownership()`, run once at startup
  after `seed_legacy_user_if_none_exist()` (order matters — needs at least
  one user to exist). Assigns any account still missing an owner
  (`user_id IS NULL` — i.e. every account that existed before this change)
  to the earliest-created user, so an existing install's data isn't
  orphaned. New `create_workspace_account(name, user_id)` helper, shared by
  the manual "Add account" flow and the new automatic one below.
- `app/auth.py`: `require_login` now returns `{"id", "username"}` instead
  of just the username string, so routes can check ownership. The ~20
  existing `Depends(require_login)` call sites only needed a type-hint
  change (`str` → `dict`); the one place that actually used the returned
  value (`GET /api/auth/me`) now reads `user["username"]`.
- `app/credentials.py`: `get_account_or_404(account_id, user_id)` now takes
  the requesting user's id and 404s (not 403) if the account doesn't exist
  *or* belongs to someone else — same response either way, so account IDs
  can't be probed to find out which ones exist.
- Every account-scoped endpoint (`/api/status`, `/api/publish`,
  `/api/library`, `/api/dashboard/summary`, the YouTube/Facebook connect
  *and* disconnect routes, all four Facebook/Instagram/YouTube analytics
  routes, and accounts list/create/rename/delete) now calls
  `get_account_or_404(account_id, user["id"])` before doing anything with
  that `account_id`. `disconnect_youtube`/`disconnect_facebook` previously
  didn't validate `account_id` at all (a pre-existing gap already flagged
  in TODO.md) — fixed as a side effect.
- `list_accounts` filters by `WHERE user_id = ?`; `create_account` sets the
  new row's owner to the creator. `delete_account`'s "can't delete your
  last account" check now counts only the requesting user's own accounts
  — the old global `COUNT(*) FROM accounts` was a real bug once more than
  one user existed (could block/allow deletion based on *other* users'
  account counts).
- `POST /api/auth/signup` now also creates one default workspace account
  for the new user (`create_workspace_account` + `account_cred_dir`), so a
  brand-new signup has somewhere to land instead of an empty account
  switcher — mirrors how Account 1 was seeded for the original
  single-tenant install (Decision 003).
- No frontend change needed: `frontend-src/app.js`'s account switcher
  already falls back to `accountsCache[0]` whenever its cached
  `currentAccountId` isn't in whatever `/api/accounts` returns (e.g. a
  stale `localStorage` value after this change) — verified this path
  directly rather than assuming it from reading the code.

Reason:
Project owner flagged this as the biggest real gap in TODO.md: nobody's
data was actually private from anyone else who signed up.

Alternatives Considered:
- Leaving orphaned (pre-migration) accounts unowned/inaccessible until
  manually claimed (rejected — silently locks the existing user out of
  their own data on upgrade, worse than picking a reasonable owner)
- 403 instead of 404 for "exists but not yours" (rejected — leaks which
  account IDs exist to a user who shouldn't know)
- Passing `user_id` as a decoupled second FastAPI dependency instead of
  changing what `require_login` returns (rejected — same number of call
  sites to touch, but two dependencies doing overlapping session lookups
  per request instead of one)

Status:
Accepted. Not yet done: an admin UI or CLI to manually reassign an
account's owner (would need direct DB access today, same gap as Decision
004's user-management item); deciding what should happen if the
first-created user's account is later deleted while orphaned accounts
still reference it (edge case, not currently possible via the API since
users can't be deleted at all yet).

---

## Decision 007

Date: 2026-09-17

Decision:
Guarantee every logged-in user owns at least one workspace account at all
times, checked on every authenticated request — not just at signup — as a
follow-up fix to Decision 006 (per-user data isolation).

Reason:
Auditing commit `55f798d` (Decision 006) for bugs found a real gap: its
`backfill_account_ownership()` migration assigns every pre-existing
account to a single earliest-created user. Multi-user login (Decision
004) had been live for two days before Decision 006 shipped, so if a
second real person had already signed up in that window and was using
the shared account, the migration would leave them owning zero accounts
— and the frontend's account switcher falls back to `account_id=1` when
its list is empty, which now belongs to someone else, so every page
would 404 for them. Reproduced this exact scenario with a test (two
pre-existing users, one shared account) before fixing it.

Implementation:
- `app/auth.py`: new `ensure_user_has_account(user_id, username)`,
  creates a workspace account for the user if they don't already own one.
  Called from `require_login` itself (runs on every authenticated
  request), not only at login or signup, so it also repairs anyone
  already mid-session on an existing cookie rather than requiring them to
  log out and back in.
- `POST /api/auth/signup` now calls this same helper instead of
  duplicating the "create a starter account" logic inline.
- Fixed a stale docstring in `app/auth.py` from before Decision 006 that
  still described workspace accounts as shared with no per-user
  restriction.

Alternatives Considered:
- Only checking at login (rejected — doesn't repair a session that's
  already active on a stale cookie; someone locked out today would stay
  locked out until their 30-day session happened to expire)
- A one-off manual data-repair script instead of a standing safety check
  (rejected — doesn't protect against the same zero-account state
  recurring for some other reason later; a standing invariant is cheaper
  than re-auditing for this specific failure mode every time)

Status:
Accepted. Important caveat, not fixable in code: if someone really was
locked out by the Decision 006 migration, this gives them a working app
again but with a **fresh, empty** account, not their old data back —
there's no record of who was using the original shared account under the
pre-isolation model, so their prior history can't be automatically
recovered. Flagged to the project owner to check the `users` table for
any account created between 2026-09-12 and 2026-09-14 that needs a
closer look (manual recovery would need direct DB access — same
admin-tooling gap noted in Decision 006).

---

## Decision 008

Date: 2026-09-17

Decision:
Switch the single-page app's client-side routing from a query string
(`/?page=dashboard`) to real paths (`/dashboard`, `/accounts`, ...).

Reason:
Requested by the project owner — shareable/bookmarked links looked
awkward as `?page=xxx` and cleaner as `/xxx`.

Implementation:
- `frontend-src/app.js`: `showPage()` and `goToNeedsAttention()` now call
  `history.replaceState(null, '', '/' + name)` instead of `'?page=' +
  name`. On initial load, `initialPageFromLocation()` reads
  `location.pathname` first; if it's not a recognized page it falls back
  to the old `?page=` query param once (so existing bookmarks/shared
  links don't just break) and immediately normalizes the URL to the new
  path form; if neither is present/recognized, defaults to `dashboard`.
- `server.py`: this is still one single-page app (one `index.html`,
  `build.py`) — the browser's URL changing doesn't by itself make
  `/accounts` a real server route, so a hard refresh, bookmark, or shared
  link on anything but `/` would 404 without a matching route. Added an
  explicit `_SPA_PAGES` list (must be kept in sync with
  `frontend-src/app.js`'s `PAGE_TITLES` keys) and registered each one via
  `app.add_api_route`, all serving the same `index.html` through the same
  login-gated `_serve_spa()` used by `/` — the client-side JS figures out
  which page to actually show once it loads. Deliberately did *not* add a
  catch-all for arbitrary unknown paths — those still correctly 404.

Alternatives Considered:
- A single generic `/{page_name}` path-parameter route instead of one
  explicit route per known page (rejected — would either need its own
  validation logic to reject unknown page names and 404 properly, or
  silently serve the SPA for any typo'd URL; an explicit list is simpler
  and keeps unknown-path 404s working exactly as before)
- `history.pushState` instead of `replaceState` (kept `replaceState`,
  unchanged from before this decision — this was only about the URL's
  *shape*, not about adding browser back/forward support for in-app
  navigation, which wasn't asked for and is a separate, bigger change to
  how the SPA tracks state)

Status:
Accepted. Verified: every `_SPA_PAGES` path returns the app for a
logged-in user and redirects to `/login` for a logged-out one (matching
`/`'s existing behavior); an unrelated/unknown path still 404s; existing
`/api/*` routes are unaffected (no shadowing); the JS's page-detection
logic was unit-tested directly (path-based, legacy query-based, bare `/`,
and garbage-path cases). Not verified: actual browser back/forward button
behavior and a real visual check on the live VM — no browser tooling in
this environment, same caveat as recent frontend-only sessions.
