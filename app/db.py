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
                created_at TEXT NOT NULL
            )
            """
        )
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
                created_at TEXT NOT NULL
            )
            """
        )
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
