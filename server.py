"""
MediaFlow local backend
------------------------
Runs on your machine (or a VM). Serves the dashboard and handles real
uploads to YouTube, Facebook, and Instagram.

This file only wires the app together — app creation, middleware, startup,
and mounting each set of routes. The actual logic lives under app/:
  app/config.py            shared paths and environment-derived settings
  app/db.py                SQLite persistence
  app/auth.py              multi-user login (sessions, password hashing)
  app/credentials.py       per-account (workspace) credential storage
  app/uploaders.py         the YouTube/Facebook/Instagram upload calls
  app/scheduler.py         the background scheduled-post poller
  app/routes/              one file per group of related routes

See README.md for what's needed to connect each platform, and
docs/DECISIONS.md 004 for how login works (real per-user accounts, not a
single shared password).
"""

import asyncio
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.auth import get_user_from_session, seed_legacy_user_if_none_exist, SESSION_COOKIE_NAME
from app.config import STATIC_DIR
from app.credentials import migrate_legacy_credentials_to_account_1
from app.db import backfill_account_ownership, backfill_admin_flag, init_db
from app.routes import (
    accounts,
    admin,
    analytics_meta,
    analytics_youtube,
    auth_pages,
    facebook_connect,
    library,
    media,
    status_publish,
    youtube_oauth,
)
from app.scheduler import _scheduler_loop

app = FastAPI(title="MediaFlow Local")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()
migrate_legacy_credentials_to_account_1()
seed_legacy_user_if_none_exist()
backfill_account_ownership()
backfill_admin_flag()

app.include_router(status_publish.router)
app.include_router(library.router)
app.include_router(accounts.router)
app.include_router(admin.router)
app.include_router(analytics_youtube.router)
app.include_router(analytics_meta.router)
app.include_router(youtube_oauth.router)
app.include_router(facebook_connect.router)
app.include_router(media.router)
app.include_router(auth_pages.router)


@app.on_event("startup")
async def _start_scheduler():
    asyncio.create_task(_scheduler_loop())


# ---------- Static frontend ----------

# The frontend is one single-page app (see build.py) whose JS shows/hides
# a <div class="page"> per section and, since the URL-scheme change (see
# docs/DECISIONS.md), keeps the browser's address bar on a matching path
# like /dashboard or /accounts instead of a ?page= query string. Every one
# of those paths needs its own real server route serving the exact same
# index.html, or a hard refresh / bookmark / shared link on any page other
# than "/" would 404 — the SPA's client-side routing only kicks in once
# index.html has already loaded and run.
_SPA_PAGES = [
    "dashboard", "accounts", "platforms", "upload",
    "scheduled", "published", "analytics", "settings", "help",
]


def _serve_spa(request: Request):
    if not get_user_from_session(request.cookies.get(SESSION_COOKIE_NAME)):
        return RedirectResponse("/login")
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/")
def index(request: Request):
    return _serve_spa(request)


for _page in _SPA_PAGES:
    app.add_api_route(f"/{_page}", _serve_spa, methods=["GET"])


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn

    # 0.0.0.0 so it's reachable from outside the VM, not just localhost.
    # Make sure your VM's firewall/security group only opens this port to
    # IPs you trust, or at minimum keep the password set above.
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
