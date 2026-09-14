"""
The actual "call the platform's API and upload this file" functions.

Used both by an immediate /api/publish call and by the background
scheduler (app/scheduler.py) once a queued post comes due — same function
either way, so scheduling behaves identically to publishing "now".
"""

import time as time_module
from pathlib import Path
from typing import Optional

import requests
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from app.config import GRAPH_BASE
from app.credentials import get_youtube_client


def _upload_to_youtube(
    file_path: Path,
    title: str,
    description: str,
    privacy: str = "private",
    tags: Optional[list] = None,
    made_for_kids: bool = False,
    contains_synthetic_media: bool = False,
    account_id: int = 1,
) -> dict:
    """Always publishes immediately at the requested privacy level. Scheduling
    is handled entirely by our own local queue (see _scheduler_loop) rather
    than YouTube's native publishAt — this function is only ever called once
    it's actually time to go live."""
    try:
        youtube = get_youtube_client(account_id)

        status = {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": made_for_kids,
            "containsSyntheticMedia": contains_synthetic_media,
        }

        body = {
            "snippet": {
                "title": title[:100] or "Untitled",
                "description": description[:5000],
                "categoryId": "22",
                "tags": (tags or [])[:500],  # YouTube caps total tag length at 500 chars combined
            },
            "status": status,
        }

        media = MediaFileUpload(str(file_path), chunksize=-1, resumable=True, mimetype="video/*")

        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            status_chunk, response = request.next_chunk()

        video_id = response.get("id")
        return {
            "ok": True,
            "video_id": video_id,
            "url": f"https://youtube.com/watch?v={video_id}",
            "privacy": status["privacyStatus"],
        }
    except HttpError as e:
        return {"ok": False, "error": f"YouTube API error: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _upload_to_facebook(file_path: Path, title: str, description: str, fb_creds: dict) -> dict:
    """Always publishes immediately. Scheduling is handled entirely by our
    own local queue rather than Facebook's scheduled_publish_time — this
    function is only ever called once it's actually time to go live."""
    try:
        page_id = fb_creds["page_id"]
        token = fb_creds["page_access_token"]
        data = {"title": title, "description": description or title, "access_token": token}

        with open(file_path, "rb") as f:
            resp = requests.post(
                f"{GRAPH_BASE}/{page_id}/videos",
                data=data,
                files={"source": f},
                timeout=900,
            )
        result = resp.json()

        if resp.ok and "id" in result:
            video_id = result["id"]
            return {
                "ok": True,
                "video_id": video_id,
                "url": f"https://www.facebook.com/{page_id}/videos/{video_id}",
            }
        err = result.get("error", {}).get("message", str(result))
        return {"ok": False, "error": f"Facebook API error: {err}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _upload_to_instagram(public_video_url: str, caption: str, fb_creds: dict) -> dict:
    """Instagram's Content Publishing API only accepts a fetchable URL, not a
    direct file upload — publishing is a 3-step dance: create a media
    container pointing at the URL, poll until Instagram finishes downloading
    and processing it, then publish the container."""
    try:
        ig_user_id = fb_creds["instagram_business_account_id"]
        token = fb_creds["page_access_token"]

        create_resp = requests.post(
            f"{GRAPH_BASE}/{ig_user_id}/media",
            data={
                "media_type": "REELS",
                "video_url": public_video_url,
                "caption": caption,
                "access_token": token,
            },
            timeout=60,
        )
        create_data = create_resp.json()
        if not create_resp.ok or "id" not in create_data:
            err = create_data.get("error", {}).get("message", str(create_data))
            return {"ok": False, "error": f"Instagram API error: {err}"}
        container_id = create_data["id"]

        for _ in range(30):  # poll for up to ~5 minutes
            status_resp = requests.get(
                f"{GRAPH_BASE}/{container_id}",
                params={"fields": "status_code", "access_token": token},
                timeout=30,
            )
            status_data = status_resp.json()
            code = status_data.get("status_code")
            if code == "FINISHED":
                break
            if code == "ERROR":
                return {"ok": False, "error": "Instagram failed to process the video."}
            time_module.sleep(10)
        else:
            return {
                "ok": False,
                "error": "Instagram is still processing the video after 5 minutes — try again shortly.",
            }

        publish_resp = requests.post(
            f"{GRAPH_BASE}/{ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": token},
            timeout=60,
        )
        publish_data = publish_resp.json()
        if not publish_resp.ok or "id" not in publish_data:
            err = publish_data.get("error", {}).get("message", str(publish_data))
            return {"ok": False, "error": f"Instagram publish error: {err}"}
        media_id = publish_data["id"]

        permalink = None
        try:
            link_resp = requests.get(
                f"{GRAPH_BASE}/{media_id}",
                params={"fields": "permalink", "access_token": token},
                timeout=15,
            )
            permalink = link_resp.json().get("permalink")
        except Exception:
            pass

        return {"ok": True, "video_id": media_id, "url": permalink}
    except Exception as e:
        return {"ok": False, "error": str(e)}

