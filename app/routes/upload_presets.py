"""
/api/upload-presets — drafts and templates for the Upload form.

Both are just a saved snapshot of the form's metadata fields (title,
caption, tags, platforms, privacy, made-for-kids/synthetic-media
checkboxes) — no video file, no schedule time. See docs/DECISIONS.md 013
for the full reasoning, in particular why a video file is deliberately
NOT part of either: a draft or template is metadata you come back to
attach a (possibly different, possibly not-yet-chosen) file to, not a
half-finished upload with a file already in flight.

'draft' (kind='draft'): unnamed, one-shot — resuming one on the frontend
deletes it via DELETE, same as consuming it.
'template' (kind='template'): user-named (see the "name" field), reused
indefinitely — applying one on the frontend does NOT delete it.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException

from app.auth import require_login
from app.credentials import get_account_or_404
from app.db import create_upload_preset, delete_upload_preset, list_upload_presets

router = APIRouter()

VALID_KINDS = {"draft", "template"}


@router.get("/api/upload-presets")
def list_presets(kind: str, account_id: int = 1, user: dict = Depends(require_login)):
    get_account_or_404(account_id, user["id"])
    if kind not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {sorted(VALID_KINDS)}")
    return list_upload_presets(account_id, kind)


@router.post("/api/upload-presets")
def create_preset(
    kind: str = Form(...),
    name: Optional[str] = Form(None),
    title: str = Form(""),
    caption: str = Form(""),
    platforms: str = Form(""),
    privacy: str = Form("private"),
    tags: str = Form(""),
    made_for_kids: bool = Form(False),
    contains_synthetic_media: bool = Form(False),
    account_id: int = 1,
    user: dict = Depends(require_login),
):
    get_account_or_404(account_id, user["id"])
    if kind not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {sorted(VALID_KINDS)}")

    clean_name = (name or "").strip()
    if kind == "template" and not clean_name:
        raise HTTPException(status_code=400, detail="Templates need a name.")
    if not title.strip() and not caption.strip():
        raise HTTPException(status_code=400, detail="Add a title or caption before saving.")

    new_id = create_upload_preset(
        account_id=account_id,
        kind=kind,
        name=clean_name or None,
        title=title,
        caption=caption,
        platforms=platforms,
        privacy=privacy,
        tags=tags,
        made_for_kids=made_for_kids,
        contains_synthetic_media=contains_synthetic_media,
    )
    return {"id": new_id}


@router.delete("/api/upload-presets/{preset_id}")
def delete_preset(preset_id: int, account_id: int = 1, user: dict = Depends(require_login)):
    get_account_or_404(account_id, user["id"])
    if not delete_upload_preset(preset_id, account_id):
        raise HTTPException(status_code=404, detail="Not found.")
    return {"ok": True}
