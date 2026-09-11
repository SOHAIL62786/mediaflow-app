"""
MediaFlow local backend
------------------------
Runs on your machine. Serves the dashboard and handles real uploads to
YouTube via the YouTube Data API v3 (resumable upload).

Facebook / Instagram / TikTok are stubbed out — see README.md for what's
needed to wire those in, and drop credentials in credentials/ when ready.
"""

import asyncio
import json
import os
import secrets
import shutil
import sqlite3
import tempfile
import time as time_module
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

BASE_DIR = Path(__file__).parent
CRED_DIR = BASE_DIR / "credentials"
UPLOAD_DIR = BASE_DIR / "uploads"
STATIC_DIR = BASE_DIR / "static"
DB_PATH = BASE_DIR / "mediaflow.db"

# Legacy single-tenant credential paths (pre-multi-account). Used only to
# migrate an existing install's credentials into Account 1 on first boot.
LEGACY_TOKEN_PATH = CRED_DIR / "token.json"
LEGACY_CLIENT_SECRET_PATH = CRED_DIR / "client_secret.json"
LEGACY_FACEBOOK_CREDS_PATH = CRED_DIR / "facebook.json"

ACCOUNTS_CRED_DIR = CRED_DIR / "accounts"


def account_cred_dir(account_id: int) -> Path:
    d = ACCOUNTS_CRED_DIR / str(account_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def token_path(account_id: int) -> Path:
    return account_cred_dir(account_id) / "token.json"


def client_secret_path(account_id: int) -> Path:
    """The Google OAuth *app* client (Client ID/secret for the whole Google
    Cloud project) is allowed to be shared across accounts so you don't have
    to re-upload it per account — but an account can also have its own if
    you want fully separate Google Cloud projects per account."""
    per_account = account_cred_dir(account_id) / "client_secret.json"
    if per_account.exists():
        return per_account
    return LEGACY_CLIENT_SECRET_PATH


def facebook_creds_path(account_id: int) -> Path:
    return account_cred_dir(account_id) / "facebook.json"


def _migrate_legacy_credentials_to_account_1():
    """One-time migration: if this install has old single-tenant credential
    files (from before multi-account support) and Account 1 doesn't have its
    own copies yet, move them in. This is what keeps the *first* account
    working exactly as before after upgrading."""
    acc1_dir = account_cred_dir(1)
    for legacy_path, name in (
        (LEGACY_TOKEN_PATH, "token.json"),
        (LEGACY_FACEBOOK_CREDS_PATH, "facebook.json"),
    ):
        dest = acc1_dir / name
        if legacy_path.exists() and not dest.exists():
            shutil.copy2(legacy_path, dest)

GRAPH_API_VERSION = "v23.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# Scopes requested on (re)connect. Includes upload (needed today) plus
# read-only + analytics scopes so a future Analytics page doesn't need
# another re-auth round-trip.
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

UPLOAD_DIR.mkdir(exist_ok=True)

app = FastAPI(title="MediaFlow Local")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Persistence (SQLite) ----------
# Every publish/schedule attempt gets a row here so the Dashboard, Scheduled,
# and Published pages have real data to show instead of being static mockups.

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                title TEXT NOT NULL,
                caption TEXT,
                platforms TEXT NOT NULL,
                privacy TEXT,
                tags TEXT,
                made_for_kids INTEGER NOT NULL DEFAULT 0,
                contains_synthetic_media INTEGER NOT NULL DEFAULT 0,
                scheduled_time TEXT,
                status TEXT NOT NULL,
                results TEXT NOT NULL,
                video_path TEXT
            )
            """
        )
        # Migration for databases created before video_path existed (our own
        # local scheduler needs somewhere to find the file again later).
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(uploads)")}
        if "video_path" not in existing_cols:
            conn.execute("ALTER TABLE uploads ADD COLUMN video_path TEXT")

        # ---- Multi-account support ----
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        if "account_id" not in existing_cols:
            # Every existing row belongs to whatever was previously the one
            # and only account — becomes Account 1 below, unaffected.
            conn.execute("ALTER TABLE uploads ADD COLUMN account_id INTEGER NOT NULL DEFAULT 1")

        has_account_1 = conn.execute("SELECT 1 FROM accounts WHERE id = 1").fetchone()
        if not has_account_1:
            # Preserves the original single-tenant install as "Account 1" —
            # same name shown before multi-account existed, so nothing about
            # the first account changes from the user's point of view.
            conn.execute(
                "INSERT INTO accounts (id, name, created_at) VALUES (1, ?, ?)",
                ("Moiz", datetime.now(timezone.utc).isoformat()),
            )


init_db()
_migrate_legacy_credentials_to_account_1()


def record_upload(title, caption, platforms, privacy, tags, made_for_kids,
                   contains_synthetic_media, scheduled_time, results: dict,
                   account_id: int = 1) -> int:
    """For an immediate publish (no scheduling) — the platform APIs have
    already been called by the time this is written, so `results` is final."""
    oks = [r for r in results.values() if r.get("ok")]
    overall_status = "failed" if not oks else ("partial" if len(oks) < len(results) else "published")

    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO uploads
                (created_at, title, caption, platforms, privacy, tags,
                 made_for_kids, contains_synthetic_media, scheduled_time, status, results, video_path, account_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                title, caption, platforms, privacy, tags,
                int(made_for_kids), int(contains_synthetic_media),
                scheduled_time, overall_status, json.dumps(results), account_id,
            ),
        )
        return cur.lastrowid


def record_queued_upload(title, caption, platforms, privacy, tags, made_for_kids,
                          contains_synthetic_media, scheduled_time, video_path: str,
                          account_id: int = 1) -> int:
    """For a scheduled publish — we haven't called any platform API yet.
    The background scheduler does that later, at `scheduled_time`, using
    the file at `video_path`. `results` starts empty since nothing has
    happened yet."""
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO uploads
                (created_at, title, caption, platforms, privacy, tags,
                 made_for_kids, contains_synthetic_media, scheduled_time, status, results, video_path, account_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', '{}', ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                title, caption, platforms, privacy, tags,
                int(made_for_kids), int(contains_synthetic_media),
                scheduled_time, video_path, account_id,
            ),
        )
        return cur.lastrowid


def row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["made_for_kids"] = bool(d["made_for_kids"])
    d["contains_synthetic_media"] = bool(d["contains_synthetic_media"])
    d["results"] = json.loads(d["results"])
    return d

# ---------- Password protection ----------
# Once this server is reachable over the internet (VM's public IP), anyone
# who finds the URL could otherwise upload videos to your YouTube channel.
# Set APP_USERNAME / APP_PASSWORD as environment variables before running.
# If you don't set them, it falls back to admin / change-me-now and prints
# a loud warning — don't leave that running on a public IP.

APP_USERNAME = os.environ.get("APP_USERNAME", "admin")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "change-me-now")

if APP_PASSWORD == "change-me-now":
    print(
        "\n"
        "*** WARNING: using the default password (admin / change-me-now). ***\n"
        "*** Set APP_USERNAME and APP_PASSWORD env vars before exposing    ***\n"
        "*** this server on a public IP.                                  ***\n"
    )

security = HTTPBasic()


# ---------- Public base URL (needed by the background scheduler) ----------
# Interactive requests can build a public URL from the incoming request
# itself (request.base_url) — but the background scheduler that publishes
# queued videos at their scheduled time runs with no HTTP request in
# progress, so for Instagram (which needs a public URL to fetch the video
# from) it needs this configured explicitly. Only required if you schedule
# Instagram posts; everything else works without it.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")


def require_login(credentials: HTTPBasicCredentials = Depends(security)):
    correct_user = secrets.compare_digest(credentials.username, APP_USERNAME)
    correct_pass = secrets.compare_digest(credentials.password, APP_PASSWORD)
    if not (correct_user and correct_pass):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ---------- YouTube auth helpers ----------

def get_youtube_credentials(account_id: int = 1) -> Optional[Credentials]:
    """Load stored token for this account, refreshing it if it's expired.
    Persists any refresh back to that account's token.json so you don't have
    to log in again next run."""
    path = token_path(account_id)
    if not path.exists():
        return None

    with open(path, "r") as f:
        data = json.load(f)

    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes"),
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
        # persist the refreshed access token
        data["token"] = creds.token
        if creds.expiry:
            data["expiry"] = creds.expiry.isoformat() + "Z"
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    return creds


def get_youtube_client(account_id: int = 1):
    creds = get_youtube_credentials(account_id)
    if creds is None:
        raise HTTPException(status_code=401, detail="YouTube is not connected. See README to run the OAuth flow.")
    return build("youtube", "v3", credentials=creds)


# ---------- Facebook / Instagram auth helpers ----------
# Instagram publishing rides on the same Facebook Page token — there's no
# separate Instagram login. See README for how to get a Page ID + Page
# Access Token, and what Instagram Business account linking requires.

def get_facebook_credentials(account_id: int = 1) -> Optional[dict]:
    path = facebook_creds_path(account_id)
    if not path.exists():
        return None
    with open(path, "r") as f:
        return json.load(f)


def get_account_or_404(account_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT id, name, created_at FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Account {account_id} does not exist.")
    return dict(row)


# ---------- Status ----------

@app.get("/api/status")
def status(account_id: int = 1, user: str = Depends(require_login)):
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
                resp = yt.channels().list(part="snippet", mine=True).execute()
                items = resp.get("items", [])
                if items:
                    platforms["youtube"] = {
                        "connected": True,
                        "channel": items[0]["snippet"]["title"],
                    }
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
                    "fields": "name,instagram_business_account{id,username}",
                    "access_token": fb_creds["page_access_token"],
                },
                timeout=10,
            )
            data = resp.json()
            if resp.ok and "error" not in data:
                platforms["facebook"] = {"connected": True, "channel": data.get("name")}
                ig = data.get("instagram_business_account")
                if ig:
                    platforms["instagram"] = {"connected": True, "channel": ig.get("username")}
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

@app.post("/api/publish")
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
    user: str = Depends(require_login),
):
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

    # ---- Immediate publish ----
    suffix = Path(video.filename).suffix or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=UPLOAD_DIR) as tmp:
        shutil.copyfileobj(video.file, tmp)
        tmp_path = Path(tmp.name)

    results = {}
    fb_creds = get_facebook_credentials(account_id)

    try:
        for platform in selected:
            if platform == "youtube":
                results["youtube"] = _upload_to_youtube(
                    tmp_path, title, caption,
                    privacy=privacy, tags=tag_list,
                    made_for_kids=made_for_kids,
                    contains_synthetic_media=contains_synthetic_media,
                    account_id=account_id,
                )
            elif platform == "facebook":
                if not fb_creds:
                    results["facebook"] = {
                        "ok": False,
                        "error": "Facebook is not connected. Go to Platforms to add your Page credentials.",
                    }
                else:
                    results["facebook"] = _upload_to_facebook(tmp_path, title, caption, fb_creds)
            elif platform == "instagram":
                if not fb_creds or not fb_creds.get("instagram_business_account_id"):
                    results["instagram"] = {
                        "ok": False,
                        "error": "Instagram isn't linked. Connect Facebook with an Instagram Business account attached (see Platforms).",
                    }
                else:
                    # Instagram's Content Publishing API requires a public URL
                    # to fetch the video from — it can't accept a direct file
                    # upload. We serve the temp file at a short-lived public
                    # URL (random filename) and delete it right after.
                    public_url = str(request.base_url) + f"media/{tmp_path.name}"
                    results["instagram"] = _upload_to_instagram(public_url, caption, fb_creds)
            else:
                results[platform] = {
                    "ok": False,
                    "error": f"{platform} isn't wired up yet — see README.md for setup steps.",
                }
    finally:
        tmp_path.unlink(missing_ok=True)

    record_upload(
        title=title,
        caption=caption,
        platforms=",".join(selected),
        privacy=privacy,
        tags=tags,
        made_for_kids=made_for_kids,
        contains_synthetic_media=contains_synthetic_media,
        scheduled_time=None,
        results=results,
        account_id=account_id,
    )

    return JSONResponse(results)


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


@app.on_event("startup")
async def _start_scheduler():
    asyncio.create_task(_scheduler_loop())


# ---------- Library (Scheduled / Published pages) ----------

@app.get("/api/library")
def library(status: Optional[str] = None, account_id: int = 1, user: str = Depends(require_login)):
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


@app.get("/api/dashboard/summary")
def dashboard_summary(account_id: int = 1, user: str = Depends(require_login)):
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


# ---------- Accounts (multi-account switcher) ----------
# Each "account" is a fully independent set of platform connections,
# scheduled/published posts, and analytics. There's still just one shared
# login (APP_USERNAME/APP_PASSWORD) — accounts are workspaces you switch
# between after logging in, not separate user logins.

@app.get("/api/accounts")
def list_accounts(user: str = Depends(require_login)):
    with get_db() as conn:
        rows = conn.execute("SELECT id, name, created_at FROM accounts ORDER BY id").fetchall()
        return [dict(r) for r in rows]


@app.post("/api/accounts")
def create_account(name: str = Form(...), user: str = Depends(require_login)):
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Account name is required.")
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO accounts (name, created_at) VALUES (?, ?)",
            (clean_name, datetime.now(timezone.utc).isoformat()),
        )
        new_id = cur.lastrowid
    # Give the new account its own empty credentials directory right away so
    # the Platforms page has somewhere to write to as soon as it connects a
    # platform — doesn't affect any other account's files.
    account_cred_dir(new_id)
    return {"id": new_id, "name": clean_name}


@app.patch("/api/accounts/{account_id}")
def rename_account(account_id: int, name: str = Form(...), user: str = Depends(require_login)):
    get_account_or_404(account_id)
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Account name is required.")
    with get_db() as conn:
        conn.execute("UPDATE accounts SET name = ? WHERE id = ?", (clean_name, account_id))
    return {"id": account_id, "name": clean_name}


@app.delete("/api/accounts/{account_id}")
def delete_account(account_id: int, user: str = Depends(require_login)):
    get_account_or_404(account_id)
    with get_db() as conn:
        remaining = conn.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()["n"]
        if remaining <= 1:
            raise HTTPException(
                status_code=400,
                detail="Can't delete the last remaining account. Add another account first.",
            )
        # Deleting an account removes its independent workspace entirely:
        # its scheduled/published post history and its stored platform
        # credentials. This mirrors how account data is fully siloed per
        # account elsewhere (see docs/DECISIONS.md 003).
        conn.execute("DELETE FROM uploads WHERE account_id = ?", (account_id,))
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    cred_dir = account_cred_dir(account_id)
    if cred_dir.exists():
        shutil.rmtree(cred_dir, ignore_errors=True)
    return {"ok": True}


# ---------- Analytics (real YouTube Analytics data) ----------

@app.get("/api/analytics/summary")
def analytics_summary(days: int = 28, account_id: int = 1, user: str = Depends(require_login)):
    creds = get_youtube_credentials(account_id)
    if not creds:
        raise HTTPException(status_code=401, detail="YouTube is not connected. Connect it from Platforms first.")

    try:
        yt = build("youtube", "v3", credentials=creds)
        yta = build("youtubeAnalytics", "v2", credentials=creds)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not reach Google APIs: {e}")

    def _check_scope_error(e: HttpError):
        if e.resp.status == 403:
            raise HTTPException(
                status_code=403,
                detail="Your YouTube connection doesn't have analytics access yet. "
                       "Go to Platforms and reconnect YouTube to grant it.",
            )
        raise HTTPException(status_code=e.resp.status, detail=f"YouTube API error: {e}")

    # Lifetime channel stats (needs only the readonly scope)
    try:
        ch_resp = yt.channels().list(part="statistics,snippet", mine=True).execute()
    except HttpError as e:
        _check_scope_error(e)
    items = ch_resp.get("items", [])
    if not items:
        raise HTTPException(status_code=404, detail="No YouTube channel found for this account.")
    stats = items[0]["statistics"]
    channel_title = items[0]["snippet"]["title"]
    lifetime = {
        "subscribers": int(stats.get("subscriberCount", 0)),
        "total_views": int(stats.get("viewCount", 0)),
        "video_count": int(stats.get("videoCount", 0)),
    }

    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=max(1, days) - 1)
    metrics = "views,estimatedMinutesWatched,averageViewDuration,likes,comments,shares,subscribersGained,subscribersLost"

    # Period totals (single row, no dimension)
    try:
        totals_resp = yta.reports().query(
            ids="channel==MINE",
            startDate=start_date.isoformat(),
            endDate=end_date.isoformat(),
            metrics=metrics,
        ).execute()
    except HttpError as e:
        _check_scope_error(e)
    totals_headers = [h["name"] for h in totals_resp.get("columnHeaders", [])]
    totals_row = (totals_resp.get("rows") or [[0] * len(totals_headers)])[0]
    t = dict(zip(totals_headers, totals_row))
    gained = int(t.get("subscribersGained", 0))
    lost = int(t.get("subscribersLost", 0))
    period_totals = {
        "views": int(t.get("views", 0)),
        "watch_time_minutes": round(float(t.get("estimatedMinutesWatched", 0))),
        "avg_view_duration_seconds": round(float(t.get("averageViewDuration", 0))),
        "likes": int(t.get("likes", 0)),
        "comments": int(t.get("comments", 0)),
        "shares": int(t.get("shares", 0)),
        "subscribers_gained": gained,
        "subscribers_lost": lost,
        "subscribers_net": gained - lost,
    }

    # Daily series for the trend chart
    try:
        daily_resp = yta.reports().query(
            ids="channel==MINE",
            startDate=start_date.isoformat(),
            endDate=end_date.isoformat(),
            metrics="views,estimatedMinutesWatched",
            dimensions="day",
            sort="day",
        ).execute()
    except HttpError as e:
        _check_scope_error(e)
    daily_headers = [h["name"] for h in daily_resp.get("columnHeaders", [])]
    daily = []
    for row in daily_resp.get("rows") or []:
        d = dict(zip(daily_headers, row))
        daily.append({
            "date": d.get("day"),
            "views": int(d.get("views", 0)),
            "watch_time_minutes": round(float(d.get("estimatedMinutesWatched", 0))),
        })

    # Videos in the period, ranked by views — fetch a generous pool (up to 50)
    # with every metric the frontend's sort/limit filters need, so switching
    # filters doesn't require another round-trip to this endpoint.
    try:
        top_resp = yta.reports().query(
            ids="channel==MINE",
            startDate=start_date.isoformat(),
            endDate=end_date.isoformat(),
            metrics="views,estimatedMinutesWatched,likes,comments,averageViewPercentage",
            dimensions="video",
            sort="-views",
            maxResults=50,
        ).execute()
    except HttpError as e:
        _check_scope_error(e)
    top_headers = [h["name"] for h in top_resp.get("columnHeaders", [])]
    top_rows = top_resp.get("rows") or []
    video_ids = [dict(zip(top_headers, row)).get("video") for row in top_rows]

    titles, thumbs = {}, {}
    if video_ids:
        try:
            # videos().list only accepts up to 50 ids per call, which matches our cap above
            vids_resp = yt.videos().list(part="snippet", id=",".join(video_ids)).execute()
            for item in vids_resp.get("items", []):
                titles[item["id"]] = item["snippet"]["title"]
                thumbs[item["id"]] = item["snippet"]["thumbnails"].get("default", {}).get("url")
        except HttpError:
            pass  # titles are a nice-to-have; fall back to raw IDs below

    top_videos = []
    for row in top_rows:
        d = dict(zip(top_headers, row))
        vid = d.get("video")
        top_videos.append({
            "video_id": vid,
            "title": titles.get(vid, vid),
            "thumbnail": thumbs.get(vid),
            "views": int(d.get("views", 0)),
            "watch_time_minutes": round(float(d.get("estimatedMinutesWatched", 0))),
            "likes": int(d.get("likes", 0)),
            "comments": int(d.get("comments", 0)),
            "avg_view_percentage": round(float(d.get("averageViewPercentage", 0)), 1),
            "url": f"https://youtube.com/watch?v={vid}",
        })

    return {
        "channel_title": channel_title,
        "lifetime": lifetime,
        "period_days": days,
        "period_totals": period_totals,
        "daily": daily,
        "top_videos": top_videos,
    }


@app.get("/api/analytics/video/{video_id}")
def analytics_video_detail(video_id: str, days: int = 28, account_id: int = 1, user: str = Depends(require_login)):
    """Per-video detail for the metrics modal — the numbers YouTube Studio
    shows on a single video's Analytics tab, including the audience
    retention curve (the actual per-second retention data, same source
    Studio's graph uses)."""
    creds = get_youtube_credentials(account_id)
    if not creds:
        raise HTTPException(status_code=401, detail="YouTube is not connected. Connect it from Platforms first.")

    try:
        yt = build("youtube", "v3", credentials=creds)
        yta = build("youtubeAnalytics", "v2", credentials=creds)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not reach Google APIs: {e}")

    def _check_scope_error(e: HttpError):
        if e.resp.status == 403:
            raise HTTPException(
                status_code=403,
                detail="Your YouTube connection doesn't have analytics access yet. "
                       "Go to Platforms and reconnect YouTube to grant it.",
            )
        raise HTTPException(status_code=e.resp.status, detail=f"YouTube API error: {e}")

    try:
        v_resp = yt.videos().list(part="snippet,statistics,contentDetails", id=video_id).execute()
    except HttpError as e:
        _check_scope_error(e)
    items = v_resp.get("items", [])
    if not items:
        raise HTTPException(status_code=404, detail="Video not found — it may have been deleted, or belongs to a different channel.")
    v = items[0]
    thumbs = v["snippet"].get("thumbnails", {})
    lifetime = {
        "views": int(v["statistics"].get("viewCount", 0)),
        "likes": int(v["statistics"].get("likeCount", 0)),
        "comments": int(v["statistics"].get("commentCount", 0)),
    }

    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=max(1, days) - 1)
    metrics = "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,comments,shares,subscribersGained,subscribersLost"

    try:
        period_resp = yta.reports().query(
            ids="channel==MINE",
            startDate=start_date.isoformat(),
            endDate=end_date.isoformat(),
            metrics=metrics,
            filters=f"video=={video_id}",
        ).execute()
    except HttpError as e:
        _check_scope_error(e)
    period_headers = [h["name"] for h in period_resp.get("columnHeaders", [])]
    period_row = (period_resp.get("rows") or [[0] * len(period_headers)])[0]
    d = dict(zip(period_headers, period_row))
    gained = int(d.get("subscribersGained", 0))
    lost = int(d.get("subscribersLost", 0))
    period = {
        "views": int(d.get("views", 0)),
        "watch_time_minutes": round(float(d.get("estimatedMinutesWatched", 0))),
        "avg_view_duration_seconds": round(float(d.get("averageViewDuration", 0))),
        "avg_view_percentage": round(float(d.get("averageViewPercentage", 0)), 1),
        "likes": int(d.get("likes", 0)),
        "comments": int(d.get("comments", 0)),
        "shares": int(d.get("shares", 0)),
        "subscribers_gained": gained,
        "subscribers_lost": lost,
        "subscribers_net": gained - lost,
    }

    # Audience retention curve — % of viewers still watching at each point
    # in the video. This is the one metric that genuinely doesn't exist for
    # Facebook/Instagram's public APIs, only YouTube's.
    retention = []
    try:
        ret_resp = yta.reports().query(
            ids="channel==MINE",
            startDate=start_date.isoformat(),
            endDate=end_date.isoformat(),
            metrics="audienceWatchRatio",
            dimensions="elapsedVideoTimeRatio",
            filters=f"video=={video_id}",
            sort="elapsedVideoTimeRatio",
        ).execute()
        for row in ret_resp.get("rows") or []:
            retention.append({"elapsed_ratio": round(float(row[0]), 3), "audience_watch_ratio": round(float(row[1]), 3)})
    except HttpError:
        pass  # not every video has enough views for retention data — degrade gracefully

    return {
        "video_id": video_id,
        "title": v["snippet"]["title"],
        "thumbnail": (thumbs.get("medium") or thumbs.get("default") or {}).get("url"),
        "published_at": v["snippet"].get("publishedAt"),
        "lifetime": lifetime,
        "period_days": days,
        "period": period,
        "retention": retention,
        "url": f"https://youtube.com/watch?v={video_id}",
    }


# ---------- Analytics (Facebook Page + Instagram, via Graph API) ----------
# Meta deprecated the old "impressions"/"page_fans" metrics in Nov 2025 —
# this uses their replacements (page_media_view, page_follows, IG "views").

def _graph_get(path: str, params: dict) -> dict:
    resp = requests.get(f"{GRAPH_BASE}/{path}", params=params, timeout=20)
    data = resp.json()
    if not resp.ok or "error" in data:
        msg = data.get("error", {}).get("message", f"Graph API error ({resp.status_code})")
        raise HTTPException(status_code=403, detail=f"Facebook/Instagram API error: {msg}")
    return data


def _insights_series(insight_payload: dict, metric: str) -> list:
    """Pulls the per-day [(date, value), ...] series for one metric out of a
    Page/IG insights response."""
    for m in insight_payload.get("data", []):
        if m.get("name") == metric:
            return [
                (v.get("end_time", "")[:10], v.get("value", 0) or 0)
                for v in m.get("values", [])
            ]
    return []


def _insights_total(insight_payload: dict, metric: str) -> int:
    series = _insights_series(insight_payload, metric)
    total = 0
    for _, v in series:
        total += v if isinstance(v, (int, float)) else 0
    return round(total)


@app.get("/api/analytics/facebook")
def analytics_facebook(days: int = 28, account_id: int = 1, user: str = Depends(require_login)):
    fb_creds = get_facebook_credentials(account_id)
    if not fb_creds:
        raise HTTPException(status_code=401, detail="Facebook is not connected. Connect it from Platforms first.")

    page_id = fb_creds["page_id"]
    token = fb_creds["page_access_token"]

    page = _graph_get(page_id, {"fields": "name,followers_count", "access_token": token})

    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=max(1, days) - 1)

    insights = _graph_get(
        f"{page_id}/insights",
        {
            "metric": "page_media_view,page_post_engagements,page_video_views",
            "period": "day",
            "since": start_date.isoformat(),
            "until": (end_date + timedelta(days=1)).isoformat(),
            "access_token": token,
        },
    )

    views_series = _insights_series(insights, "page_media_view")
    daily = [{"date": d, "views": int(v)} for d, v in views_series]

    period_totals = {
        "views": _insights_total(insights, "page_media_view"),
        "video_views": _insights_total(insights, "page_video_views"),
        "engagements": _insights_total(insights, "page_post_engagements"),
    }

    # Videos by total views — Page videos don't return view counts inline,
    # so we look each one up individually (capped to keep this reasonably
    # fast; each extra video is one more Graph API round-trip).
    top_videos = []
    try:
        videos = _graph_get(
            f"{page_id}/videos",
            {
                "fields": "id,title,permalink_url,picture,likes.summary(true).limit(0),comments.summary(true).limit(0)",
                "limit": 25,
                "access_token": token,
            },
        ).get("data", [])
        for v in videos:
            views = 0
            try:
                vi = _graph_get(f"{v['id']}/video_insights", {"metric": "total_video_views", "access_token": token})
                vals = vi.get("data", [{}])[0].get("values", [{}])
                views = vals[0].get("value", 0) if vals else 0
            except Exception:
                pass
            top_videos.append({
                "video_id": v["id"],
                "title": v.get("title") or "Untitled video",
                "thumbnail": v.get("picture"),
                "views": views,
                "likes": v.get("likes", {}).get("summary", {}).get("total_count", 0),
                "comments": v.get("comments", {}).get("summary", {}).get("total_count", 0),
                "url": v.get("permalink_url", f"https://facebook.com/{v['id']}"),
            })
        top_videos.sort(key=lambda x: x["views"], reverse=True)
    except HTTPException:
        pass  # videos are a nice-to-have; don't fail the whole page for it

    return {
        "channel_title": page.get("name", "Facebook Page"),
        "lifetime": {"followers": page.get("followers_count", 0)},
        "period_days": days,
        "period_totals": period_totals,
        "daily": daily,
        "top_videos": top_videos,
    }


@app.get("/api/analytics/facebook/video/{video_id}")
def analytics_facebook_video_detail(video_id: str, account_id: int = 1, user: str = Depends(require_login)):
    """Per-video detail for the metrics modal. Facebook's public API doesn't
    expose a second-by-second retention curve like YouTube's — this shows
    the real metrics it does expose: views, watch time, average watch time,
    and (where available) drop-off checkpoints at 10s/30s/60s and a full
    completion rate, which is the closest Facebook equivalent to a
    retention shape."""
    fb_creds = get_facebook_credentials(account_id)
    if not fb_creds:
        raise HTTPException(status_code=401, detail="Facebook is not connected. Connect it from Platforms first.")
    token = fb_creds["page_access_token"]

    video = _graph_get(video_id, {
        "fields": "id,title,description,permalink_url,picture,created_time,"
                  "likes.summary(true).limit(0),comments.summary(true).limit(0)",
        "access_token": token,
    })

    metric_names = [
        "total_video_views", "total_video_views_unique", "total_video_view_time",
        "total_video_avg_time_watched", "total_video_10s_views", "total_video_30s_views",
        "total_video_complete_views", "total_video_impressions",
    ]
    insights = _graph_get(f"{video_id}/video_insights", {
        "metric": ",".join(metric_names), "access_token": token,
    })

    values = {}
    for m in insights.get("data", []):
        vals = m.get("values", [{}])
        values[m.get("name")] = vals[0].get("value", 0) if vals else 0

    return {
        "video_id": video_id,
        "title": video.get("title") or "Untitled video",
        "thumbnail": video.get("picture"),
        "published_at": video.get("created_time"),
        "url": video.get("permalink_url", f"https://facebook.com/{video_id}"),
        "likes": video.get("likes", {}).get("summary", {}).get("total_count", 0),
        "comments": video.get("comments", {}).get("summary", {}).get("total_count", 0),
        "metrics": {
            "views": values.get("total_video_views", 0),
            "unique_views": values.get("total_video_views_unique", 0),
            "impressions": values.get("total_video_impressions", 0),
            "total_watch_time_seconds": round((values.get("total_video_view_time", 0) or 0) / 1000),
            "avg_watch_time_seconds": round((values.get("total_video_avg_time_watched", 0) or 0) / 1000, 1),
            "views_at_10s": values.get("total_video_10s_views", 0),
            "views_at_30s": values.get("total_video_30s_views", 0),
            "complete_views": values.get("total_video_complete_views", 0),
        },
        "note": "Facebook's API doesn't provide a second-by-second retention curve like YouTube's — "
                "the 10s/30s/complete view counts above are the closest drop-off signal it exposes.",
    }


@app.get("/api/analytics/instagram")
def analytics_instagram(days: int = 28, account_id: int = 1, user: str = Depends(require_login)):
    fb_creds = get_facebook_credentials(account_id)
    ig_id = fb_creds.get("instagram_business_account_id") if fb_creds else None
    if not fb_creds or not ig_id:
        raise HTTPException(
            status_code=401,
            detail="Instagram is not connected. Connect a Facebook Page with a linked Instagram Business account first.",
        )

    token = fb_creds["page_access_token"]

    account = _graph_get(ig_id, {"fields": "username,followers_count,media_count", "access_token": token})

    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=max(1, days) - 1)

    def _total_value(payload: dict, metric: str) -> int:
        for m in payload.get("data", []):
            if m.get("name") == metric:
                return int(m.get("total_value", {}).get("value", 0) or 0)
        return 0

    # "views"/"profile_views"/"reach" are total_value-only metrics, and Meta
    # caps since/until at 30 days apart for these — so for longer ranges we
    # sum across consecutive <=30-day windows instead of one big call.
    period_totals = {"views": 0, "reach": 0, "profile_views": 0}
    window_start = start_date
    while window_start <= end_date:
        window_end = min(window_start + timedelta(days=29), end_date)
        chunk = _graph_get(
            f"{ig_id}/insights",
            {
                "metric": "reach,profile_views,views",
                "metric_type": "total_value",
                "period": "day",
                "since": window_start.isoformat(),
                "until": (window_end + timedelta(days=1)).isoformat(),
                "access_token": token,
            },
        )
        period_totals["views"] += _total_value(chunk, "views")
        period_totals["reach"] += _total_value(chunk, "reach")
        period_totals["profile_views"] += _total_value(chunk, "profile_views")
        window_start = window_end + timedelta(days=1)

    # Build the daily chart with one call per day (capped so a 90-day
    # selection doesn't fire 90 requests) — total_value metrics don't
    # support a native per-day series in one call.
    daily = []
    chart_days = min(days, 30)
    for i in range(chart_days):
        day = end_date - timedelta(days=chart_days - 1 - i)
        try:
            day_resp = _graph_get(
                f"{ig_id}/insights",
                {
                    "metric": "views",
                    "metric_type": "total_value",
                    "period": "day",
                    "since": day.isoformat(),
                    "until": (day + timedelta(days=1)).isoformat(),
                    "access_token": token,
                },
            )
            daily.append({"date": day.isoformat(), "views": _total_value(day_resp, "views")})
        except HTTPException:
            daily.append({"date": day.isoformat(), "views": 0})

    top_videos = []
    try:
        media = _graph_get(
            ig_id + "/media",
            {
                "fields": "id,caption,media_type,media_url,thumbnail_url,permalink,like_count,comments_count",
                "limit": 50,
                "access_token": token,
            },
        ).get("data", [])
        for m in media:
            likes = m.get("like_count", 0) or 0
            comments = m.get("comments_count", 0) or 0
            caption = (m.get("caption") or "Untitled post")[:80]
            top_videos.append({
                "media_id": m["id"],
                "title": caption,
                "thumbnail": m.get("thumbnail_url") or m.get("media_url"),
                "views": likes + comments,  # used only for sorting; shown as engagement below
                "likes": likes,
                "comments": comments,
                "url": m.get("permalink"),
            })
        top_videos.sort(key=lambda x: x["views"], reverse=True)
    except HTTPException:
        pass

    return {
        "channel_title": f"@{account.get('username', 'instagram')}",
        "lifetime": {"followers": account.get("followers_count", 0), "media_count": account.get("media_count", 0)},
        "period_days": days,
        "period_totals": period_totals,
        "daily": daily,
        "top_videos": top_videos,
    }


@app.get("/api/analytics/instagram/video/{media_id}")
def analytics_instagram_video_detail(media_id: str, account_id: int = 1, user: str = Depends(require_login)):
    """Per-post detail for the metrics modal. Instagram's public API doesn't
    expose a retention curve either — this shows the closest real metrics
    it does provide, which vary by media type (Reels get 'plays'/'saved',
    regular posts don't), so we fetch defensively and show whatever comes
    back rather than failing the whole request over one unsupported metric."""
    fb_creds = get_facebook_credentials(account_id)
    if not fb_creds or not fb_creds.get("instagram_business_account_id"):
        raise HTTPException(status_code=401, detail="Instagram is not connected. Connect a Facebook Page with a linked Instagram Business account first.")
    token = fb_creds["page_access_token"]

    media = _graph_get(media_id, {
        "fields": "id,caption,media_type,media_product_type,media_url,thumbnail_url,permalink,"
                  "like_count,comments_count,timestamp",
        "access_token": token,
    })

    # Try the broadest metric set first, then fall back to smaller sets —
    # which metrics are valid depends on media_product_type (REELS vs FEED
    # vs STORY), and Instagram rejects the whole call if even one metric in
    # the list doesn't apply to this media type.
    metric_attempts = [
        "views,reach,saved,shares,total_interactions",
        "reach,saved,shares,total_interactions",
        "reach,saved",
        "reach",
    ]
    insight_values = {}
    for metric_set in metric_attempts:
        try:
            resp = _graph_get(f"{media_id}/insights", {"metric": metric_set, "access_token": token})
            for m in resp.get("data", []):
                val = m.get("values", [{}])
                insight_values[m.get("name")] = val[0].get("value", 0) if val else 0
            break
        except HTTPException:
            continue  # this metric combination isn't valid for this media type — try a smaller one

    return {
        "media_id": media_id,
        "title": (media.get("caption") or "Untitled post")[:200],
        "thumbnail": media.get("thumbnail_url") or media.get("media_url"),
        "published_at": media.get("timestamp"),
        "media_type": media.get("media_product_type") or media.get("media_type"),
        "url": media.get("permalink"),
        "likes": media.get("like_count", 0),
        "comments": media.get("comments_count", 0),
        "metrics": {
            "views": insight_values.get("views", 0),
            "reach": insight_values.get("reach", 0),
            "saved": insight_values.get("saved", 0),
            "shares": insight_values.get("shares", 0),
            "total_interactions": insight_values.get("total_interactions", 0),
        },
        "note": "Instagram's API doesn't expose a retention curve like YouTube's, and which metrics "
                "are available depends on the post type (Reels vs. regular posts vs. Stories).",
    }


# ---------- YouTube connect / disconnect (OAuth) ----------

_pending_oauth_flows: dict = {}  # state -> (Flow, account_id), cleared once the callback completes


@app.get("/api/connect/youtube")
def connect_youtube(request: Request, account_id: int = 1, user: str = Depends(require_login)):
    get_account_or_404(account_id)
    secret_path = client_secret_path(account_id)
    if not secret_path.exists():
        raise HTTPException(
            status_code=400,
            detail="credentials/client_secret.json is missing — add your Google OAuth client first "
                   "(shared across accounts, or drop one in this account's own credentials folder).",
        )
    redirect_uri = str(request.base_url) + "api/oauth2callback/youtube"
    flow = Flow.from_client_secrets_file(
        str(secret_path), scopes=YOUTUBE_SCOPES, redirect_uri=redirect_uri
    )
    auth_url, state = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    _pending_oauth_flows[state] = (flow, account_id)
    return RedirectResponse(auth_url)


@app.get("/api/oauth2callback/youtube")
def oauth2callback_youtube(request: Request):
    # No @Depends(require_login) here — this is a browser redirect coming
    # back from Google, not an API call the frontend makes with basic auth.
    # HTTP Basic Auth cannot be attached to a server-initiated redirect
    # anyway, so this endpoint verifies the `state` value instead, which
    # only exists because /api/connect/youtube (which IS login-gated) issued
    # it moments earlier. The account_id it was issued for travels along
    # with the flow object in _pending_oauth_flows so the token lands in the
    # right account's credentials folder, not always Account 1.
    state = request.query_params.get("state")
    pending = _pending_oauth_flows.pop(state, None)
    if pending is None:
        raise HTTPException(status_code=400, detail="OAuth session expired or invalid — try connecting again.")
    flow, account_id = pending

    flow.fetch_token(authorization_response=str(request.url))
    creds = flow.credentials

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }
    if creds.expiry:
        token_data["expiry"] = creds.expiry.isoformat() + "Z"
    with open(token_path(account_id), "w") as f:
        json.dump(token_data, f, indent=2)

    return RedirectResponse(f"/?page=accounts&account_id={account_id}")


@app.post("/api/disconnect/youtube")
def disconnect_youtube(account_id: int = 1, user: str = Depends(require_login)):
    path = token_path(account_id)
    if path.exists():
        path.unlink()
    return {"ok": True}


# ---------- Facebook / Instagram connect / disconnect ----------
# No OAuth flow here — you already have a Page Access Token, so we just
# validate it against the Graph API and store it. See README for how to
# generate one if you ever need a fresh one.

@app.post("/api/connect/facebook")
def connect_facebook(
    app_id: str = Form(...),
    app_secret: str = Form(...),
    page_id: str = Form(...),
    page_access_token: str = Form(...),
    account_id: int = 1,
    user: str = Depends(require_login),
):
    get_account_or_404(account_id)
    try:
        resp = requests.get(
            f"{GRAPH_BASE}/{page_id}",
            params={
                "fields": "name,instagram_business_account{id,username}",
                "access_token": page_access_token,
            },
            timeout=15,
        )
        data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not reach Facebook: {e}")

    if not resp.ok or "error" in data:
        err = data.get("error", {}).get("message", "Facebook rejected these credentials.")
        raise HTTPException(status_code=400, detail=err)

    ig = data.get("instagram_business_account")
    creds = {
        "app_id": app_id,
        "app_secret": app_secret,
        "page_id": page_id,
        "page_access_token": page_access_token,
        "page_name": data.get("name"),
        "instagram_business_account_id": ig.get("id") if ig else None,
        "instagram_username": ig.get("username") if ig else None,
    }
    with open(facebook_creds_path(account_id), "w") as f:
        json.dump(creds, f, indent=2)

    return {
        "ok": True,
        "page_name": creds["page_name"],
        "instagram_linked": bool(ig),
        "instagram_username": creds["instagram_username"],
    }


@app.post("/api/disconnect/facebook")
def disconnect_facebook(account_id: int = 1, user: str = Depends(require_login)):
    path = facebook_creds_path(account_id)
    if path.exists():
        path.unlink()
    return {"ok": True}


# ---------- Temporary public media serving (Instagram needs a fetchable URL) ----------
# Instagram's Content Publishing API can't accept a direct file upload — it
# fetches the video from a URL you give it. This route exists only to serve
# that fetch. It's intentionally NOT behind login (Instagram's servers can't
# do HTTP Basic Auth), so treat it as a narrow, deliberate exception:
# filenames are random tempfile names (not guessable/listable), and the file
# is deleted right after each publish attempt finishes — so the exposure
# window is only as long as one upload takes.
@app.get("/media/{filename}")
def serve_media(filename: str):
    safe_name = Path(filename).name  # strip any path components, just in case
    path = UPLOAD_DIR / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type="video/mp4")


# ---------- Static frontend ----------

@app.get("/")
def index(user: str = Depends(require_login)):
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn

    # 0.0.0.0 so it's reachable from outside the VM, not just localhost.
    # Make sure your VM's firewall/security group only opens this port to
    # IPs you trust, or at minimum keep the password set above.
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
