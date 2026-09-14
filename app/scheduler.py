"""
Local scheduler (replaces native platform scheduling).

Videos scheduled "for later" are held on disk with a DB row of
status='scheduled' and a video_path. This background loop polls for rows
whose time has arrived and actually performs the upload/publish at that
moment — the same call as a manual "Publish Now" — rather than relying on
YouTube's publishAt or Facebook's scheduled_publish_time. Instagram, which
has no native scheduling at all, works identically to the other two here.
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import PUBLIC_BASE_URL
from app.credentials import get_facebook_credentials
from app.db import get_db
from app.uploaders import _upload_to_facebook, _upload_to_instagram, _upload_to_youtube


# ---------- Local scheduler (replaces native platform scheduling) ----------
# Videos scheduled "for later" are held on disk with a DB row of
# status='scheduled' and a video_path. This background loop polls for rows
# whose time has arrived and actually performs the upload/publish at that
# moment — the same call as a manual "Publish Now" — rather than relying on
# YouTube's publishAt or Facebook's scheduled_publish_time. Instagram, which
# has no native scheduling at all, works identically to the other two here.

SCHEDULER_POLL_SECONDS = 30


def _execute_scheduled_upload(row: dict):
    """Runs the actual platform publish(es) for one due row, then updates
    its DB record and deletes the held file. Safe to call from a worker
    thread — it does its own DB connection and doesn't touch any live
    HTTP request state."""
    video_path = Path(row["video_path"]) if row["video_path"] else None
    platforms = [p.strip() for p in row["platforms"].split(",") if p.strip()]
    tag_list = [t.strip() for t in (row["tags"] or "").split(",") if t.strip()]
    account_id = row["account_id"] if "account_id" in row.keys() else 1
    fb_creds = get_facebook_credentials(account_id)

    results = {}
    if not video_path or not video_path.exists():
        for p in platforms:
            results[p] = {
                "ok": False,
                "error": "The queued video file was missing when it was due to publish "
                         "(it may have been cleaned up, or the disk ran out of space).",
            }
    else:
        for platform in platforms:
            if platform == "youtube":
                results["youtube"] = _upload_to_youtube(
                    video_path, row["title"], row["caption"],
                    privacy=row["privacy"], tags=tag_list,
                    made_for_kids=bool(row["made_for_kids"]),
                    contains_synthetic_media=bool(row["contains_synthetic_media"]),
                    account_id=account_id,
                )
            elif platform == "facebook":
                if not fb_creds:
                    results["facebook"] = {"ok": False, "error": "Facebook is not connected."}
                else:
                    results["facebook"] = _upload_to_facebook(video_path, row["title"], row["caption"], fb_creds)
            elif platform == "instagram":
                if not fb_creds or not fb_creds.get("instagram_business_account_id"):
                    results["instagram"] = {"ok": False, "error": "Instagram isn't linked to a connected Facebook Page."}
                elif not PUBLIC_BASE_URL:
                    results["instagram"] = {
                        "ok": False,
                        "error": "Scheduled Instagram posts need PUBLIC_BASE_URL set in your environment "
                                 "(no live request to build the URL from in the background) — see README.",
                    }
                else:
                    public_url = f"{PUBLIC_BASE_URL}/media/{video_path.name}"
                    results["instagram"] = _upload_to_instagram(public_url, row["caption"], fb_creds)
            else:
                results[platform] = {"ok": False, "error": f"{platform} isn't wired up yet."}

    oks = [r for r in results.values() if r.get("ok")]
    new_status = "failed" if not oks else ("partial" if len(oks) < len(results) else "published")

    with get_db() as conn:
        conn.execute(
            "UPDATE uploads SET status = ?, results = ?, video_path = NULL WHERE id = ?",
            (new_status, json.dumps(results), row["id"]),
        )

    if video_path and video_path.exists():
        video_path.unlink(missing_ok=True)


def _process_due_scheduled_uploads():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM uploads WHERE status = 'scheduled' AND video_path IS NOT NULL AND scheduled_time <= ?",
            (datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),),
        ).fetchall()
        due = [dict(r) for r in rows]

    for row in due:
        try:
            _execute_scheduled_upload(row)
        except Exception as e:
            with get_db() as conn:
                conn.execute(
                    "UPDATE uploads SET status = 'failed', results = ? WHERE id = ?",
                    (json.dumps({p: {"ok": False, "error": f"Scheduler error: {e}"}
                                 for p in row["platforms"].split(",")}), row["id"]),
                )


async def _scheduler_loop():
    while True:
        try:
            await asyncio.get_event_loop().run_in_executor(None, _process_due_scheduled_uploads)
        except Exception as e:
            print(f"[scheduler] unexpected error: {e}")
        await asyncio.sleep(SCHEDULER_POLL_SECONDS)


