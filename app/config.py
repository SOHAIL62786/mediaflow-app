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

# ---------- Optional signup invite-code gate ----------
# Sign-up is fully open by default (project owner's explicit choice — see
# docs/DECISIONS.md). Setting this env var requires anyone signing up to
# enter a matching code; leaving it unset (the default) keeps signup open
# exactly as before. See docs/DECISIONS.md 009.
SIGNUP_CODE = os.environ.get("SIGNUP_CODE", "")

# ---------- "Sign in with Google" (app-level login/signup) ----------
# This is a *different* Google OAuth client than credentials/client_secret.json
# (or a per-account credentials/accounts/<id>/client_secret.json) above —
# those are each workspace-account's own connection to pull that account's
# YouTube data, uploaded via the Accounts/Platforms UI. This one is how a
# *person* gets a MediaFlow login in the first place, so it's a single
# app-wide client configured here via env vars, same pattern as
# APP_USERNAME/APP_PASSWORD/SIGNUP_CODE above. See docs/DECISIONS.md 016.
# Leaving these unset simply hides the "Continue with Google" button —
# username/password signup and login are unaffected either way.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
# Deliberately just enough to identify the person (name/email) — no
# YouTube/Drive/etc. access requested here. These are Google's "non-
# sensitive" scope tier, which matters for whether the OAuth consent
# screen needs Google's manual verification to leave "Testing" status;
# see docs/DECISIONS.md 016 and README.md for what that means in practice.
GOOGLE_LOGIN_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# ---------- Public base URL (needed by the background scheduler) ----------
# Interactive requests can build a public URL from the incoming request
# itself (request.base_url) — but the background scheduler that publishes
# queued videos at their scheduled time runs with no HTTP request in
# progress, so for Instagram (which needs a public URL to fetch the video
# from) it needs this configured explicitly. Only required if you schedule
# Instagram posts; everything else works without it.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
