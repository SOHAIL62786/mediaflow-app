"""
"Sign in with Google" — app-level login/signup (see docs/DECISIONS.md 016).

Deliberately separate from app/routes/youtube_oauth.py, which connects one
*workspace account* (Decision 003) to its own YouTube data and is gated
behind require_login. This is unrelated to workspace accounts — it's how a
*person* gets a MediaFlow login in the first place, using one single
app-wide Google OAuth client (GOOGLE_CLIENT_ID/SECRET in app/config.py)
rather than a per-account credentials/accounts/<id>/client_secret.json
file, so it has to work before that person has a session at all.
"""

import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from google_auth_oauthlib.flow import Flow

from app.auth import (
    create_session,
    create_user_from_google,
    ensure_user_has_account,
    get_user_by_google_sub,
    set_session_cookie,
)
from app.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_LOGIN_SCOPES, SIGNUP_CODE

router = APIRouter()

# state -> (Flow, signup_code_the_user_typed_before_clicking). Same
# short-lived in-memory pending-flow pattern as youtube_oauth.py's
# _pending_oauth_flows — popped as soon as the callback consumes it, so a
# state value only ever works once.
_pending_google_flows: dict = {}


@router.get("/api/auth/google-config")
def api_google_config():
    # Public (no login) — same reasoning as /api/auth/signup-config: the
    # Sign In / Sign Up pages need this before anyone has a session, just
    # to decide whether to show the "Continue with Google" button at all.
    return {"enabled": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)}


def _client_config(redirect_uri: str) -> dict:
    # Flow.from_client_config() wants the same shape as a downloaded
    # client_secret.json, just built from env vars instead of a file —
    # there's no per-account file for this (see module docstring).
    return {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }


def _redirect_with_error(path: str, message: str) -> RedirectResponse:
    return RedirectResponse(f"{path}?{urlencode({'error': message})}")


@router.get("/api/auth/google/login")
def google_login(request: Request, signup_code: str = ""):
    # Public (no require_login) — this IS how someone logs in or signs up,
    # so unlike /api/connect/youtube it can't itself require a session.
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=503,
            detail="Sign in with Google isn't set up on this server yet "
                   "(GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET aren't configured).",
        )
    redirect_uri = str(request.base_url) + "api/auth/google/callback"
    flow = Flow.from_client_config(
        _client_config(redirect_uri), scopes=GOOGLE_LOGIN_SCOPES, redirect_uri=redirect_uri
    )
    # "online" (no refresh token) — this only ever needs to identify the
    # person once per sign-in, not keep long-term API access the way the
    # YouTube connect flow does. select_account (not "consent") so a
    # returning user isn't re-shown Google's permission screen every time.
    auth_url, state = flow.authorization_url(access_type="online", prompt="select_account")
    # The invite code (if any) travels with this *server-side* pending-flow
    # entry, never inside `state` itself or anywhere Google sees it —
    # `state` stays just an opaque per-attempt CSRF token, same as
    # youtube_oauth.py's.
    _pending_google_flows[state] = (flow, signup_code)
    return RedirectResponse(auth_url)


@router.get("/api/auth/google/callback")
def google_callback(request: Request):
    state = request.query_params.get("state")
    pending = _pending_google_flows.pop(state, None)
    if pending is None:
        return _redirect_with_error("/login", "Google sign-in session expired or invalid — try again.")
    flow, signup_code = pending

    if request.query_params.get("error"):
        # User hit Cancel/Deny on Google's own consent screen — not worth
        # surfacing as an error banner, just send them back quietly.
        return RedirectResponse("/login")

    try:
        flow.fetch_token(authorization_response=str(request.url))
        claims = google_id_token.verify_oauth2_token(
            flow.credentials.id_token, google_requests.Request(), GOOGLE_CLIENT_ID
        )
    except Exception:
        return _redirect_with_error("/login", "Google sign-in failed. Please try again.")

    if not claims.get("email_verified"):
        return _redirect_with_error("/login", "That Google account's email address isn't verified.")

    google_sub = claims["sub"]
    email = claims.get("email", "")
    name = claims.get("name", "")

    existing = get_user_by_google_sub(google_sub)
    if existing:
        user_id, username = existing["id"], existing["username"]
    else:
        # New person — the same invite-code gate that guards password
        # signup (docs/DECISIONS.md 009) applies here too; it only ever
        # gates *account creation*, so a returning user above never hits
        # this regardless of what's in `signup_code`.
        if SIGNUP_CODE and not secrets.compare_digest(signup_code or "", SIGNUP_CODE):
            return _redirect_with_error("/signup", "Invalid or missing invite code.")
        user_id, username = create_user_from_google(google_sub, email, name)

    ensure_user_has_account(user_id, username)
    token = create_session(user_id)
    resp = RedirectResponse("/")
    set_session_cookie(resp, request, token)
    return resp
