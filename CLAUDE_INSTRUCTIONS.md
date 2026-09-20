# AI Development Instructions

You are working on an existing project: MediaFlow, a self-hosted
multi-platform video publishing dashboard.

## Before Making Changes
Always read, in this order:
1. docs/PROJECT_CONTEXT.md
2. SESSION_HANDOFF.md
3. TODO.md
4. docs/DECISIONS.md (skim for anything relevant to the task at hand)

Do not make changes until you understand the current project state and
architecture.

## Rules
- Do not randomly refactor working code.
- Do not delete functionality without the project owner's permission.
- Preserve existing architecture unless explicitly asked to change it.
- Check existing code before creating new files — reuse existing
  components/functions where reasonable, avoid duplicating functionality.
- Never commit anything under `credentials/` — it must stay gitignored.
  (See docs/DECISIONS.md 001 for why this matters.)
- Live VM config files (`mediaflow.nginx.conf`, `mediaflow.service`) can
  drift from this repo without warning — certbot, or a manual fix under
  time pressure, can edit the live file directly on the VM and never get
  reflected back here. Before telling the project owner to copy either of
  these repo files onto the VM, have them `diff` the repo version against
  the live one first (e.g. `diff mediaflow.nginx.conf
  /etc/nginx/sites-available/mediaflow`) and actually look at what's
  different — don't assume the repo copy is authoritative. Blindly
  overwriting caused a real HTTPS outage on 2026-09-20 (see
  docs/DECISIONS.md 011): the live file had a certbot-managed SSL server
  block the repo copy never had, and copying over it silently deleted
  HTTPS while HTTP kept working — which is exactly what made it a slow,
  confusing diagnosis instead of an obvious one.
- Backend logic lives under `app/` (routes in `app/routes/*.py`), not in
  `server.py` — see docs/DECISIONS.md 005. Add new routes as a new or
  existing `app/routes/*.py` file and register it in `server.py`, don't
  add routes directly to `server.py`.
- Frontend: edit `frontend-src/` (per-page HTML, style.css, app.js), not
  `static/index.html` directly — it's a generated file. Run
  `python3 build.py` after any `frontend-src/` change (see
  docs/DECISIONS.md 005). `static/login.html` / `static/signup.html` are
  standalone pages, not part of this build — edit those directly.
- Before writing to CHANGELOG.md or SESSION_HANDOFF.md, check the actual
  `git diff` / `git log` for what changed — do not document from memory
  or assumption.

## After Completing Work
1. Update CHANGELOG.md with what changed and why.
2. Update TODO.md (check off completed items, add new ones discovered).
3. Update SESSION_HANDOFF.md with current state and next step.
4. If an architectural or technical decision was made, add an entry to
   docs/DECISIONS.md (decision, reason, alternatives considered, status).

## Removing Code
If something is removed, document in CHANGELOG.md:
- What was removed
- Why it was removed
- What replaced it (if anything)

## Before Ending a Session
Make sure SESSION_HANDOFF.md reflects:
- What was completed this session
- What's incomplete or in progress
- Any new issues discovered
- The recommended next task
