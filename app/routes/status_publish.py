"""
/api/status and /api/publish — the two routes New Upload and the platform
connection cards depend on directly.
"""

import secrets
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.auth import require_login
from app.config import GRAPH_BASE, UPLOAD_DIR
from app.credentials import get_facebook_credentials, get_youtube_credentials
from app.db import record_queued_upload, record_upload
from app.uploaders import _upload_to_facebook, _upload_to_instagram, _upload_to_youtube

router = APIRouter()


# ---------- Status ----------

@router.get("/api/status")
def status(account_id: int = 1, user: str = Depends(require_login)):
    platforms = {
        "youtube": {"connected": False, "channel": None},
        "facebook": {"connected": False, "channel": None},
        "instagram": {"connected": False, "channel": None},
        "tiktok": {"connected": False, "channel": None},
    }

    try:
        creds = get_youtube_credentials(account_id)
        if creds:
            yt = build("youtube", "v3", credentials=creds)
            try:
                resp = yt.channels().list(part="snippet,statistics", mine=True).execute()
                items = resp.get("items", [])
                if items:
                    stats = items[0]["statistics"]
                    platforms["youtube"] = {
                        "connected": True,
                        "channel": items[0]["snippet"]["title"],
                    }
                    if not stats.get("hiddenSubscriberCount"):
                        platforms["youtube"]["subscribers"] = int(stats.get("subscriberCount", 0))
                else:
                    platforms["youtube"] = {"connected": True, "channel": "YouTube (upload-only token)"}
            except HttpError as e:
                # Your token only has the youtube.upload scope, which is enough
                # to publish videos but NOT enough to read channel info via
                # channels.list (that needs a broader read scope). Treat this
                # specific case as "connected" since uploads will still work —
                # we just can't show the channel name.
                if e.resp.status == 403 and "insufficientPermissions" in str(e):
                    platforms["youtube"] = {"connected": True, "channel": "YouTube (upload-only token)"}
                else:
                    raise
    except Exception as e:
        platforms["youtube"] = {"connected": False, "channel": None, "error": str(e)}

    fb_creds = get_facebook_credentials(account_id)
    if fb_creds:
        try:
            resp = requests.get(
                f"{GRAPH_BASE}/{fb_creds['page_id']}",
                params={
                    "fields": "name,followers_count,instagram_business_account{id,username,followers_count}",
                    "access_token": fb_creds["page_access_token"],
                },
                timeout=10,
            )
            data = resp.json()
            if not resp.ok or "error" in data:
                # Some Page tokens don't have permission for follower counts.
                # Fall back to the original minimal fields so connection
                # status detection still works even without the counts.
                resp = requests.get(
                    f"{GRAPH_BASE}/{fb_creds['page_id']}",
                    params={
                        "fields": "name,instagram_business_account{id,username}",
                        "access_token": fb_creds["page_access_token"],
                    },
                    timeout=10,
                )
                data = resp.json()
            if resp.ok and "error" not in data:
                platforms["facebook"] = {"connected": True, "channel": data.get("name")}
                if data.get("followers_count") is not None:
                    platforms["facebook"]["followers"] = data.get("followers_count")
                ig = data.get("instagram_business_account")
                if ig:
                    platforms["instagram"] = {"connected": True, "channel": ig.get("username")}
                    if ig.get("followers_count") is not None:
                        platforms["instagram"]["followers"] = ig.get("followers_count")
                else:
                    platforms["instagram"] = {
                        "connected": False,
                        "channel": None,
                        "error": "No Instagram Business account linked to this Page.",
                    }
            else:
                err = data.get("error", {}).get("message", "Facebook rejected this token.")
                platforms["facebook"] = {"connected": False, "channel": None, "error": err}
        except Exception as e:
            platforms["facebook"] = {"connected": False, "channel": None, "error": str(e)}

    return platforms


# ---------- Publish ----------

@router.post("/api/publish")
async def publish(
    request: Request,
    video: UploadFile = File(...),
    title: str = Form(...),
    caption: str = Form(""),
    platforms: str = Form(...),  # comma-separated, e.g. "youtube,facebook"
    privacy: str = Form("private"),          # "private" | "unlisted" | "public"
    tags: str = Form(""),                    # comma-separated, e.g. "travel,vlog,japan"
    made_for_kids: bool = Form(False),
    contains_synthetic_media: bool = Form(False),  # YouTube's AI/altered-content disclosure
    scheduled_time: Optional[str] = Form(None),  # RFC3339 UTC timestamp, e.g. "2026-09-10T14:30:00.000Z"
    account_id: int = 1,
    user: str = Depends(require_login),
):
    selected = [p.strip().lower() for p in platforms.split(",") if p.strip()]
    if not selected:
        raise HTTPException(status_code=400, detail="No platforms selected.")
    if privacy not in ("private", "unlisted", "public"):
        raise HTTPException(status_code=400, detail="privacy must be private, unlisted, or public.")

    publish_at = None
    if scheduled_time:
        try:
            parsed = datetime.fromisoformat(scheduled_time.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="scheduled_time is not a valid date/time.")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if parsed <= datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="scheduled_time must be in the future.")
        publish_at = parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    # ---- Scheduled: queue locally, publish nothing yet ----
    # We deliberately don't use each platform's own native scheduling
    # (YouTube's publishAt, Facebook's scheduled_publish_time) — YouTube in
    # particular appears to distribute scheduled Shorts more slowly than
    # ones made public immediately, and Instagram has no native scheduling
    # at all. Instead we hold the file ourselves and run the exact same
    # "publish now" call for every platform at the scheduled moment, via a
    # background job that polls for due uploads (see _scheduler_loop).
    # This also makes scheduling behave identically across every platform,
    # regardless of what each one natively supports.
    if publish_at:
        suffix = Path(video.filename).suffix or ".mp4"
        dest_name = f"scheduled_{secrets.token_hex(8)}{suffix}"
        dest_path = UPLOAD_DIR / dest_name
        with open(dest_path, "wb") as out:
            shutil.copyfileobj(video.file, out)

        record_queued_upload(
            title=title,
            caption=caption,
            platforms=",".join(selected),
            privacy=privacy,
            tags=tags,
            made_for_kids=made_for_kids,
            contains_synthetic_media=contains_synthetic_media,
            scheduled_time=publish_at,
            video_path=str(dest_path),
            account_id=account_id,
        )

        return JSONResponse({
            p: {
                "ok": True,
                "queued": True,
                "scheduled_for": publish_at,
                "note": f"Queued locally — MediaFlow will publish this to {p} at the scheduled time "
                        f"(not using {p}'s own scheduler).",
            }
            for p in selected
        })

    # ---- Immediate publish ----
    suffix = Path(video.filename).suffix or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=UPLOAD_DIR) as tmp:
        shutil.copyfileobj(video.file, tmp)
        tmp_path = Path(tmp.name)

    results = {}
    fb_creds = get_facebook_credentials(account_id)

    try:
        for platform in selected:
            if platform == "youtube":
                results["youtube"] = _upload_to_youtube(
                    tmp_path, title, caption,
                    privacy=privacy, tags=tag_list,
                    made_for_kids=made_for_kids,
                    contains_synthetic_media=contains_synthetic_media,
                    account_id=account_id,
                )
            elif platform == "facebook":
                if not fb_creds:
                    results["facebook"] = {
                        "ok": False,
                        "error": "Facebook is not connected. Go to Platforms to add your Page credentials.",
                    }
                else:
                    results["facebook"] = _upload_to_facebook(tmp_path, title, caption, fb_creds)
            elif platform == "instagram":
                if not fb_creds or not fb_creds.get("instagram_business_account_id"):
                    results["instagram"] = {
                        "ok": False,
                        "error": "Instagram isn't linked. Connect Facebook with an Instagram Business account attached (see Platforms).",
                    }
                else:
                    # Instagram's Content Publishing API requires a public URL
                    # to fetch the video from — it can't accept a direct file
                    # upload. We serve the temp file at a short-lived public
                    # URL (random filename) and delete it right after.
                    public_url = str(request.base_url) + f"media/{tmp_path.name}"
                    results["instagram"] = _upload_to_instagram(public_url, caption, fb_creds)
            else:
                results[platform] = {
                    "ok": False,
                    "error": f"{platform} isn't wired up yet — see README.md for setup steps.",
                }
    finally:
        tmp_path.unlink(missing_ok=True)

    record_upload(
        title=title,
        caption=caption,
        platforms=",".join(selected),
        privacy=privacy,
        tags=tags,
        made_for_kids=made_for_kids,
        contains_synthetic_media=contains_synthetic_media,
        scheduled_time=None,
        results=results,
        account_id=account_id,
    )

    return JSONResponse(results)
