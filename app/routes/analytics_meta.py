"""
/api/analytics/facebook* and /api/analytics/instagram* — Facebook Page and
Instagram analytics via the Graph API. Kept in one file since both share
the _graph_get/_insights_series/_insights_total helpers below.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
import requests

from app.auth import require_login
from app.config import GRAPH_BASE
from app.credentials import get_account_or_404, get_facebook_credentials

router = APIRouter()


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


@router.get("/api/analytics/facebook")
def analytics_facebook(days: int = 28, account_id: int = 1, user: dict = Depends(require_login)):
    get_account_or_404(account_id, user["id"])
    fb_creds = get_facebook_credentials(account_id)
    if not fb_creds:
        raise HTTPException(status_code=401, detail="Facebook is not connected. Connect it from Platforms first.")

    page_id = fb_creds["page_id"]
    token = fb_creds["page_access_token"]

    page = _graph_get(page_id, {"fields": "name,followers_count", "access_token": token})

    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=max(1, days) - 1)

    # Meta has repeatedly renamed/deprecated these Page Insights metric names
    # (page_impressions -> deprecated Nov 2025 "for all API versions" per
    # Meta's own docs; page_media_view is the documented replacement, but
    # this app is pinned to Graph API v23.0 in app/config.py and it's still
    # unclear which of these metric names Meta actually accepts on that
    # version right now). Rather than guess again and risk breaking the
    # whole page over one bad metric name, each metric is fetched
    # independently here: one failing metric degrades to 0 for that number
    # instead of taking down the entire Analytics page. Whichever metric(s)
    # fail get printed server-side (check the VM logs / journalctl) so it's
    # obvious which name Meta has rejected this time.
    def _fetch_metric(metric: str):
        try:
            resp = _graph_get(
                f"{page_id}/insights",
                {
                    "metric": metric,
                    "period": "day",
                    "since": start_date.isoformat(),
                    "until": (end_date + timedelta(days=1)).isoformat(),
                    "access_token": token,
                },
            )
            return _insights_series(resp, metric), _insights_total(resp, metric)
        except HTTPException as e:
            print(f"[analytics_facebook] metric '{metric}' failed, defaulting to 0: {e.detail}")
            return [], 0

    views_series, views_total = _fetch_metric("page_media_view")
    _, video_views_total = _fetch_metric("page_video_views")
    _, engagements_total = _fetch_metric("page_post_engagements")

    daily = [{"date": d, "views": int(v)} for d, v in views_series]

    period_totals = {
        "views": views_total,
        "video_views": video_views_total,
        "engagements": engagements_total,
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


@router.get("/api/analytics/facebook/video/{video_id}")
def analytics_facebook_video_detail(video_id: str, account_id: int = 1, user: dict = Depends(require_login)):
    get_account_or_404(account_id, user["id"])
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


@router.get("/api/analytics/instagram")
def analytics_instagram(days: int = 28, account_id: int = 1, user: dict = Depends(require_login)):
    get_account_or_404(account_id, user["id"])
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

    # Real per-post views — the media list endpoint doesn't return view counts
    # inline, so (same pattern as the Facebook video list above) each one is
    # looked up individually via its own insights call. Capped to 25 to keep
    # this reasonably fast, same cap Facebook uses above. Which metric name is
    # valid depends on media_product_type (Reels vs feed posts vs carousels),
    # so we try "views" and fall back to 0 rather than failing the row.
    top_videos = []
    try:
        media = _graph_get(
            ig_id + "/media",
            {
                "fields": "id,caption,media_type,media_url,thumbnail_url,permalink,like_count,comments_count",
                "limit": 25,
                "access_token": token,
            },
        ).get("data", [])
        for m in media:
            likes = m.get("like_count", 0) or 0
            comments = m.get("comments_count", 0) or 0
            caption = (m.get("caption") or "Untitled post")[:80]
            views = 0
            try:
                vi = _graph_get(f"{m['id']}/insights", {"metric": "views", "access_token": token})
                vals = vi.get("data", [{}])[0].get("values", [{}])
                views = vals[0].get("value", 0) if vals else 0
            except Exception:
                pass  # metric not valid for this media type (e.g. some carousels/photos) — leave at 0
            top_videos.append({
                "media_id": m["id"],
                "title": caption,
                "thumbnail": m.get("thumbnail_url") or m.get("media_url"),
                "views": views,
                "engagement": likes + comments,
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


@router.get("/api/analytics/instagram/video/{media_id}")
def analytics_instagram_video_detail(media_id: str, account_id: int = 1, user: dict = Depends(require_login)):
    get_account_or_404(account_id, user["id"])
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
