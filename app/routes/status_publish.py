"""
/api/status and /api/publish — the two routes New Upload and the platform
connection cards depend on directly.
"""

import asyncio
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
from app.credentials import get_account_or_404, get_facebook_credentials, get_youtube_credentials
from app.db import create_upload_preset, prune_upload_history, record_queued_upload, record_upload
from app.publish_jobs import create_job, finish_job, get_job, is_cancel_requested, request_cancel, set_step_status
from app.uploaders import _upload_to_facebook, _upload_to_instagram, _upload_to_youtube

router = APIRouter()

# asyncio.create_task() only holds a *weak* reference to the task it
# returns — if nothing else references it, the task can be garbage
# collected mid-execution before it completes. Keeping every in-flight
# publish job's task in this set (and letting it remove itself once done)
# is the standard fix; see the "Important" note in the asyncio docs for
# create_task().
_background_tasks: set = set()


# ---------- Status ----------

@router.get("/api/status")
def status(account_id: int = 1, user: dict = Depends(require_login)):
    get_account_or_404(account_id, user["id"])
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
    user: dict = Depends(require_login),
):
    get_account_or_404(account_id, user["id"])
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

    # ---- Auto-save this submission to History (see docs/DECISIONS.md 013
    # and app/routes/upload_presets.py) — every form actually used to
    # attempt a publish, regardless of outcome, so it can be reviewed or
    # reused later without a user having to remember to save it themselves.
    create_upload_preset(
        account_id=account_id,
        kind="history",
        name=None,
        title=title,
        caption=caption,
        platforms=",".join(selected),
        privacy=privacy,
        tags=tags,
        made_for_kids=made_for_kids,
        contains_synthetic_media=contains_synthetic_media,
    )
    prune_upload_history(account_id)

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

    # ---- Immediate publish: run as a background job, return immediately.
    # The Upload page opens a progress panel and polls
    # GET /api/publish/jobs/{job_id} for live per-platform status — see
    # app/publish_jobs.py for why this is in-memory, and for cancel's
    # cooperative (not forceful) semantics. ----
    suffix = Path(video.filename).suffix or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=UPLOAD_DIR) as tmp:
        shutil.copyfileobj(video.file, tmp)
        tmp_path = Path(tmp.name)

    job_id = create_job(user["id"], account_id, selected)
    base_url = str(request.base_url)

    task = asyncio.create_task(_run_publish_job(
        job_id=job_id,
        tmp_path=tmp_path,
        title=title,
        caption=caption,
        selected=selected,
        privacy=privacy,
        tag_list=tag_list,
        made_for_kids=made_for_kids,
        contains_synthetic_media=contains_synthetic_media,
        account_id=account_id,
        base_url=base_url,
        tags_raw=tags,
    ))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return JSONResponse({"job_id": job_id})


async def _run_publish_job(
    *, job_id, tmp_path, title, caption, selected, privacy, tag_list,
    made_for_kids, contains_synthetic_media, account_id, base_url, tags_raw,
):
    results = {}
    fb_creds = get_facebook_credentials(account_id)

    try:
        for platform in selected:
            if is_cancel_requested(job_id):
                set_step_status(job_id, platform, "cancelled")
                results[platform] = {"ok": False, "error": "Cancelled before this step started."}
                continue

            set_step_status(job_id, platform, "active")
            try:
                if platform == "youtube":
                    # The googleapiclient/requests calls inside these are
                    # blocking I/O — run in a thread so they don't stall
                    # the event loop (which is what lets the frontend's
                    # polling requests, for THIS job or anyone else's on
                    # this server, actually get served while an upload is
                    # in flight).
                    result = await asyncio.to_thread(
                        _upload_to_youtube, tmp_path, title, caption,
                        privacy=privacy, tags=tag_list,
                        made_for_kids=made_for_kids,
                        contains_synthetic_media=contains_synthetic_media,
                        account_id=account_id,
                    )
                elif platform == "facebook":
                    if not fb_creds:
                        result = {
                            "ok": False,
                            "error": "Facebook is not connected. Go to Platforms to add your Page credentials.",
                        }
                    else:
                        result = await asyncio.to_thread(_upload_to_facebook, tmp_path, title, caption, fb_creds)
                elif platform == "instagram":
                    if not fb_creds or not fb_creds.get("instagram_business_account_id"):
                        result = {
                            "ok": False,
                            "error": "Instagram isn't linked. Connect Facebook with an Instagram Business account attached (see Platforms).",
                        }
                    else:
                        public_url = base_url + f"media/{tmp_path.name}"
                        result = await asyncio.to_thread(
                            _upload_to_instagram, public_url, caption, fb_creds,
                            local_file_path=tmp_path,
                            build_media_url=lambda name: base_url + f"media/{name}",
                        )
                else:
                    result = {"ok": False, "error": f"{platform} isn't wired up yet — see README.md for setup steps."}
            except Exception as e:
                result = {"ok": False, "error": f"Unexpected error: {e}"}

            results[platform] = result
            set_step_status(job_id, platform, "done" if result.get("ok") else "failed", error=result.get("error"))
    finally:
        tmp_path.unlink(missing_ok=True)

    record_upload(
        title=title,
        caption=caption,
        platforms=",".join(selected),
        privacy=privacy,
        tags=tags_raw,
        made_for_kids=made_for_kids,
        contains_synthetic_media=contains_synthetic_media,
        scheduled_time=None,
        results=results,
        account_id=account_id,
    )
    finish_job(job_id, results)


@router.get("/api/publish/jobs/{job_id}")
def get_publish_job(job_id: str, user: dict = Depends(require_login)):
    job = get_job(job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {
        "steps": job["steps"],
        "finished": job["finished"],
        "cancel_requested": job["cancel_requested"],
        "results": job["results"],
    }


@router.post("/api/publish/jobs/{job_id}/cancel")
def cancel_publish_job(job_id: str, user: dict = Depends(require_login)):
    if not request_cancel(job_id, user["id"]):
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"ok": True}
