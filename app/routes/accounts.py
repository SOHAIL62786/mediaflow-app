"""
/api/accounts — list/create/rename/delete workspace accounts (the
multi-account switcher). Each account is owned by exactly one user — see
docs/DECISIONS.md 006 (per-user data isolation).
"""

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException

from app.auth import require_login
from app.credentials import account_cred_dir, get_account_or_404
from app.db import create_workspace_account, get_db

router = APIRouter()


# ---------- Accounts (multi-account switcher) ----------
# Each "account" is a fully independent set of platform connections,
# scheduled/published posts, and analytics — a workspace you switch
# between after logging in. As of docs/DECISIONS.md 006, each account is
# owned by exactly one logged-in user: a user can only see, switch to, or
# modify their own accounts, not anyone else's.

@router.get("/api/accounts")
def list_accounts(user: dict = Depends(require_login)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, created_at FROM accounts WHERE user_id = ? ORDER BY id", (user["id"],)
        ).fetchall()
        return [dict(r) for r in rows]


@router.post("/api/accounts")
def create_account(name: str = Form(...), user: dict = Depends(require_login)):
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Account name is required.")
    new_id = create_workspace_account(clean_name, user["id"])
    # Give the new account its own empty credentials directory right away so
    # the Platforms page has somewhere to write to as soon as it connects a
    # platform — doesn't affect any other account's files.
    account_cred_dir(new_id)
    return {"id": new_id, "name": clean_name}


@router.patch("/api/accounts/{account_id}")
def rename_account(account_id: int, name: str = Form(...), user: dict = Depends(require_login)):
    get_account_or_404(account_id, user["id"])
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Account name is required.")
    with get_db() as conn:
        conn.execute("UPDATE accounts SET name = ? WHERE id = ?", (clean_name, account_id))
    return {"id": account_id, "name": clean_name}


@router.delete("/api/accounts/{account_id}")
def delete_account(account_id: int, user: dict = Depends(require_login)):
    get_account_or_404(account_id, user["id"])
    with get_db() as conn:
        # Scoped to THIS user's own accounts — the old global COUNT(*) was
        # a real bug once multiple users existed (see docs/DECISIONS.md
        # 006): it could block a user from deleting their last account
        # just because other users happened to have accounts of their own.
        remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM accounts WHERE user_id = ?", (user["id"],)
        ).fetchone()["n"]
        if remaining <= 1:
            raise HTTPException(
                status_code=400,
                detail="Can't delete your last remaining account. Add another account first.",
            )
        # Any still-scheduled posts for this account have a video file held
        # on disk (see record_queued_upload) that nothing else will ever
        # clean up once the DB row is gone — delete those files first so
        # they don't leak in uploads/ forever.
        pending_paths = conn.execute(
            "SELECT video_path FROM uploads WHERE account_id = ? AND video_path IS NOT NULL",
            (account_id,),
        ).fetchall()
        # Deleting an account removes its independent workspace entirely:
        # its scheduled/published post history and its stored platform
        # credentials. This mirrors how account data is fully siloed per
        # account elsewhere (see docs/DECISIONS.md 003).
        conn.execute("DELETE FROM uploads WHERE account_id = ?", (account_id,))
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    cred_dir = account_cred_dir(account_id)
    if cred_dir.exists():
        shutil.rmtree(cred_dir, ignore_errors=True)
    for row in pending_paths:
        p = Path(row["video_path"])
        if p.exists():
            p.unlink(missing_ok=True)
    return {"ok": True}

