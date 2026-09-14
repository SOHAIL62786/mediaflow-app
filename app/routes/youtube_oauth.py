"""
YouTube's OAuth connect/callback/disconnect flow.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow

from app.auth import require_login
from app.config import YOUTUBE_SCOPES
from app.credentials import client_secret_path, get_account_or_404, token_path

router = APIRouter()


# ---------- YouTube connect / disconnect (OAuth) ----------

_pending_oauth_flows: dict = {}  # state -> (Flow, account_id), cleared once the callback completes


@router.get("/api/connect/youtube")
def connect_youtube(request: Request, account_id: int = 1, user: dict = Depends(require_login)):
    get_account_or_404(account_id, user["id"])
    secret_path = client_secret_path(account_id)
    if not secret_path.exists():
        raise HTTPException(
            status_code=400,
            detail="credentials/client_secret.json is missing — add your Google OAuth client first "
                   "(shared across accounts, or drop one in this account's own credentials folder).",
        )
    redirect_uri = str(request.base_url) + "api/oauth2callback/youtube"
    flow = Flow.from_client_secrets_file(
        str(secret_path), scopes=YOUTUBE_SCOPES, redirect_uri=redirect_uri
    )
    auth_url, state = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    _pending_oauth_flows[state] = (flow, account_id)
    return RedirectResponse(auth_url)


@router.get("/api/oauth2callback/youtube")
def oauth2callback_youtube(request: Request):
    # No @Depends(require_login) here — this is a browser redirect coming
    # back from Google, not an API call the frontend makes directly. The
    # session cookie would actually be attached fine (it's a same-origin
    # navigation), but this endpoint intentionally verifies the `state`
    # value instead, which only exists because /api/connect/youtube (which
    # IS login-gated) issued it moments earlier — one less place trusting
    # a cookie is enough. The account_id it was issued for travels along
    # with the flow object in _pending_oauth_flows so the token lands in the
    # right account's credentials folder, not always Account 1.
    state = request.query_params.get("state")
    pending = _pending_oauth_flows.pop(state, None)
    if pending is None:
        raise HTTPException(status_code=400, detail="OAuth session expired or invalid — try connecting again.")
    flow, account_id = pending

    flow.fetch_token(authorization_response=str(request.url))
    creds = flow.credentials

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }
    if creds.expiry:
        token_data["expiry"] = creds.expiry.isoformat() + "Z"
    with open(token_path(account_id), "w") as f:
        json.dump(token_data, f, indent=2)

    return RedirectResponse(f"/?page=platforms&account_id={account_id}")


@router.post("/api/disconnect/youtube")
def disconnect_youtube(account_id: int = 1, user: dict = Depends(require_login)):
    # Also fixes a pre-existing gap (see TODO.md): this previously never
    # validated the account existed/was yours, silently no-op'ing on a bad
    # account_id instead of 404ing.
    get_account_or_404(account_id, user["id"])
    path = token_path(account_id)
    if path.exists():
        path.unlink()
    return {"ok": True}
