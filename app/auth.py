"""
Multi-user login (see docs/DECISIONS.md 004).

Replaces the old single shared HTTP Basic Auth password with real per-user
accounts: hashed passwords, session-cookie identity, and custom Sign In /
Sign Up pages. As of docs/DECISIONS.md 006, this is also where each user's
workspace-account ownership (app/credentials.py / app/routes/accounts.py,
Decision 003) is enforced from — see ensure_user_has_account() below.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, Request

from app.config import APP_PASSWORD, APP_USERNAME
from app.credentials import account_cred_dir
from app.db import create_workspace_account, get_db

SESSION_COOKIE_NAME = "mf_session"
SESSION_LIFETIME_DAYS = 30
PBKDF2_ITERATIONS = 260_000  # OWASP-recommended minimum for PBKDF2-SHA256 as of 2023


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algo, iterations, salt, hex_digest = stored_hash.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations))
        return secrets.compare_digest(digest.hex(), hex_digest)
    except (ValueError, AttributeError):
        return False


def seed_legacy_user_if_none_exist():
    with get_db() as conn:
        if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            return
        username = APP_USERNAME or "admin"
        password = APP_PASSWORD or secrets.token_urlsafe(12)
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, hash_password(password), datetime.now(timezone.utc).isoformat()),
        )
    if APP_PASSWORD:
        print(
            "\n"
            f"*** No accounts existed yet — created one from APP_USERNAME/APP_PASSWORD: '{username}'.    ***\n"
            "*** Log in with that once; everyone else should use Sign Up for their own account.          ***\n"
        )
    else:
        print(
            "\n"
            "*** No accounts existed and APP_USERNAME/APP_PASSWORD weren't set — created a one-time      ***\n"
            f"*** account so you're not locked out -> username: {username}  password: {password}\n"
            "*** Log in with that once, then use Sign Up for real accounts going forward.                ***\n"
        )


def get_user_by_google_sub(google_sub: str):
    """Returns the {id, username} row for a returning Google sign-in, or
    None for a first-time one. Matched on google_sub (Google's own stable
    per-person ID), never on email — someone can change their Google
    account's email address without it changing which MediaFlow account
    they land in. See docs/DECISIONS.md 016."""
    with get_db() as conn:
        return conn.execute(
            "SELECT id, username FROM users WHERE google_sub = ?", (google_sub,)
        ).fetchone()


def _sanitize_username_candidate(raw: str) -> str:
    # Same allowed charset as api_signup's username validation
    # (app/routes/auth_pages.py) — letters, numbers, '_', '-', '.' — so a
    # Google-derived username can't slip past a rule a manually-typed one
    # can't. An email's local-part before '@' is usually clean already;
    # this only matters for the unusual ones (e.g. a '+' alias).
    cleaned = "".join(c if (c.isalnum() or c in "_-.") else "-" for c in raw).strip("-_.")
    if len(cleaned) < 3:
        cleaned = (cleaned + secrets.token_hex(3))[:32]
    return cleaned[:32]


def _unique_username_from_google(email: str, display_name: str) -> str:
    local_part = email.split("@")[0] if email and "@" in email else (display_name or "user")
    base = _sanitize_username_candidate(local_part) or "user"
    with get_db() as conn:
        candidate = base
        suffix = 1
        while conn.execute("SELECT 1 FROM users WHERE username = ?", (candidate,)).fetchone():
            suffix += 1
            candidate = f"{base}{suffix}"[:32]
    return candidate


def create_user_from_google(google_sub: str, email: str, display_name: str = "") -> tuple:
    """Creates a brand-new user on a first-time Google sign-in. Returns
    (user_id, username).

    password_hash stays NOT NULL (no schema change to that constraint —
    see the ALTER TABLE note in app/db.py) but gets a placeholder value in
    a shape verify_password() already can't match: it splits the stored
    hash on '$' expecting exactly 4 parts ("pbkdf2_sha256$<iters>$<salt>
    $<hex>"), so a 3-part sentinel like this one always fails the unpack
    and returns False — no separate "is this a Google account" check
    needed anywhere a password gets verified. There's no "set a password"
    flow yet for a Google-only account (see TODO.md); until then, Google
    sign-in is the only way in for one."""
    username = _unique_username_from_google(email, display_name)
    placeholder_hash = f"google_oauth$no_password${secrets.token_hex(16)}"
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, created_at, google_sub, email) "
            "VALUES (?, ?, ?, ?, ?)",
            (username, placeholder_hash, datetime.now(timezone.utc).isoformat(), google_sub, email or None),
        )
        return cur.lastrowid, username


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=SESSION_LIFETIME_DAYS)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now.isoformat(), expires.isoformat()),
        )
    return token


def get_user_from_session(token: Optional[str]):
    if not token:
        return None
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT users.id, users.username, users.is_admin, sessions.expires_at
            FROM sessions JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ?
            """,
            (token,),
        ).fetchone()
        if not row:
            return None
        if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return None
    return row


def delete_session(token: Optional[str]):
    if not token:
        return
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def set_session_cookie(response, request: Request, token: str):
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_LIFETIME_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=(request.url.scheme == "https"),
        path="/",
    )


def ensure_user_has_account(user_id: int, username: str) -> None:
    """Safety net for per-user data isolation (docs/DECISIONS.md 006): a
    logged-in user should always own at least one workspace account, or
    the frontend's account switcher falls back to account_id=1 (see
    frontend-src/app.js) which now 404s on every page for anyone who
    doesn't own it — a fully broken app, not just a missing account.

    This can happen to someone who isn't a brand-new signup: multi-user
    login (Decision 004) was live for two days before per-user isolation
    (Decision 006) shipped, so any second person who'd already signed up
    in that window had the pre-existing shared account backfilled to only
    the single earliest-created user, not to them — leaving them with
    zero accounts. Checked on every authenticated request (not just
    login/signup) so it also repairs anyone already mid-session, not only
    people logging in fresh."""
    with get_db() as conn:
        if conn.execute("SELECT 1 FROM accounts WHERE user_id = ? LIMIT 1", (user_id,)).fetchone():
            return
    new_id = create_workspace_account(f"{username}'s account", user_id)
    account_cred_dir(new_id)


def require_login(request: Request) -> dict:
    """FastAPI dependency used across the API. Returns {"id", "username",
    "is_admin"} — previously just {"id", "username"}, but the admin panel
    (docs/DECISIONS.md 010) needs to know this on every request without a
    second DB round-trip. Route bodies that only cared about gating access
    (the vast majority) don't need any other change; the few that display
    the username (e.g. GET /api/auth/me) still read user["username"]."""
    user = get_user_from_session(request.cookies.get(SESSION_COOKIE_NAME))
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in")
    ensure_user_has_account(user["id"], user["username"])
    return {"id": user["id"], "username": user["username"], "is_admin": bool(user["is_admin"])}


def require_admin(request: Request) -> dict:
    """FastAPI dependency for the admin panel (docs/DECISIONS.md 010) —
    everything an admin can do (see every user, reassign any account's
    ownership, reset anyone's password) is real per-user data outside
    their own, so this must be its own explicit gate, never inferred from
    require_login succeeding. 403s (not 404) since admin routes aren't
    per-account resources someone could otherwise legitimately hit."""
    user = require_login(request)
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user
