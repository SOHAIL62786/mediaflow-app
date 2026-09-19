"""
Persistence (SQLite).

Every publish/schedule attempt gets a row here so the Dashboard, Scheduled,
and Published pages have real data to show instead of being static mockups.
Multi-account (workspace) support scopes rows by `account_id` (see
docs/DECISIONS.md 003). Multi-user login (see docs/DECISIONS.md 004) added
the users/sessions tables — unrelated to the account_id workspace concept.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from app.config import DB_PATH


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                title TEXT NOT NULL,
                caption TEXT,
                platforms TEXT NOT NULL,
                privacy TEXT,
                tags TEXT,
                made_for_kids INTEGER NOT NULL DEFAULT 0,
                contains_synthetic_media INTEGER NOT NULL DEFAULT 0,
                scheduled_time TEXT,
                status TEXT NOT NULL,
                results TEXT NOT NULL,
                video_path TEXT
            )
            """
        )
        # Migration for databases created before video_path existed (our own
        # local scheduler needs somewhere to find the file again later).
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(uploads)")}
        if "video_path" not in existing_cols:
            conn.execute("ALTER TABLE uploads ADD COLUMN video_path TEXT")

        # ---- Multi-account support ----
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                user_id INTEGER
            )
            """
        )
        # Migration for databases created before per-user account ownership
        # existed (see docs/DECISIONS.md 006). Nullable here because at this
        # point in startup the `users` table may still be empty (init_db()
        # runs before seed_legacy_user_if_none_exist()) — orphaned rows are
        # assigned to an owner afterwards by backfill_account_ownership().
        accounts_cols = {row["name"] for row in conn.execute("PRAGMA table_info(accounts)")}
        if "user_id" not in accounts_cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN user_id INTEGER")

        if "account_id" not in existing_cols:
            # Every existing row belongs to whatever was previously the one
            # and only account — becomes Account 1 below, unaffected.
            conn.execute("ALTER TABLE uploads ADD COLUMN account_id INTEGER NOT NULL DEFAULT 1")

        has_account_1 = conn.execute("SELECT 1 FROM accounts WHERE id = 1").fetchone()
        if not has_account_1:
            # Preserves the original single-tenant install as "Account 1" —
            # same name shown before multi-account existed, so nothing about
            # the first account changes from the user's point of view.
            conn.execute(
                "INSERT INTO accounts (id, name, created_at) VALUES (1, ?, ?)",
                ("Moiz", datetime.now(timezone.utc).isoformat()),
            )

        # ---- Multi-user login (replaces single shared APP_USERNAME/
        # APP_PASSWORD Basic Auth — see app/auth.py for the seeding step
        # that runs after this) ----
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        # Migration for databases created before the admin role existed (see
        # docs/DECISIONS.md 010) — same ALTER-TABLE-if-missing pattern as
        # accounts.user_id above.
        users_cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        if "is_admin" not in users_cols:
            conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )


def backfill_account_ownership():
    """One-time migration step (see docs/DECISIONS.md 006): assign any
    account with no owner yet (`user_id IS NULL` — every account created
    before per-user isolation existed) to the earliest-created user. Must
    run after seed_legacy_user_if_none_exist() so there's at least one user
    to assign to; a no-op on installs where every account already has an
    owner. This preserves access to existing workspaces/data for whoever
    was already using this install, rather than orphaning them."""
    with get_db() as conn:
        orphaned = conn.execute("SELECT id FROM accounts WHERE user_id IS NULL").fetchall()
        if not orphaned:
            return
        first_user = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        if not first_user:
            return
        conn.execute("UPDATE accounts SET user_id = ? WHERE user_id IS NULL", (first_user["id"],))


def backfill_admin_flag():
    """One-time migration step (see docs/DECISIONS.md 010): if no user is
    marked admin yet, grant it to the single earliest-created user — the
    same "original owner" this codebase already treats specially in
    backfill_account_ownership() above. Deliberately does NOT grant it to
    every pre-existing user: the whole point of an admin role is to limit
    who can see every user's data and reassign account ownership, and we
    can't distinguish "the real owner" from "someone who happened to sign
    up early" for anyone past the very first row. A no-op once any admin
    exists, so it never overrides a deliberate later change (e.g. an admin
    promoting someone else, or demoting themselves)."""
    with get_db() as conn:
        if conn.execute("SELECT 1 FROM users WHERE is_admin = 1 LIMIT 1").fetchone():
            return
        first_user = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        if not first_user:
            return
        conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (first_user["id"],))


def create_workspace_account(name: str, user_id: int) -> int:
    """Create a new workspace account (see docs/DECISIONS.md 003) owned by
    `user_id`. Shared by the manual 'Add account' flow (app/routes/accounts.py)
    and the automatic default-account-on-signup flow (app/routes/auth_pages.py)
    so a brand-new user always has at least one workspace to land in."""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO accounts (name, created_at, user_id) VALUES (?, ?, ?)",
            (name, datetime.now(timezone.utc).isoformat(), user_id),
        )
        return cur.lastrowid


def record_upload(title, caption, platforms, privacy, tags, made_for_kids,
                   contains_synthetic_media, scheduled_time, results: dict,
                   account_id: int = 1) -> int:
    """For an immediate publish (no scheduling) — the platform APIs have
    already been called by the time this is written, so `results` is final."""
    oks = [r for r in results.values() if r.get("ok")]
    overall_status = "failed" if not oks else ("partial" if len(oks) < len(results) else "published")

    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO uploads
                (created_at, title, caption, platforms, privacy, tags,
                 made_for_kids, contains_synthetic_media, scheduled_time, status, results, video_path, account_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                title, caption, platforms, privacy, tags,
                int(made_for_kids), int(contains_synthetic_media),
                scheduled_time, overall_status, json.dumps(results), account_id,
            ),
        )
        return cur.lastrowid


def record_queued_upload(title, caption, platforms, privacy, tags, made_for_kids,
                          contains_synthetic_media, scheduled_time, video_path: str,
                          account_id: int = 1) -> int:
    """For a scheduled publish — we haven't called any platform API yet.
    The background scheduler does that later, at `scheduled_time`, using
    the file at `video_path`. `results` starts empty since nothing has
    happened yet."""
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO uploads
                (created_at, title, caption, platforms, privacy, tags,
                 made_for_kids, contains_synthetic_media, scheduled_time, status, results, video_path, account_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', '{}', ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                title, caption, platforms, privacy, tags,
                int(made_for_kids), int(contains_synthetic_media),
                scheduled_time, video_path, account_id,
            ),
        )
        return cur.lastrowid


def row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["made_for_kids"] = bool(d["made_for_kids"])
    d["contains_synthetic_media"] = bool(d["contains_synthetic_media"])
    d["results"] = json.loads(d["results"])
    return d
