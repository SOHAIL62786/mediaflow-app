"""
Multi-user login (see docs/DECISIONS.md 004).

Replaces the old single shared HTTP Basic Auth password with real per-user
accounts: hashed passwords, session-cookie identity, and custom Sign In /
Sign Up pages. Unrelated to the *workspace* accounts feature in
app/credentials.py / app/routes/accounts.py (docs/DECISIONS.md 003) — every
logged-in user can see and switch between all workspaces, there's no
per-user restriction on which ones they can access.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, Request

from app.config import APP_PASSWORD, APP_USERNAME
from app.db import get_db

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
            SELECT users.id, users.username, sessions.expires_at
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


def require_login(request: Request) -> str:
    """FastAPI dependency used across the API. Kept returning just the
    username (same as the old Basic Auth version) so none of the many
    existing `user: str = Depends(require_login)` route signatures needed
    to change — only how that identity is established did."""
    user = get_user_from_session(request.cookies.get(SESSION_COOKIE_NAME))
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in")
    return user["username"]
