"""
Admin panel (see docs/DECISIONS.md 010) — list users, force a password
reset, promote/demote admins, and reassign a workspace account's owner.

Everything here is gated by require_admin (app/auth.py), never
require_login — every endpoint in this file exposes or changes another
user's data by design, which is exactly what per-user isolation
(docs/DECISIONS.md 006) otherwise exists to prevent.
"""

from fastapi import APIRouter, Depends, Form, HTTPException

from app.auth import hash_password, require_admin
from app.db import get_db

router = APIRouter()


@router.get("/api/admin/users")
def list_users(admin: dict = Depends(require_admin)):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT users.id, users.username, users.created_at, users.is_admin,
                   COUNT(accounts.id) AS account_count
            FROM users
            LEFT JOIN accounts ON accounts.user_id = users.id
            GROUP BY users.id
            ORDER BY users.id
            """
        ).fetchall()
    return [
        {
            "id": r["id"],
            "username": r["username"],
            "created_at": r["created_at"],
            "is_admin": bool(r["is_admin"]),
            "account_count": r["account_count"],
        }
        for r in rows
    ]


@router.get("/api/admin/accounts")
def list_all_accounts(admin: dict = Depends(require_admin)):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT accounts.id, accounts.name, accounts.created_at,
                   accounts.user_id, users.username AS owner_username
            FROM accounts
            LEFT JOIN users ON users.id = accounts.user_id
            ORDER BY accounts.id
            """
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/admin/accounts/{account_id}/reassign")
def reassign_account(account_id: int, new_user_id: int = Form(...), admin: dict = Depends(require_admin)):
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM accounts WHERE id = ?", (account_id,)).fetchone():
            raise HTTPException(status_code=404, detail="No such account.")
        if not conn.execute("SELECT 1 FROM users WHERE id = ?", (new_user_id,)).fetchone():
            raise HTTPException(status_code=404, detail="No such user.")
        conn.execute("UPDATE accounts SET user_id = ? WHERE id = ?", (new_user_id, account_id))
    return {"ok": True}


@router.post("/api/admin/users/{user_id}/set-password")
def admin_set_password(user_id: int, new_password: str = Form(...), admin: dict = Depends(require_admin)):
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
            raise HTTPException(status_code=404, detail="No such user.")
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new_password), user_id))
        # Force re-login everywhere — otherwise a compromised/former
        # password holder's existing session cookie would keep working
        # even after the password it was issued under has been changed.
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    return {"ok": True}


@router.post("/api/admin/users/{user_id}/set-admin")
def admin_set_admin(user_id: int, is_admin: bool = Form(...), admin: dict = Depends(require_admin)):
    with get_db() as conn:
        row = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No such user.")
        if not is_admin and row["is_admin"]:
            remaining_admins = conn.execute(
                "SELECT COUNT(*) AS n FROM users WHERE is_admin = 1 AND id != ?", (user_id,)
            ).fetchone()["n"]
            if remaining_admins == 0:
                raise HTTPException(status_code=400, detail="Can't remove the last remaining admin.")
        conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (1 if is_admin else 0, user_id))
    return {"ok": True}


@router.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: int, admin: dict = Depends(require_admin)):
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="Can't delete your own account from here — log in as another admin.")
    with get_db() as conn:
        row = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No such user.")
        owned = conn.execute("SELECT COUNT(*) AS n FROM accounts WHERE user_id = ?", (user_id,)).fetchone()["n"]
        if owned > 0:
            raise HTTPException(
                status_code=400,
                detail=f"This user still owns {owned} account(s) — reassign them first.",
            )
        if row["is_admin"]:
            remaining_admins = conn.execute(
                "SELECT COUNT(*) AS n FROM users WHERE is_admin = 1 AND id != ?", (user_id,)
            ).fetchone()["n"]
            if remaining_admins == 0:
                raise HTTPException(status_code=400, detail="Can't delete the last remaining admin.")
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return {"ok": True}
