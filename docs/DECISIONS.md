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

---

## Decision 009

Date: 2026-09-18

Decision:
Add an optional `SIGNUP_CODE` env var that gates `/api/auth/signup`
behind a shared invite code. Unset (the default) keeps signup exactly as
open as it's always been — this is additive, not a change to current
behavior unless the project owner opts in.

Reason:
Flagged in TODO.md since Decision 006: signup is fully open by design,
with this as the pre-agreed escape hatch if it ever turns out to be too
permissive. Picked as the next actionable High Priority item (the other
open items either need a human to check production data or a product
decision from the owner first).

Implementation:
- `app/config.py`: `SIGNUP_CODE = os.environ.get("SIGNUP_CODE", "")`.
- `app/routes/auth_pages.py`: `POST /api/auth/signup` takes an optional
  `signup_code` form field; if `SIGNUP_CODE` is set, compares it with
  `secrets.compare_digest` (constant-time, same care as password
  verification elsewhere in this file) and 403s on mismatch *before*
  touching the DB — a rejected attempt never creates a user row, so a
  wrong code can't be used to enumerate/reserve usernames. New public
  `GET /api/auth/signup-config` returns only `{"require_code": bool}` —
  never the code itself — so the signup page can decide whether to show
  the field without needing to guess or hardcode it.
- `static/signup.html`: the invite-code field is hidden by default and
  only shown (and marked required) if `signup-config` says it's needed —
  most installs will never see it. If that fetch fails for any reason,
  the field stays hidden but the server-side check still runs, so
  nothing is bypassed either way.
- Also fixed a stale claim on the signup page while in this file: the
  brand-panel note still said "everyone who signs up shares the same
  MediaFlow dashboard and connected accounts," which stopped being true
  once per-user isolation shipped (Decision 006) — actively misleading a
  new signup about how their data is scoped. Replaced with an accurate
  line about each account being private.

Alternatives Considered:
- Always showing the invite-code field, letting the backend silently
  ignore it when unset (rejected — permanently adds visible friction/
  confusion to the common case, which is staying fully open, just to
  avoid one small `GET` request)
- A single shared password for all new signups baked into a build step
  instead of an env var (rejected — env var is consistent with how
  `APP_USERNAME`/`APP_PASSWORD` and `PUBLIC_BASE_URL` are already
  configured for this project, no new configuration mechanism needed)

Status:
Accepted, but not yet turned on for the live install — `SIGNUP_CODE` is
unset by default, so nothing changes unless/until the project owner sets
it. Verified: gate off behaves identically to before (any or no code
accepted); gate on rejects a missing or wrong code with 403 and creates
no user row either way, accepts the correct code, and the resulting user
is fully functional (owns an account, etc.); `signup-config` reports the
right state in both cases. `pyflakes` clean. Not verified: the
conditional show/hide of the field in an actual browser — no browser
tooling in this environment.

---

## Decision 010

Date: 2026-09-18

Decision:
Add an admin role and a Settings-page admin panel: list every user, force
a password reset, promote/demote admins, delete a user (once they own no
accounts), and reassign a workspace account's owner. Requested item from
TODO.md High Priority.

This introduces a real privilege distinction that didn't exist before —
every user has been equal since Decision 004. Treated with the same
caution as Decision 006 (schema-changing, security-relevant, one-way
migration): built and tested locally, held for explicit project-owner
review before pushing, not auto-deployed the way the SIGNUP_CODE feature
(Decision 009) was, since that one was opt-in-safe by construction and
this one is not — it decides who gets elevated access.

Reason:
The recent isolation work (Decision 006/007) made this gap sharper: fixing
a locked-out user or reassigning an account previously meant direct DB
access. This closes that gap with a real UI, and distributes admin
access across more than one account if desired, rather than leaving a
single admin as the only person who could ever fix anything.

Implementation:
- `users.is_admin INTEGER NOT NULL DEFAULT 0` (migration: `ALTER TABLE`
  if missing, same pattern as `accounts.user_id`).
- `app/db.py`: `backfill_admin_flag()` — if no user is marked admin yet,
  grants it to the single earliest-created user only, never to every
  pre-existing user. Deliberately narrower than
  `backfill_account_ownership()`'s reasoning would allow, because the
  entire point of an admin role is to limit who has it — we can tell
  "the very first user" apart from everyone else, but can't tell "the
  real owner" apart from "someone who happened to sign up early" for
  anyone past that first row. Idempotent (a no-op once any admin exists),
  so it never overrides a deliberate later promotion/demotion. Run at
  startup after `seed_legacy_user_if_none_exist()` (needs ≥1 user).
- `app/auth.py`: `get_user_from_session` and `require_login` now also
  return `is_admin`. New `require_admin` dependency — wraps
  `require_login`, 403s if not admin. Every route in the new
  `app/routes/admin.py` uses `require_admin`, never `require_login`, since
  every one of them exposes or changes another user's data by design —
  exactly what Decision 006 otherwise exists to prevent, so this needed
  its own explicit, separate gate rather than being layered onto an
  existing one.
- New routes: `GET /api/admin/users` (id, username, created_at, is_admin,
  account_count), `GET /api/admin/accounts` (every account + owner,
  cross-user by design here), `POST .../accounts/{id}/reassign`, `POST
  .../users/{id}/set-password` (also deletes that user's sessions —
  otherwise a changed password wouldn't invalidate a session issued under
  the old one), `POST .../users/{id}/set-admin`, `DELETE
  .../users/{id}`.
- Delete-user guards, mirroring the existing "can't delete your last
  account" pattern in `app/routes/accounts.py`: can't delete yourself
  (log in as another admin instead), can't delete a user who still owns
  ≥1 account (reassign first — avoids silently orphaning their data or
  quietly deleting it as a side effect), can't demote or delete the last
  remaining admin (would need direct DB access to recover from).
- `GET /api/auth/me` now also returns `is_admin`, so the frontend knows
  whether to render the panel at all.
- `frontend-src/pages/settings.html` + `frontend-src/app.js`: two new
  cards (Users, Workspace accounts) on the Settings page, hidden unless
  `is_admin` is true. Reuses the existing account-row/button CSS classes
  from the Accounts page rather than introducing new ones. Reassignment
  is a `<select>` per account row (all users as options); everything else
  follows the same `prompt()`/`confirm()`/`showToast()` pattern already
  used for renaming/deleting a workspace account.

Alternatives Considered:
- Granting admin to every user who existed before this migration
  (rejected — same reasoning as Decision 007's backfill: we can't
  distinguish the real owner from an early signup for anyone past the
  first row, and granting admin too broadly defeats the purpose of
  having the role at all)
- Cascading a deleted user's accounts to another user automatically
  instead of blocking the delete (rejected — silently moving someone's
  platform connections/posts as a side effect of an unrelated action is
  the kind of surprising behavior this project has been actively fixing
  all session; requiring an explicit reassign first makes the data
  movement its own visible, intentional step)
- No "last admin" guard (rejected — would allow a mistake to lock the
  project owner out of their own admin panel with no recovery path
  short of direct DB access again, defeating a chunk of this feature's
  purpose)

Status:
Accepted, reviewed and approved by the project owner, pushed to `main`.
Verified locally before push: access control (non-admin 403s on every
`/api/admin/*` route); listing; reassignment (ownership actually moves,
previous owner self-heals a new account per Decision 007's guarantee);
forced password reset (old sessions invalidated, new password works);
promote/demote (including the last-admin guard, tested by demoting down
to one admin and confirming the final demotion is blocked); delete-user
(self-delete blocked, blocked while they own accounts, works once
reassigned, session invalidated). Full isolation + routing + signup-gate
regression suite re-run alongside — still passing. `pyflakes` and `node
--check` clean. Not verified: the UI in an actual browser — no browser
tooling in this environment.


## Decision 011

Date: 2026-09-20

Incident:
A ~30-minute HTTPS outage on sohailanalytics.online, caused by an assistant
instruction, not by any code change. Debugging a real `ERR_CONNECTION_ABORTED`
on video publish led to checking nginx's `client_max_body_size`; the fix
instruction was `sudo cp mediaflow.nginx.conf /etc/nginx/sites-available/mediaflow`
— copying the repo's version over the live one. The live file had a
`server_name sohailanalytics.online` HTTPS server block that certbot had
added directly on the VM at some earlier point, never captured in this
repo (the repo's version only ever had the generic `server_name _;`
placeholder). The copy silently deleted that block. HTTP kept working
throughout (same `listen 80` block was still there), which is what made
this slow to diagnose — several wrong theories (AWS Security Group,
Cloudflare, Chrome's automatic HTTPS upgrade) were chased before the
actual cause surfaced: `sudo certbot --nginx -d sohailanalytics.online`
returned "Could not automatically find a matching server block," which
is the actual root cause made visible — certbot could no longer find the
`server_name` it had originally attached to.

Fix:
`mediaflow.nginx.conf` now pins `server_name sohailanalytics.online;`
instead of the generic `_;` placeholder, so certbot's nginx plugin can
find and re-attach to this exact block going forward, and re-running
certbot re-adds the `listen 443 ssl` block and cert paths.

Standing rule (see CLAUDE_INSTRUCTIONS.md):
Never tell the project owner to copy `mediaflow.nginx.conf` (or
`mediaflow.service`) onto the VM without first diffing it against what's
actually live there. Live infra config can be edited directly on the VM
(by certbot, or under time pressure) without that change ever reaching
this repo — the repo copy is not guaranteed to be authoritative just
because it's the one under version control.

Status:
Fixed and confirmed working by the project owner. The live VM's nginx
config (with certbot's SSL block) has not yet been pulled back into this
repo file — TODO.md tracks this as a follow-up so the repo stops being a
stale/incomplete picture of the real config.


---

## Decision 012

Date: 2026-09-20

Decision:
Add an automatic ffmpeg re-encode-and-retry fallback for Instagram
publishing, in `app/uploaders.py`, used by both the immediate
`/api/publish` flow and the background scheduler.

Background:
Instagram's Content Publishing API can accept a video, download it fine,
and still reject it during its own processing step with an undocumented
error code (`status_code: "ERROR"`, e.g. code 2207077) — Meta doesn't
publish what these mean. Root-caused on a real failing video from a
project-owner export (CapCut, H.264 High profile, 1080x1920, ~15Mbps,
30fps): a `-c copy` remux with `+faststart` alone (fixing only moov-atom
placement) did NOT resolve it, but a real re-encode down to H.264 Main
profile + yuv420p + AAC did, per a working local script
(`upload_reel.py`) the project owner had already validated by hand. That
script's "raw first, ffmpeg re-encode only on failure, retry once"
pattern is what got ported in, rather than always re-encoding (slow and
lossy, unnecessary for the common case where the raw file is fine).

Implementation:
- `_attempt_instagram_publish()` (the pre-existing create -> poll ->
  publish logic, unchanged) is called once with the original URL. On
  `status_code == "ERROR"` specifically, it's tagged
  `reencode_worth_trying: True`.
- `_upload_to_instagram()` wraps that: if the first attempt fails AND is
  tagged retryable AND the caller supplied the local file path plus a
  `build_media_url` callback, it re-encodes
  (`ffmpeg -c:v libx264 -profile:v main -pix_fmt yuv420p -c:a aac -b:a
  128k -ar 44100 -movflags +faststart`) into a new file in `UPLOAD_DIR`
  (so `/media/{filename}` can serve it) and retries exactly once.
  Deliberately gated by that flag: a create-time failure (bad token,
  malformed request) or the 5-minute processing timeout are NOT
  retried this way, since re-encoding doesn't address either and would
  only double an already-long wait.
- `ffmpeg` is optional, checked via `shutil.which`. If missing, the
  original error is returned with a note appended — publishing behaves
  exactly as before this change, just without the automatic retry.
- Both call sites (`app/routes/status_publish.py`'s immediate publish,
  `app/scheduler.py`'s scheduled publish) already had the local file
  on disk at the point Instagram is attempted (deletion only happens
  after all platforms are tried), so no change to file-lifecycle timing
  was needed — just threading `local_file_path` and `build_media_url`
  through.

Known tradeoff, accepted:
A publish that needs this fallback can now take up to roughly 10 minutes
worst case (up to 5 min Instagram processing + real ffmpeg re-encode +
up to another 5 min processing on retry), all within one blocking
`/api/publish` request. `mediaflow.nginx.conf`'s `proxy_read_timeout`/
`proxy_send_timeout` are already 600s (set for large video uploads),
which covers this, but it's a real, deliberately-accepted latency cost
for the cases it applies to — not attempted for the failure modes
(timeout, auth) where it wouldn't help, specifically to avoid making
this worse than necessary.

Verification:
No real Instagram credentials available in this environment (same
constraint as the `analytics_meta.py` fix), so verified via: a
synthetic test video generated with the same H.264 High-profile
characteristics as the project owner's actual failing file, confirming
`_reencode_for_instagram()` produces H.264 Main profile / yuv420p / AAC
/ moov-atom-first output; the full retry path exercised end-to-end with
a mocked Graph API (raw attempt returns `ERROR` -> re-encode -> retry
succeeds); confirmed exactly one retry is attempted (no runaway loop)
when the retry also fails; confirmed create-time/auth errors never
trigger the fallback; confirmed a missing-ffmpeg environment degrades
to the pre-existing behavior instead of crashing; confirmed the
re-encoded temp file is always cleaned up; `pyflakes`/`py_compile`
clean across the whole `app/` package; full existing test suite
(status/library/dashboard endpoints) still passes.

Status:
Accepted. Not yet confirmed against a real Instagram account/video on
the live VM — TODO.md tracks this, same caveat as other Meta-API-facing
changes in this environment.

---

## Decision 013

Date: 2026-09-21

Decision:
Add "Save as Draft" and "Save as Template" to the Upload form, backed by
one new table (`upload_presets`) rather than two. A draft and a template
turned out to be the same shape of data (title, caption, tags,
platforms, privacy, made-for-kids/synthetic-media checkboxes) with two
different lifecycles, not two different schemas — giving them separate
tables would have meant duplicating the same columns, CRUD functions,
and API routes twice for no real benefit. A `kind` column ('draft' |
'template') plus a nullable `name` (required for templates, always null
for drafts, since drafts are identified by their own title/timestamp
instead of a user-given label) covers both:
- **Drafts**: unnamed, one-shot. "Resume" on the frontend loads the
  saved fields into the form AND deletes the draft — it's consumed once
  you act on it, same mental model as a real draft.
- **Templates**: user-named, reused indefinitely. "Apply" loads the
  fields into the form but does NOT delete the template.

Both are scoped to a workspace-account (like uploads/credentials), not
to the logged-in user, via the same `get_account_or_404(account_id,
user_id)` ownership check used everywhere else — consistent with
Decision 003/006's account-vs-user split.

Deliberately NOT included: a video file. A draft/template is metadata
you come back to and attach a (possibly different, possibly
not-yet-chosen) file to — not a half-uploaded video sitting in storage.
This was the main open question noted when this item first went into
TODO.md, and keeping files out of scope was chosen because:
1. It avoids a much larger feature (storing, and safely cleaning up,
   arbitrary video files indefinitely for drafts that might never be
   resumed) that TODO.md already flags as a general risk area (orphaned
   temp-file cleanup).
2. "Resume"/"Apply" can then be a pure frontend action (populate form
   fields) with no new publish/schedule code path needed — reusing the
   existing, already-tested `/api/publish` flow untouched.
3. It matches how most people actually think of a "draft" for something
   like this: the tedious-to-retype details (title, tags, per-platform
   settings), not necessarily the file itself.

Alternatives Considered:
- Two separate tables (`drafts`, `templates`) matching the original
  phrasing in TODO.md — rejected once it became clear the schemas
  would be identical; a `kind` flag on one table does the same job with
  less duplication.
- Storing the video file with a draft (so "Resume" could publish
  directly without re-selecting a file) — rejected for now, see above.
  Could revisit later as a distinct, explicitly-scoped feature if
  needed.
- Scoping presets per-user instead of per-account — rejected for
  consistency with how every other piece of upload-related data
  (uploads, credentials) is already account-scoped, not user-scoped.

Status:
Accepted. Backend verified directly (curl): full CRUD for both kinds,
template-name-required validation, empty-title-and-caption rejection,
cross-user ownership isolation (404, matching the existing pattern), and
that deleting an account cleans up its presets (no orphaned rows).
Frontend verified with a headless-browser walkthrough on desktop and
mobile: save draft, save template (name prompt), tab switching, Apply
populating the form without deleting the template, Resume populating
the form AND deleting the draft, no console errors, no horizontal
overflow on mobile. `pyflakes` clean across `app/`.

---

## Decision 014

Date: 2026-09-22

Decision:
Remove the Connected Accounts and Publishing Tips panels from the Upload
page's sidebar. Add a third "History" tab alongside Drafts/Templates that
auto-logs every form actually submitted to /api/publish (regardless of
outcome), opening a popup with the full submitted fields plus Use/Delete
buttons, rather than the inline Apply/Delete buttons Drafts/Templates use.

Implementation:
- `upload_presets` table/CRUD (Decision 013) reused as-is for the new
  kind='history' — no schema change needed, `kind` was already a free
  TEXT column. `VALID_KINDS` (list/delete) now includes 'history';
  `VALID_CREATE_KINDS` (the public POST endpoint) deliberately does NOT —
  history can only be created by /api/publish itself, not user-POSTed,
  so it stays a genuine log rather than something fakeable.
- `create_upload_preset(kind="history", ...)` called from inside
  `publish()` right after form validation, before the scheduled/immediate
  branch — so it captures what was submitted regardless of whether the
  publish succeeds, partially fails, fully fails, or gets scheduled.
- New `prune_upload_history(account_id, keep=50)`, called right after
  each save, keeps history from growing unbounded (drafts/templates don't
  need this — they only exist when a user explicitly saves one).
- Frontend: History rows render without inline action buttons — clicking
  anywhere on the row opens a popup (reusing the existing `.modal-overlay`
  pattern from the Analytics video-detail modal) showing every submitted
  field, with Use (loads into the form) and Delete inside the popup.
- Used the existing pill-button tab style (matching Drafts/Templates)
  rather than a literal `<input type="radio">`, for visual consistency —
  same single-select behavior either way.

Reason:
Project owner wanted the Upload page's sidebar decluttered (Connected
Accounts already lives on its own Platforms page; Publishing Tips wasn't
providing enough value to keep) and a way to review/reuse/discard past
publish attempts without having to remember to save a draft first.

Verified:
- Functional test via FastAPI TestClient: publish → history auto-saves
  with correct fields → manual POST with kind=history correctly rejected
  (400) → delete removes it → list reflects the deletion
- Pruning verified directly: 10 inserts + prune(keep=3) leaves exactly the
  3 most recent, oldest-first-out
- `python3 -m py_compile` on every changed backend file
- `node --check` on the rebuilt static/index.html's JS
- Duplicate-ID sweep on the rebuilt static/index.html — only pre-existing
  JS template-literal false positives (`${a.id}` etc.), no real duplicates

Status:
Accepted.

---

## Decision 015

Date: 2026-09-23

Decision:
Add a Dashboard / Table view toggle to the Analytics page. Table view
renders every video/post for the current platform as a sortable
spreadsheet-style grid (one row per video, one column per metric) instead
of the card-list + charts Dashboard view.

Implementation:
- No backend/API changes — Table view renders from the exact same
  `/api/analytics/summary` (and facebook/instagram equivalents) response
  already being fetched for Dashboard view, cached client-side
  (`lastAnalyticsData`) so toggling between the two views is instant, no
  refetch, no loading flicker.
- Columns are exactly the fields the summary endpoint already returns per
  video — no extra per-row detail fetches: YouTube gets period views,
  lifetime views, watch time, avg. retention, likes, comments; Facebook
  and Instagram get their narrower existing field sets (their summary
  endpoints return less per-video detail than YouTube's does).
- Click a column header to sort by it, click again to flip ascending/
  descending. Click a row to open the same metrics popup Dashboard view's
  "Metrics" button uses.
- The existing Top 5/10/25/All limiter carries over into Table view; the
  sort-by dropdown doesn't (superseded by clickable column headers there).

Reason:
Project owner wanted an easier way to compare videos side by side than
scrolling a card list one at a time.

Verified:
- `node --check` on the rebuilt static/index.html's JS
- CSS brace-balance check across the full stylesheet (a mid-edit mistake
  — a new CSS block landed inside an existing rule instead of after it —
  was caught this way before it shipped, then fixed properly)
- Duplicate-ID sweep on the rebuilt output — confirmed the new table's
  reused `#videoFilterBarContainer` id follows the same safe pattern
  already established elsewhere on this page (only one live instance in
  the DOM at any given time, since Dashboard/Table fully replace the
  page body rather than coexisting)
- Manual trace of state flow: platform switch, day-range change, and
  sort/limit changes all behave correctly whichever view is active

Status:
Accepted.
