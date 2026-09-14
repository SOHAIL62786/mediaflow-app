"""
/api/library and /api/dashboard/summary — the Scheduled, Published, and
Dashboard pages read from these.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_login
from app.credentials import get_account_or_404, get_facebook_credentials, get_youtube_credentials
from app.db import get_db, row_to_dict
from app.scheduler import _process_due_scheduled_uploads

router = APIRouter()


# ---------- Library (Scheduled / Published pages) ----------

@router.get("/api/library")
def library(status: Optional[str] = None, account_id: int = 1, user: dict = Depends(require_login)):
    get_account_or_404(account_id, user["id"])
    valid = {"scheduled", "published", "failed", "partial"}
    if status and status not in valid:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(valid)}")

    # Catch up immediately on refresh/load rather than waiting for the next
    # background poll — useful right after scheduling something for "now
    # plus a minute" and checking back before the 30s loop has ticked.
    _process_due_scheduled_uploads()

    with get_db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM uploads WHERE status = ? AND account_id = ? ORDER BY id DESC", (status, account_id)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM uploads WHERE account_id = ? ORDER BY id DESC", (account_id,)
            ).fetchall()
        return [row_to_dict(r) for r in rows]


@router.get("/api/dashboard/summary")
def dashboard_summary(account_id: int = 1, user: dict = Depends(require_login)):
    get_account_or_404(account_id, user["id"])
    _process_due_scheduled_uploads()
    with get_db() as conn:
        counts = {"scheduled": 0, "published": 0, "failed": 0, "partial": 0}
        for r in conn.execute(
            "SELECT status, COUNT(*) as n FROM uploads WHERE account_id = ? GROUP BY status", (account_id,)
        ):
            counts[r["status"]] = r["n"]
        recent = [row_to_dict(r) for r in conn.execute(
            "SELECT * FROM uploads WHERE account_id = ? ORDER BY id DESC LIMIT 5", (account_id,)
        )]

    connected_count = 0
    try:
        if get_youtube_credentials(account_id):
            connected_count += 1
    except Exception:
        pass
    if get_facebook_credentials(account_id):
        connected_count += 1

    return {
        "scheduled_count": counts["scheduled"],
        "published_count": counts["published"],
        "failed_count": counts["failed"] + counts["partial"],
        "connected_accounts": connected_count,
        "recent": recent,
    }


