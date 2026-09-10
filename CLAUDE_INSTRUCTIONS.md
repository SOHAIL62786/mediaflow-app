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
