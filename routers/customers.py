"""Customer routes."""
from typing import List, Optional
from datetime import datetime, date as date_type
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session

from config.database import engine, upsert_mongo, delete_mongo
from models.user import User
from models.customer import Customer, CustomerTable
from schemas.customer import CustomerCreate
from services.auth import get_current_user, get_current_user_optional
from services.customer import find_customer, compute_customer_metrics
from services.activity import log_activity, create_audit_log
from services.order import compute_order_totals

router = APIRouter()

# In-memory data stores
customers: List[Customer] = []
orders: List = []


def set_customer_orders(o):
    global orders
    orders = o


@router.get("")
async def list_customers(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    segment: Optional[str] = None,
    user: Optional[User] = Depends(get_current_user_optional)
):
    """List all customers."""
    result = customers[:]
    
    if search:
        search_lower = search.lower()
        result = [c for c in result if 
            search_lower in c.name.lower() or 
            search_lower in (c.phone or "").lower() or
            search_lower in (c.email or "").lower()
        ]
    if segment:
        result = [c for c in result if c.segment == segment]
    
    return result[skip:skip + limit]


@router.get("/segments")
async def get_customer_segments(user: User = Depends(get_current_user)):
    """Get customer segment summary."""
    segments = {}
    for c in customers:
        seg = c.segment or "unknown"
        if seg not in segments:
            segments[seg] = {"count": 0, "total_spent": 0}
        segments[seg]["count"] += 1
        segments[seg]["total_spent"] += c.total_spent or 0
    
    return segments


@router.get("/lifecycle")
async def get_customer_lifecycle(user: User = Depends(get_current_user)):
    """Get customer lifecycle stages."""
    from datetime import date, timedelta
    
    today = date.today()
    thirty_days_ago = today - timedelta(days=30)
    ninety_days_ago = today - timedelta(days=90)
    
    lifecycle = {
        "new": [],      # First order in last 30 days
        "active": [],   # Ordered in last 30 days (not new)
        "at_risk": [],  # Last order 30-90 days ago
        "dormant": [],  # Last order > 90 days ago
    }
    
    for c in customers:
        if not c.first_order_date:
            continue
        
        if c.first_order_date >= thirty_days_ago:
            lifecycle["new"].append(c)
        elif c.last_order_date and c.last_order_date >= thirty_days_ago:
            lifecycle["active"].append(c)
        elif c.last_order_date and c.last_order_date >= ninety_days_ago:
            lifecycle["at_risk"].append(c)
        else:
            lifecycle["dormant"].append(c)
    
    return {
        stage: {"count": len(custs), "customers": [{"id": c.id, "name": c.name} for c in custs[:10]]}
        for stage, custs in lifecycle.items()
    }


@router.api_route("/auto-tag", methods=["GET", "POST"])
async def auto_tag_customers(user: User = Depends(get_current_user)):
    """Auto-tag customers based on RFM analysis."""
    tagged = 0
    for c in customers:
        orders_for_customer = [o for o in orders if o.customer_id == c.id]
        if not orders_for_customer:
            continue
        total_spent = sum(compute_order_totals(o).get("revenue", 0) for o in orders_for_customer)
        if total_spent > 500000:
            if not hasattr(c, 'tags') or c.tags is None:
                c.tags = []
            if 'VIP' not in c.tags:
                c.tags.append('VIP')
                tagged += 1
    return {"tagged": tagged, "message": f"Đã gắn tag cho {tagged} khách hàng"}


@router.get("/summary")
async def get_customers_summary(user: User = Depends(get_current_user)):
    """Get customer summary with full customer and order lists."""
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    new_this_month = sum(
        1 for c in customers
        if c.created_at and c.created_at >= month_start
    )

    # Build per-customer order stats for RFM
    today = now.date()
    customer_orders: dict = {}
    for o in orders:
        cid = getattr(o, 'customer_id', None)
        if not cid:
            continue
        if getattr(o, 'status', '') in ('cancelled',):
            continue
        o_date = getattr(o, 'date', None)
        if o_date and not isinstance(o_date, date_type):
            try:
                o_date = date_type.fromisoformat(str(o_date)[:10])
            except Exception:
                o_date = None
        revenue = float(getattr(o, 'revenue', 0) or 0)
        if cid not in customer_orders:
            customer_orders[cid] = {"order_count": 0, "total_revenue": 0.0, "last_order_date": None}
        customer_orders[cid]["order_count"] += 1
        customer_orders[cid]["total_revenue"] += revenue
        if o_date and (customer_orders[cid]["last_order_date"] is None or o_date > customer_orders[cid]["last_order_date"]):
            customer_orders[cid]["last_order_date"] = o_date

    def rfm_score(recency_days, frequency, monetary):
        r = 5 if recency_days <= 14 else 4 if recency_days <= 30 else 3 if recency_days <= 60 else 2 if recency_days <= 90 else 1
        f = 5 if frequency >= 10 else 4 if frequency >= 5 else 3 if frequency >= 3 else 2 if frequency >= 2 else 1
        m = 5 if monetary >= 2000000 else 4 if monetary >= 1000000 else 3 if monetary >= 500000 else 2 if monetary >= 200000 else 1
        return r + f + m

    analytics = []
    for c in customers:
        stats = customer_orders.get(c.id, {})
        order_count = stats.get("order_count", 0)
        total_revenue = stats.get("total_revenue", 0.0)
        last_date = stats.get("last_order_date")
        recency_days = (today - last_date).days if last_date else 999
        analytics.append({
            "customer_id": c.id,
            "name": c.name,
            "order_count": order_count,
            "total_revenue": round(total_revenue, 2),
            "total_spent": float(c.total_spent or 0),
            "recency_days": recency_days,
            "rfm_score": rfm_score(recency_days, order_count, total_revenue),
            "last_order_date": str(last_date) if last_date else None,
        })
    analytics.sort(key=lambda x: x["rfm_score"], reverse=True)

    return {
        "total": len(customers),
        "new_this_month": new_this_month,
        "total_spent": sum(c.total_spent or 0 for c in customers),
        "customers": [c.model_dump() for c in customers],
        "orders": [o.model_dump() for o in orders],
        "analytics": analytics,
    }


@router.get("/{customer_id}")
async def get_customer(
    customer_id: int,
    user: Optional[User] = Depends(get_current_user_optional)
):
    """Get single customer."""
    return find_customer(customer_id)


@router.post("")
async def create_customer(
    payload: CustomerCreate,
    request: Request,
    user: User = Depends(get_current_user)
):
    """Create new customer."""
    new_id = max((c.id for c in customers), default=0) + 1
    now = datetime.utcnow()
    
    customer = Customer(
        id=new_id,
        name=payload.name,
        phone=payload.phone,
        email=payload.email,
        address=payload.address,
        note=payload.note,
        segment=payload.segment,
        source=payload.source,
        tags=payload.tags or [],
        created_at=now,
    )
    customers.append(customer)
    
    # Save to SQL
    with Session(engine) as session:
        session.add(CustomerTable(
            name=customer.name,
            phone=customer.phone,
            email=customer.email,
            address=customer.address,
            note=customer.note,
            segment=customer.segment,
            source=customer.source,
            tags=str(customer.tags) if customer.tags else None,
            created_at=customer.created_at,
        ))
        session.commit()
    
    upsert_mongo("customers", customer.model_dump(mode="json") if hasattr(customer, "model_dump") else customer.__dict__)
    log_activity(user.id, "customer", new_id, "create", {"name": customer.name})
    await create_audit_log(user, "CREATE", "customers", new_id, None, customer.__dict__, request)
    return customer


@router.put("/{customer_id}")
async def update_customer(
    customer_id: int,
    payload: CustomerCreate,
    request: Request,
    user: User = Depends(get_current_user)
):
    """Update customer."""
    customer = find_customer(customer_id)
    before_data = customer.__dict__.copy()
    
    customer.name = payload.name
    customer.phone = payload.phone
    customer.email = payload.email
    customer.address = payload.address
    customer.note = payload.note
    customer.segment = payload.segment
    customer.source = payload.source
    customer.tags = payload.tags or customer.tags
    
    # Update in SQL
    with Session(engine) as session:
        row = session.get(CustomerTable, customer_id)
        if row:
            row.name = customer.name
            row.phone = customer.phone
            row.email = customer.email
            row.address = customer.address
            row.note = customer.note
            row.segment = customer.segment
            row.source = customer.source
            row.tags = str(customer.tags) if customer.tags else None
            session.add(row)
            session.commit()
    
    log_activity(user.id, "customer", customer_id, "update", {"name": customer.name})
    await create_audit_log(user, "UPDATE", "customers", customer_id, before_data, customer.__dict__, request)
    
    return customer


@router.delete("/{customer_id}")
async def delete_customer(
    customer_id: int,
    request: Request,
    user: User = Depends(get_current_user)
):
    """Delete customer."""
    customer = find_customer(customer_id)
    before_data = customer.__dict__.copy()
    
    customers.remove(customer)
    
    # Delete from SQL
    with Session(engine) as session:
        row = session.get(CustomerTable, customer_id)
        if row:
            session.delete(row)
            session.commit()
    
    delete_mongo("customers", "id", customer_id)
    log_activity(user.id, "customer", customer_id, "delete", {"name": customer.name})
    await create_audit_log(user, "DELETE", "customers", customer_id, before_data, None, request)
    return {"message": "Đã xóa khách hàng"}


@router.post("/recompute-metrics")
async def recompute_metrics(user: User = Depends(get_current_user)):
    """Recompute all customer metrics."""
    compute_customer_metrics()
    return {"message": "Đã cập nhật metrics cho tất cả khách hàng"}
