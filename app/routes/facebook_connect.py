"""
Facebook/Instagram connect and disconnect. No OAuth flow — you already
have a Page Access Token, so this just validates it against the Graph API
and stores it. See README for how to generate one.
"""

import json

import requests
from fastapi import APIRouter, Depends, Form, HTTPException

from app.auth import require_login
from app.config import GRAPH_BASE
from app.credentials import facebook_creds_path, get_account_or_404

router = APIRouter()


# ---------- Facebook / Instagram connect / disconnect ----------
# No OAuth flow here — you already have a Page Access Token, so we just
# validate it against the Graph API and store it. See README for how to
# generate one if you ever need a fresh one.

@router.post("/api/connect/facebook")
def connect_facebook(
    app_id: str = Form(...),
    app_secret: str = Form(...),
    page_id: str = Form(...),
    page_access_token: str = Form(...),
    account_id: int = 1,
    user: str = Depends(require_login),
):
    get_account_or_404(account_id)
    try:
        resp = requests.get(
            f"{GRAPH_BASE}/{page_id}",
            params={
                "fields": "name,instagram_business_account{id,username}",
                "access_token": page_access_token,
            },
            timeout=15,
        )
        data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not reach Facebook: {e}")

    if not resp.ok or "error" in data:
        err = data.get("error", {}).get("message", "Facebook rejected these credentials.")
        raise HTTPException(status_code=400, detail=err)

    ig = data.get("instagram_business_account")
    creds = {
        "app_id": app_id,
        "app_secret": app_secret,
        "page_id": page_id,
        "page_access_token": page_access_token,
        "page_name": data.get("name"),
        "instagram_business_account_id": ig.get("id") if ig else None,
        "instagram_username": ig.get("username") if ig else None,
    }
    with open(facebook_creds_path(account_id), "w") as f:
        json.dump(creds, f, indent=2)

    return {
        "ok": True,
        "page_name": creds["page_name"],
        "instagram_linked": bool(ig),
        "instagram_username": creds["instagram_username"],
    }


@router.post("/api/disconnect/facebook")
def disconnect_facebook(account_id: int = 1, user: str = Depends(require_login)):
    path = facebook_creds_path(account_id)
    if path.exists():
        path.unlink()
    return {"ok": True}
