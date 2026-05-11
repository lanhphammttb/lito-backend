"""Content routes - Content planning and demand signals."""
from typing import List, Optional
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session

from config.database import engine
from models.user import User
from models.content import ContentPlan, ContentPlanTable, DemandSignal, DemandSignalTable
from schemas.content import ContentPlanCreate, ContentPerformanceUpdate, DemandSignalCreate
from services.auth import get_current_user, get_current_user_optional
from services.activity import log_activity

router = APIRouter()

# In-memory data stores
content_plans: List[ContentPlan] = []
demand_signals: List[DemandSignal] = []


@router.get("/plans")
async def list_content_plans(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    platform: Optional[str] = None,
    user: Optional[User] = Depends(get_current_user_optional)
):
    """List content plans."""
    result = content_plans[:]
    
    if status:
        result = [c for c in result if c.status == status]
    if platform:
        result = [c for c in result if c.platform == platform]
    
    result.sort(key=lambda x: x.scheduled_date or date.max, reverse=True)
    return result[skip:skip + limit]


@router.post("/plans")
async def create_content_plan(
    payload: ContentPlanCreate,
    user: User = Depends(get_current_user)
):
    """Create content plan."""
    new_id = max((c.id for c in content_plans), default=0) + 1
    
    plan = ContentPlan(
        id=new_id,
        title=payload.title,
        content_type=payload.content_type,
        platform=payload.platform,
        product_id=payload.product_id,
        scheduled_date=payload.scheduled_date,
        status=payload.status or "draft",
        notes=payload.notes,
        created_at=datetime.utcnow(),
    )
    content_plans.append(plan)
    
    log_activity(user.id, "content_plan", new_id, "create", {"title": plan.title})
    
    return plan


@router.put("/plans/{plan_id}")
async def update_content_plan(
    plan_id: int,
    payload: ContentPlanCreate,
    user: User = Depends(get_current_user)
):
    """Update content plan."""
    plan = next((c for c in content_plans if c.id == plan_id), None)
    if not plan:
        raise HTTPException(status_code=404, detail="Content plan không tồn tại")
    
    plan.title = payload.title
    plan.content_type = payload.content_type
    plan.platform = payload.platform
    plan.product_id = payload.product_id
    plan.scheduled_date = payload.scheduled_date
    plan.status = payload.status or plan.status
    plan.notes = payload.notes
    plan.updated_at = datetime.utcnow()
    
    log_activity(user.id, "content_plan", plan_id, "update", {"title": plan.title})
    
    return plan


@router.patch("/plans/{plan_id}/performance")
async def update_content_performance(
    plan_id: int,
    payload: ContentPerformanceUpdate,
    user: User = Depends(get_current_user)
):
    """Update content performance metrics."""
    plan = next((c for c in content_plans if c.id == plan_id), None)
    if not plan:
        raise HTTPException(status_code=404, detail="Content plan không tồn tại")
    
    plan.views = payload.views
    plan.likes = payload.likes
    plan.comments = payload.comments
    plan.shares = payload.shares
    plan.click_through = payload.click_through
    plan.conversion_count = payload.conversion_count
    plan.updated_at = datetime.utcnow()
    
    return plan


@router.delete("/plans/{plan_id}")
async def delete_content_plan(
    plan_id: int,
    user: User = Depends(get_current_user)
):
    """Delete content plan."""
    plan = next((c for c in content_plans if c.id == plan_id), None)
    if not plan:
        raise HTTPException(status_code=404, detail="Content plan không tồn tại")
    
    content_plans.remove(plan)
    log_activity(user.id, "content_plan", plan_id, "delete", {})
    
    return {"message": "Đã xóa content plan"}


# Demand Signals
@router.get("/signals")
async def list_demand_signals(
    skip: int = 0,
    limit: int = 100,
    product_id: Optional[int] = None,
    user: Optional[User] = Depends(get_current_user_optional)
):
    """List demand signals."""
    result = demand_signals[:]
    
    if product_id:
        result = [d for d in result if d.product_id == product_id]
    
    result.sort(key=lambda x: x.week_of, reverse=True)
    return result[skip:skip + limit]


@router.post("/signals")
async def create_demand_signal(
    payload: DemandSignalCreate,
    user: User = Depends(get_current_user)
):
    """Create demand signal."""
    new_id = max((d.id for d in demand_signals), default=0) + 1
    
    signal = DemandSignal(
        id=new_id,
        product_id=payload.product_id,
        week_of=payload.week_of,
        views=payload.views or 0,
        add_to_cart=payload.add_to_cart or 0,
        inquiries=payload.inquiries or 0,
        orders_count=payload.orders_count or 0,
        source=payload.source,
        created_at=datetime.utcnow(),
    )
    demand_signals.append(signal)
    
    return signal


@router.get("/analytics")
async def get_content_analytics(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    user: User = Depends(get_current_user)
):
    """Get content analytics summary."""
    result = content_plans[:]
    
    if start_date:
        result = [c for c in result if c.scheduled_date and c.scheduled_date >= start_date]
    if end_date:
        result = [c for c in result if c.scheduled_date and c.scheduled_date <= end_date]
    
    total_views = sum(c.views or 0 for c in result)
    total_likes = sum(c.likes or 0 for c in result)
    total_comments = sum(c.comments or 0 for c in result)
    total_shares = sum(c.shares or 0 for c in result)
    total_conversions = sum(c.conversion_count or 0 for c in result)
    
    # By platform
    by_platform = {}
    for c in result:
        platform = c.platform or "unknown"
        if platform not in by_platform:
            by_platform[platform] = {"count": 0, "views": 0, "conversions": 0}
        by_platform[platform]["count"] += 1
        by_platform[platform]["views"] += c.views or 0
        by_platform[platform]["conversions"] += c.conversion_count or 0
    
    return {
        "total_content": len(result),
        "total_views": total_views,
        "total_likes": total_likes,
        "total_comments": total_comments,
        "total_shares": total_shares,
        "total_conversions": total_conversions,
        "engagement_rate": (total_likes + total_comments + total_shares) / total_views if total_views else 0,
        "conversion_rate": total_conversions / total_views if total_views else 0,
        "by_platform": by_platform,
    }
