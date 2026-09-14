"""
/api/analytics/summary and /api/analytics/video/{video_id} — real YouTube
Analytics data (YouTube Data API + YouTube Analytics API).
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.auth import require_login
from app.credentials import get_account_or_404, get_youtube_credentials

router = APIRouter()


# ---------- Analytics (real YouTube Analytics data) ----------

# YouTube Analytics' "day" dimension is bucketed in Pacific Time (same as
# YouTube Studio), not UTC — this matters most for a 1-day ("Today") window,
# where a UTC-based boundary could be up to ~8 hours off from what Studio
# shows as "today".
YT_ANALYTICS_TZ = ZoneInfo("America/Los_Angeles")

@router.get("/api/analytics/summary")
def analytics_summary(days: int = 28, account_id: int = 1, user: dict = Depends(require_login)):
    get_account_or_404(account_id, user["id"])
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

    end_date = datetime.now(YT_ANALYTICS_TZ).date()
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

    titles, thumbs, lifetime_views = {}, {}, {}
    if video_ids:
        try:
            # videos().list only accepts up to 50 ids per call, which matches our cap above
            vids_resp = yt.videos().list(part="snippet,statistics", id=",".join(video_ids)).execute()
            for item in vids_resp.get("items", []):
                titles[item["id"]] = item["snippet"]["title"]
                thumbs[item["id"]] = item["snippet"]["thumbnails"].get("default", {}).get("url")
                lifetime_views[item["id"]] = int(item["statistics"].get("viewCount", 0))
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
            "lifetime_views": lifetime_views.get(vid, 0),
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


@router.get("/api/analytics/video/{video_id}")
def analytics_video_detail(video_id: str, days: int = 28, account_id: int = 1, user: dict = Depends(require_login)):
    get_account_or_404(account_id, user["id"])
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

    end_date = datetime.now(YT_ANALYTICS_TZ).date()
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


