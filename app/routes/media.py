"""
Temporary public media serving — Instagram's Content Publishing API can't
accept a direct file upload, only a fetchable URL, so this route exists
purely to serve that fetch. See the comment below for why it's
intentionally not behind login.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import UPLOAD_DIR

router = APIRouter()


# ---------- Temporary public media serving (Instagram needs a fetchable URL) ----------
# Instagram's Content Publishing API can't accept a direct file upload — it
# fetches the video from a URL you give it. This route exists only to serve
# that fetch. It's intentionally NOT behind login (Instagram's servers have
# no session cookie or account to log in with), so treat it as a narrow,
# deliberate exception: filenames are random tempfile names (not
# guessable/listable), and the file is deleted right after each publish
# attempt finishes — so the exposure window is only as long as one upload
# takes.
@router.get("/media/{filename}")
def serve_media(filename: str):
    safe_name = Path(filename).name  # strip any path components, just in case
    path = UPLOAD_DIR / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type="video/mp4")

