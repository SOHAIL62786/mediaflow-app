"""
Login/signup pages and the auth API (see docs/DECISIONS.md 004).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from app.auth import (
    SESSION_COOKIE_NAME,
    create_session,
    delete_session,
    ensure_user_has_account,
    get_user_from_session,
    hash_password,
    require_login,
    set_session_cookie,
    verify_password,
)
from app.config import STATIC_DIR
from app.db import get_db

router = APIRouter()


# ---------- Auth pages + API ----------

@router.get("/login")
def login_page(request: Request):
    if get_user_from_session(request.cookies.get(SESSION_COOKIE_NAME)):
        return RedirectResponse("/")
    return FileResponse(STATIC_DIR / "login.html")


@router.get("/signup")
def signup_page(request: Request):
    if get_user_from_session(request.cookies.get(SESSION_COOKIE_NAME)):
        return RedirectResponse("/")
    return FileResponse(STATIC_DIR / "signup.html")


@router.post("/api/auth/signup")
def api_signup(request: Request, username: str = Form(...), password: str = Form(...)):
    username = username.strip()
    if len(username) < 3 or len(username) > 32:
        raise HTTPException(status_code=400, detail="Username must be 3-32 characters.")
    if not all(c.isalnum() or c in "_-." for c in username):
        raise HTTPException(status_code=400, detail="Username can only contain letters, numbers, '_', '-', and '.'")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    with get_db() as conn:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            raise HTTPException(status_code=409, detail="That username is already taken.")
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, hash_password(password), datetime.now(timezone.utc).isoformat()),
        )
        user_id = cur.lastrowid

    # Per-user data isolation (docs/DECISIONS.md 006) means a brand-new user
    # owns zero workspace accounts by default — give them one right away so
    # the account switcher/Platforms/Upload pages have somewhere to work
    # with immediately, same as Account 1 was seeded for the original
    # single-tenant install (docs/DECISIONS.md 003).
    ensure_user_has_account(user_id, username)

    token = create_session(user_id)
    resp = JSONResponse({"ok": True, "username": username})
    set_session_cookie(resp, request, token)
    return resp


@router.post("/api/auth/login")
def api_login(request: Request, username: str = Form(...), password: str = Form(...)):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect username or password.")

    token = create_session(row["id"])
    resp = JSONResponse({"ok": True, "username": row["username"]})
    set_session_cookie(resp, request, token)
    return resp


@router.post("/api/auth/logout")
def api_logout(request: Request):
    delete_session(request.cookies.get(SESSION_COOKIE_NAME))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return resp


@router.get("/api/auth/me")
def api_me(user: dict = Depends(require_login)):
    return {"username": user["username"]}

