"""Social media (Facebook + Instagram) data endpoints."""
from fastapi import APIRouter, Depends, HTTPException
import httpx

from config.settings import settings
from models.user import User
from services.auth import get_current_user

router = APIRouter()

_FB_API = "https://graph.facebook.com/v25.0"


def _page_token() -> str:
    token = getattr(settings, "facebook_page_access_token", None)
    if not token:
        raise HTTPException(status_code=400, detail="Facebook chưa được kết nối. Vào Cài đặt để kết nối.")
    return token


def _ig_id() -> str:
    ig_id = getattr(settings, "instagram_business_account_id", None)
    if not ig_id:
        raise HTTPException(status_code=400, detail="Instagram chưa được kết nối. Vào Cài đặt để kết nối Facebook.")
    return ig_id


@router.get("/facebook/posts")
async def list_facebook_posts(limit: int = 30, user: User = Depends(get_current_user)):
    """Return recent posts from the linked Facebook Page."""
    page_id = getattr(settings, "facebook_page_id", None)
    token = _page_token()
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{_FB_API}/{page_id}/posts",
            params={
                "fields": "id,message,story,created_time,full_picture",
                "limit": min(limit, 100),
                "access_token": token,
            },
        )
        data = resp.json()
    if "error" in data:
        raise HTTPException(status_code=400, detail=f"Lỗi Facebook API: {data['error'].get('message')}")
    return data.get("data", [])


@router.get("/instagram/media")
async def list_instagram_media(limit: int = 30, user: User = Depends(get_current_user)):
    """Return recent Instagram posts from the linked Business account."""
    ig_id = _ig_id()
    token = _page_token()
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{_FB_API}/{ig_id}/media",
            params={
                "fields": "id,caption,media_type,timestamp,like_count,comments_count,permalink,media_url,thumbnail_url",
                "limit": min(limit, 100),
                "access_token": token,
            },
        )
        data = resp.json()
    if "error" in data:
        raise HTTPException(status_code=400, detail=f"Lỗi Instagram API: {data['error'].get('message')}")
    return data.get("data", [])


@router.get("/instagram/media/{media_id}/insights")
async def get_instagram_media_insights(media_id: str, user: User = Depends(get_current_user)):
    """Return insights for a specific Instagram post."""
    token = _page_token()
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{_FB_API}/{media_id}/insights",
            params={
                "metric": "impressions,reach,saved,total_interactions,follows,profile_visits,shares",
                "access_token": token,
            },
        )
        data = resp.json()
    if "error" in data:
        raise HTTPException(status_code=400, detail=f"Lỗi Instagram API: {data['error'].get('message')}")
    result = {}
    for item in data.get("data", []):
        val = item.get("values", [{}])[0].get("value", 0) if item.get("values") else item.get("value", 0)
        result[item["name"]] = val
    return result
