"""
The actual "call the platform's API and upload this file" functions.

Used both by an immediate /api/publish call and by the background
scheduler (app/scheduler.py) once a queued post comes due — same function
either way, so scheduling behaves identically to publishing "now".
"""

import secrets
import shutil
import subprocess
import time as time_module
from pathlib import Path
from typing import Callable, Optional

import requests
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from app.config import GRAPH_BASE, UPLOAD_DIR
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


# Re-encoding is a last resort (slow, and re-compresses the video), so it's
# only ever attempted once, and only for the one failure mode it can
# actually fix — see _upload_to_instagram's docstring for why.
INSTAGRAM_REENCODE_TIMEOUT_SECONDS = 600  # generous cap so a big file can't hang a publish request forever


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _reencode_for_instagram(file_path: Path) -> Path:
    """Re-encodes into a conservative, known-Instagram-safe format: H.264
    Main profile (not whatever profile/GOP structure the source used —
    often the real culprit when a file already looks spec-compliant on
    paper), yuv420p, AAC audio, and the moov atom moved to the front.
    Written into UPLOAD_DIR (same place /media/{filename} serves from) so
    the caller can build a fetchable URL for it immediately. Raises
    RuntimeError on failure; caller is responsible for deleting the output
    file once it's done with it."""
    output_path = UPLOAD_DIR / f"ig_reencode_{secrets.token_hex(8)}.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(file_path),
        "-c:v", "libx264",
        "-profile:v", "main",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-movflags", "+faststart",
        str(output_path),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=INSTAGRAM_REENCODE_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired:
        output_path.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg re-encode timed out after {INSTAGRAM_REENCODE_TIMEOUT_SECONDS}s")
    if result.returncode != 0 or not output_path.exists():
        output_path.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg re-encode failed: {result.stderr[-800:]}")
    return output_path


def _attempt_instagram_publish(public_video_url: str, caption: str, fb_creds: dict) -> dict:
    """One end-to-end attempt: create a media container pointing at the
    given URL, poll until Instagram finishes downloading and processing it,
    then publish. Split out from _upload_to_instagram so the re-encode
    fallback can call this again with a second URL without duplicating the
    three-step dance."""
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
                params={"fields": "status_code,status", "access_token": token},
                timeout=30,
            )
            status_data = status_resp.json()
            code = status_data.get("status_code")
            if code == "FINISHED":
                break
            if code == "ERROR":
                # Graph API's "status" field has the actual reason (bad
                # aspect ratio, duration, codec, file size, etc.) —
                # "status_code" alone is just the enum. Surface both so a
                # failure is actually diagnosable instead of a dead end.
                # reencode_worth_trying: this specific failure mode (a video
                # Instagram accepted for download but rejected while
                # processing it) is exactly what re-encoding into a
                # conservative format can fix — unlike a create-time
                # rejection or a processing timeout, neither of which
                # re-encoding addresses.
                detail = status_data.get("status") or "no further detail returned by Instagram."
                return {
                    "ok": False,
                    "error": f"Instagram failed to process the video: {detail}",
                    "reencode_worth_trying": True,
                }
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


def _upload_to_instagram(
    public_video_url: str,
    caption: str,
    fb_creds: dict,
    local_file_path: Optional[Path] = None,
    build_media_url: Optional[Callable[[str], str]] = None,
) -> dict:
    """Instagram's Content Publishing API only accepts a fetchable URL, not a
    direct file upload — publishing is a 3-step dance handled by
    _attempt_instagram_publish: create a media container pointing at the
    URL, poll until Instagram finishes downloading and processing it, then
    publish the container.

    Fallback: if that attempt fails specifically because Instagram rejected
    the video during processing (status_code == "ERROR" — the file was
    fetched fine but didn't meet Instagram's Reels spec: aspect ratio,
    duration, codec, GOP structure, etc.), and the caller gave us the local
    file plus a way to build a public URL for a new one, re-encode into a
    conservative known-good format and retry exactly once. This mirrors a
    working local script that already validated the approach: raw upload
    first (fast, no quality loss), only re-encode (slow, lossy) when the
    raw file is actually rejected.

    Deliberately NOT retried this way: a create-time rejection (bad
    token/URL, not a video-format problem) or a 5-minute processing
    timeout (Instagram being slow, not the file being bad) — re-encoding
    doesn't fix either and would just double an already-long wait, risking
    the request outliving nginx's proxy_read_timeout.
    """
    result = _attempt_instagram_publish(public_video_url, caption, fb_creds)
    worth_retrying = result.pop("reencode_worth_trying", False)

    if result.get("ok") or not worth_retrying or not local_file_path or not build_media_url:
        return result

    if not _ffmpeg_available():
        result["error"] += " (re-encode fallback skipped: ffmpeg is not installed on the server)"
        return result

    try:
        reencoded_path = _reencode_for_instagram(Path(local_file_path))
    except Exception as e:
        result["error"] += f" (re-encode fallback also failed: {e})"
        return result

    try:
        reencoded_url = build_media_url(reencoded_path.name)
        retry_result = _attempt_instagram_publish(reencoded_url, caption, fb_creds)
        retry_result.pop("reencode_worth_trying", None)
        if retry_result.get("ok"):
            retry_result["note"] = (
                "Published after re-encoding — the original file didn't meet Instagram's Reels spec "
                "(check codec profile, GOP structure, or bitrate if this keeps happening)."
            )
        else:
            retry_result["error"] = f"{retry_result['error']} (also failed after re-encoding)"
        return retry_result
    finally:
        reencoded_path.unlink(missing_ok=True)

