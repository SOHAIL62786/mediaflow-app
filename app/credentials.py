"""
Per-account (workspace) credential storage and platform auth helpers.

Each account gets its own folder under credentials/accounts/<id>/ holding
its YouTube token and Facebook Page credentials — see docs/DECISIONS.md 003
for why (multi-account/workspace support — unrelated to the multi-user
*login* system in app/auth.py, see docs/DECISIONS.md 004). client_secret.json
(the Google OAuth *app* client, not a per-user token) is shared across
accounts by default.
"""

import json
import shutil
from pathlib import Path
from typing import Optional

from fastapi import HTTPException
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.config import (
    ACCOUNTS_CRED_DIR,
    LEGACY_CLIENT_SECRET_PATH,
    LEGACY_FACEBOOK_CREDS_PATH,
    LEGACY_TOKEN_PATH,
)
from app.db import get_db


def account_cred_dir(account_id: int) -> Path:
    d = ACCOUNTS_CRED_DIR / str(account_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def token_path(account_id: int) -> Path:
    return account_cred_dir(account_id) / "token.json"


def client_secret_path(account_id: int) -> Path:
    """The Google OAuth *app* client (Client ID/secret for the whole Google
    Cloud project) is allowed to be shared across accounts so you don't have
    to re-upload it per account — but an account can also have its own if
    you want fully separate Google Cloud projects per account."""
    per_account = account_cred_dir(account_id) / "client_secret.json"
    if per_account.exists():
        return per_account
    return LEGACY_CLIENT_SECRET_PATH


def facebook_creds_path(account_id: int) -> Path:
    return account_cred_dir(account_id) / "facebook.json"


def migrate_legacy_credentials_to_account_1():
    """One-time migration: if this install has old single-tenant credential
    files (from before multi-account support) and Account 1 doesn't have its
    own copies yet, move them in. This is what keeps the *first* account
    working exactly as before after upgrading."""
    acc1_dir = account_cred_dir(1)
    for legacy_path, name in (
        (LEGACY_TOKEN_PATH, "token.json"),
        (LEGACY_FACEBOOK_CREDS_PATH, "facebook.json"),
    ):
        dest = acc1_dir / name
        if legacy_path.exists() and not dest.exists():
            shutil.copy2(legacy_path, dest)


# ---------- YouTube auth helpers ----------

def get_youtube_credentials(account_id: int = 1) -> Optional[Credentials]:
    """Load stored token for this account, refreshing it if it's expired.
    Persists any refresh back to that account's token.json so you don't have
    to log in again next run."""
    path = token_path(account_id)
    if not path.exists():
        return None

    with open(path, "r") as f:
        data = json.load(f)

    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes"),
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
        # persist the refreshed access token
        data["token"] = creds.token
        if creds.expiry:
            data["expiry"] = creds.expiry.isoformat() + "Z"
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    return creds


def get_youtube_client(account_id: int = 1):
    creds = get_youtube_credentials(account_id)
    if creds is None:
        raise HTTPException(status_code=401, detail="YouTube is not connected. See README to run the OAuth flow.")
    return build("youtube", "v3", credentials=creds)


# ---------- Facebook / Instagram auth helpers ----------
# Instagram publishing rides on the same Facebook Page token — there's no
# separate Instagram login. See README for how to get a Page ID + Page
# Access Token, and what Instagram Business account linking requires.

def get_facebook_credentials(account_id: int = 1) -> Optional[dict]:
    path = facebook_creds_path(account_id)
    if not path.exists():
        return None
    with open(path, "r") as f:
        return json.load(f)


def get_account_or_404(account_id: int, user_id: int) -> dict:
    """Look up a workspace account, scoped to its owner (see
    docs/DECISIONS.md 006 — per-user data isolation). Returns the same 404
    whether the account doesn't exist at all or belongs to someone else, so
    a logged-in user can't distinguish "no such account" from "not yours"
    by probing IDs."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, name, created_at, user_id FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
    if not row or row["user_id"] != user_id:
        raise HTTPException(status_code=404, detail=f"Account {account_id} does not exist.")
    return dict(row)
