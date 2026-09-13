# Session Handoff

## Last Updated
2026-09-12

## Current Task
Project owner asked for a proper Sign In / Sign Up page instead of the
generic browser Basic Auth popup. Clarified up front whether "sign up"
meant real multi-user accounts, a nicer single-password page, or
admin-created users only — project owner chose real multi-user accounts:
different people can each register their own login, and everyone who
does shares the same MediaFlow dashboard and data (no per-user data
separation, just per-user credentials).

Follow-up in the same session: after the above shipped, project owner
sent a live screenshot showing the Analytics video list looking broken
on mobile (thumbnail and Metrics button floating oddly, not aligned with
the title) — a real production video title with hashtags and an Arabic
salutation glyph was wrapping to 4+ lines and exposing a pre-existing
`align-items:center` bug in `.lib-row` (unrelated to the login work
above, just surfaced around the same time). Fixed and pushed separately
— see Progress below.

## Progress
Completed and pushed (009dd22): fixed `.lib-row`'s alignment — it used
`align-items:center`, which centers flex items against the tallest one
in the row. A long/mixed-script video title could wrap tall enough that
the thumbnail and action button ended up centered against the *middle*
of the wrapped title instead of pinned to the top, looking broken.
Fixed by clamping the title to 2 lines (`-webkit-line-clamp`) and
switching to `align-items:flex-start`. Affects all three Analytics
video-row renderers and the Dashboard's Recent Activity list (shared
`.lib-row`). Verified with the exact reported title via a headless
mobile render — thumbnail/title/button now measure identical top offsets
in every row. Small, CSS-only, low-risk change.

Completed, tested locally, and pushed (2f9cf4e):

- `server.py`:
  - New `users` (id, username, password_hash, created_at) and `sessions`
    (token, user_id, created_at, expires_at) tables.
  - Passwords hashed with PBKDF2-HMAC-SHA256, random per-user salt,
    260,000 iterations (OWASP's 2023 recommended minimum) — stdlib
    `hashlib`/`secrets` only, no new dependency.
  - Session identity is a random token in an HttpOnly/SameSite=Lax
    cookie (`mf_session`, 30-day expiry) — replaces HTTP Basic Auth
    entirely, which is what makes a custom login page possible instead
    of the browser's native popup.
  - `require_login` rewritten to check the session cookie instead of
    Basic Auth credentials, but kept its old return signature (just the
    username) — none of the ~20 existing `Depends(require_login)` route
    signatures needed to change.
  - New routes: `GET /login`, `GET /signup` (public; redirect to `/` if
    already logged in), `POST /api/auth/signup`, `POST /api/auth/login`,
    `POST /api/auth/logout`, `GET /api/auth/me`. `GET /` now redirects
    to `/login` instead of a Basic Auth 401 when not authenticated.
  - Backward compat: if `APP_USERNAME`/`APP_PASSWORD` env vars are set
    and no `users` row exists yet, one account is seeded from them on
    first boot. If neither is set, a one-time random-password account is
    created and printed to the server log instead. Either way this only
    happens once — from then on it's an ordinary account.
- `static/login.html`, `static/signup.html` (new): standalone pages
  outside the SPA, matching MediaFlow's existing visual language (dark
  brand panel + form, collapsing to just the form on mobile — top-aligned
  there, not vertically centered, so an on-screen keyboard doesn't
  awkwardly cover a centered form). Signup has live "passwords match"/
  min-length validation; both show an inline error banner instead of a
  native browser prompt on failure.
- `static/index.html`: sidebar's user card (previously hardcoded
  "Admin / admin@example.com") now shows the real logged-in username +
  first-letter avatar, and has a working Log Out button
  (`POST /api/auth/logout` then redirect to `/login`). Added a global
  `fetch` wrapper that redirects to `/login` on any 401 response, so an
  expired/invalidated session bounces to sign-in instead of every page
  silently failing to load its data.
- `docs/DECISIONS.md`: added Decision 004 documenting that this reverses
  the login part of Decision 003 ("single shared login, not separate
  user logins") — the *workspace*-accounts concept from Decision 003
  (independent platform connections/posts/analytics, switched via the
  top-right dropdown) is unrelated and unchanged; what changed is that
  multiple *people* can now each have their own login into that same
  shared dashboard.
- `docs/PROJECT_CONTEXT.md`, `README.md`, `DEPLOYMENT_GUIDE.md`,
  `mediaflow.env.example`: updated to describe the new login model
  instead of Basic Auth. Also fixed a few now-stale in-code comments in
  server.py that referenced "HTTP Basic Auth" (the YouTube OAuth
  callback comment and the `/media/` public-serving comment) for
  technical accuracy.
- `TODO.md`: added the open-signup tradeoff (see below) and lack of an
  admin user-management UI as new items; removed the now-obsolete
  "harden default password" item (there's no more shared default
  password to harden).

Testing done (this repo's dev environment has no real platform
credentials, but none of this needed any):
- curl: signup, duplicate-username rejection (case-insensitive — "Admin"
  correctly blocked when "admin" exists), short-password rejection,
  invalid-username-character rejection, wrong-password login rejection,
  correct login, logout, post-logout 401 on `/api/auth/me`, and legacy
  `APP_USERNAME`/`APP_PASSWORD` seeding+login — all verified directly
  against the running server.
- Headless Chromium (Puppeteer): both pages at desktop + mobile widths,
  live signup validation states, login error banner, post-signup and
  post-login redirect to `/`, sidebar user card showing the real
  username, logout redirecting to `/login`, the server-side redirect
  guard (direct navigation with an invalid cookie), and the client-side
  401 fetch guard (session invalidated mid-app, triggered by a normal
  in-app action) — no console/page errors in any of it.

Currently Working On:
- Nothing else — both the auth feature and the layout fix are complete,
  tested, pushed, and deployed successfully.

Not Completed / things noticed but NOT fixed (worth a look next time):
- Sign-up is fully open to anyone who reaches the app's URL — offered as
  a choice (gated vs. open) and open was explicitly chosen by the
  project owner. Noted an optional `SIGNUP_CODE` env var gate as a future
  lever in TODO.md, not built since it wasn't asked for.
- No admin UI to list/remove users or force a password reset — would
  need direct DB access (`users`/`sessions` tables) right now.
- The `.lib-row` layout fix was verified against the exact title that
  broke in production, but only with mocked API data (no real connected
  YouTube account in this dev environment) — worth a glance at the real
  Analytics page next time credentials are available, just to confirm.
- Everything from prior sessions' "Not Completed" lists is still open —
  see TODO.md (scheduler-at-scale, account_id-in-URL fragility,
  disconnect_youtube/facebook not 404ing on bad IDs, Facebook/Instagram
  Analytics can't do a "views today" per-post view, visual-redesign pass
  on pages other than Dashboard).

## Important Information
- `credentials/` is gitignored and will NOT be present when a new session
  clones this repo. Each new session/machine needs credentials supplied
  separately (not via git) — see docs/PROJECT_CONTEXT.md.
- Repo write access for a Claude session is granted via a GitHub
  fine-grained PAT (Contents: read/write, this repo only), supplied by
  the project owner via a plaintext file (`gittoken.md`). This has been
  flagged as exposed across multiple sessions now — still not rotated as
  of this session.
- **Login is now real multi-user accounts, not one shared password** —
  see Decision 004. Anyone who signs up gets full access to the shared
  dashboard and all connected platforms; there's no invite gate or
  per-user permission scoping.
- Deleting an account (workspace) via the Accounts page is destructive
  and immediate (no soft-delete/undo) — unrelated to the new user-login
  accounts, don't conflate the two "accounts" concepts (see Decision 004).
- The sidebar's collapsed/expanded state and width are stored in the
  browser's `localStorage`, so they're per-browser, not per-account or
  server-synced.

## Next Step
Both changes from this session are live. Worth verifying the login/
signup flow once more on the live VM directly (this session's testing
was all local — no reason to expect VM-environment-specific issues, but
it's a security-sensitive feature worth a real-world check), and
glancing at the real Analytics video list once a YouTube account with
actual upload history is available, to confirm the row-alignment fix
looks right outside of mocked data too. Then pick up whatever's next
from TODO.md.

## Security Note
A live GitHub fine-grained PAT stored in plaintext in `gittoken.md` has
been used across multiple sessions now, including this one (once the
push is confirmed). Still recommend rotating it and moving to a secrets
manager or per-session token — this has been flagged repeatedly without
being addressed.

Separately, worth being explicit about: this session's change means
anyone who can reach this app's URL can now create their own account and
get full publishing access to every connected platform. That's an
explicit, confirmed choice by the project owner (not a bug), but it
raises the stakes on network-level access control (firewall / who can
reach the VM) compared to before, when only people who already knew a
single shared password could get in.

## Known Issues
See "Not Completed / things noticed but NOT fixed" above.
