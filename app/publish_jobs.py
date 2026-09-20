"""
In-memory registry for immediate-publish jobs, backing the live progress
panel (Upload page: click Publish -> side panel with a step per platform,
polled by the frontend) and cooperative cancel.

Deliberately in-memory, not a DB table: this is ephemeral, per-request
progress state, not a record anyone needs after the fact — the final
outcome still gets written to the `uploads` table via record_upload(),
same as before this feature existed. In-memory is fine because this app
runs as a single process (one uvicorn worker, see docs/DECISIONS.md) —
job state living only in that process's memory is the same assumption
the rest of the app already makes.

Cancel is cooperative, not forceful: cancelling a job stops it from
*starting* the next not-yet-begun platform step. It cannot interrupt a
platform upload call already in flight — Facebook/Instagram's Graph API
publish calls are effectively all-or-nothing once started, and even for
YouTube's resumable upload, actually aborting a live chunk transfer is a
bigger change than this first version attempts. See TODO.md.
"""

import threading
import time
import uuid

_jobs = {}
_lock = threading.Lock()

_MAX_JOB_AGE_SECONDS = 3600  # prune finished jobs older than this on each create


def create_job(user_id: int, account_id: int, platforms: list[str]) -> str:
    job_id = uuid.uuid4().hex
    steps = [
        {"key": p, "label": f"Publishing to {p.capitalize()}", "status": "pending", "error": None}
        for p in platforms
    ]
    now = time.time()
    with _lock:
        _jobs[job_id] = {
            "user_id": user_id,
            "account_id": account_id,
            "steps": steps,
            "cancel_requested": False,
            "finished": False,
            "results": None,
            "created_at": now,
        }
        # Prune old finished jobs so this dict can't grow unbounded over a
        # long-running process — cheap enough to do on every create.
        stale = [
            jid for jid, j in _jobs.items()
            if j["finished"] and now - j["created_at"] > _MAX_JOB_AGE_SECONDS
        ]
        for jid in stale:
            del _jobs[jid]
    return job_id


def get_job(job_id: str, user_id: int):
    """Returns the job dict, or None if it doesn't exist or isn't this
    user's — same not-found-vs-not-yours ambiguity as get_account_or_404,
    deliberately, so a guessed job_id can't confirm another user's job
    exists."""
    with _lock:
        job = _jobs.get(job_id)
    if not job or job["user_id"] != user_id:
        return None
    return job


def set_step_status(job_id: str, key: str, status: str, error: str | None = None):
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        for s in job["steps"]:
            if s["key"] == key:
                s["status"] = status
                s["error"] = error
                break


def is_cancel_requested(job_id: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        return bool(job and job["cancel_requested"])


def request_cancel(job_id: str, user_id: int) -> bool:
    job = get_job(job_id, user_id)
    if not job:
        return False
    with _lock:
        _jobs[job_id]["cancel_requested"] = True
    return True


def finish_job(job_id: str, results: dict):
    with _lock:
        job = _jobs.get(job_id)
        if job:
            job["finished"] = True
            job["results"] = results
