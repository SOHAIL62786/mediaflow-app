"""
Shared constants and environment-derived configuration.

Nothing in here talks to the database or makes network calls — just paths
and settings every other module needs, so they don't each redefine (or
disagree on) where things live.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
CRED_DIR = BASE_DIR / "credentials"
UPLOAD_DIR = BASE_DIR / "uploads"
STATIC_DIR = BASE_DIR / "static"
DB_PATH = BASE_DIR / "mediaflow.db"

UPLOAD_DIR.mkdir(exist_ok=True)

# Legacy single-tenant credential paths (pre-multi-account). Used only to
# migrate an existing install's credentials into Account 1 on first boot.
LEGACY_TOKEN_PATH = CRED_DIR / "token.json"
LEGACY_CLIENT_SECRET_PATH = CRED_DIR / "client_secret.json"
LEGACY_FACEBOOK_CREDS_PATH = CRED_DIR / "facebook.json"

ACCOUNTS_CRED_DIR = CRED_DIR / "accounts"

GRAPH_API_VERSION = "v23.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# Scopes requested on (re)connect. Includes upload (needed today) plus
# read-only + analytics scopes so a future Analytics page doesn't need
# another re-auth round-trip.
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

# ---------- Legacy single-shared-login seed values ----------
# These no longer gate access directly (see app/auth.py — login is now real
# per-user accounts with hashed passwords and session cookies). They're only
# used once, if no `users` row exists yet, to seed a first account so an
# existing install isn't locked out after upgrading. See docs/DECISIONS.md 004.
APP_USERNAME = os.environ.get("APP_USERNAME", "")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")

# ---------- Public base URL (needed by the background scheduler) ----------
# Interactive requests can build a public URL from the incoming request
# itself (request.base_url) — but the background scheduler that publishes
# queued videos at their scheduled time runs with no HTTP request in
# progress, so for Instagram (which needs a public URL to fetch the video
# from) it needs this configured explicitly. Only required if you schedule
# Instagram posts; everything else works without it.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
