"""Growth analytics router - business health, AARRR, cohorts, content plans, signals, funnel, benchmarks, marketing frameworks."""
from typing import List, Optional
from datetime import datetime, timedelta, date
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict


class DummyModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ContentPlan(DummyModel): pass
class ContentPlanCreate(DummyModel): pass
class ContentPerformanceUpdate(DummyModel): pass


router = APIRouter()

products: List = []
orders: List = []
materials: List = []
customers: List = []
content_plans: List = []
demand_signals: List = []

# Stubs used by analytics/issues diagnosis
product_reviews: List = []
product_images: List = []
price_changes: List = []
seasons: List = []


def set_data_stores(p, o, m, c, cp, ds):
    global products, orders, materials, customers, content_plans, demand_signals
    products = p; orders = o; materials = m; customers = c; content_plans = cp; demand_signals = ds


def compute_order_totals(order):
    if isinstance(order, dict):
        items = order.get("items", order.get("order_lines", []))
        revenue = sum(item.get("unit_price", 0) * item.get("quantity", 0) for item in items)
    else:
        lines = getattr(order, "order_lines", getattr(order, "items", []))
        revenue = sum(getattr(item, "unit_price", 0) * getattr(item, "quantity", 0) for item in (lines or []))
    return {"revenue": revenue, "cost": 0, "profit": revenue}


def compute_customer_metrics():
    for cust in customers:
        if not hasattr(cust, 'total_orders'):
            cust.total_orders = 0
            cust.total_spent = 0
            cust.last_order_date = None
            cust.first_order_date = None


def next_id(collection) -> int:
    return max((item.id for item in collection), default=0) + 1


# --- Content plan endpoints ---------------------------------------------------

@router.get("/content-plans")
async def list_content_plans():
    return content_plans


@router.post("/content-plans")
async def create_content_plan(payload: ContentPlanCreate):
    related_product_id = getattr(payload, 'related_product_id', None)
    if related_product_id:
        if not any(p.id == related_product_id for p in products):
            raise HTTPException(status_code=404, detail="Product không tồn tại")
    new_plan = ContentPlan(id=next_id(content_plans), **payload.model_dump(), created_by=1)
    content_plans.append(new_plan)
    return new_plan


@router.put("/content-plans/{plan_id}")
async def update_content_plan(plan_id: int, payload: ContentPlan):
    if getattr(payload, 'id', plan_id) != plan_id:
        raise HTTPException(status_code=400, detail="Không được đổi id")
    related_product_id = getattr(payload, 'related_product_id', None)
    if related_product_id:
        if not any(p.id == related_product_id for p in products):
            raise HTTPException(status_code=404, detail="Product không tồn tại")
    for idx, plan in enumerate(content_plans):
        if plan.id == plan_id:
            payload.created_by = getattr(plan, 'created_by', None) or getattr(payload, 'created_by', None)
            payload.updated_by = 1
            content_plans[idx] = payload
            return payload
    raise HTTPException(status_code=404, detail="Content plan không tồn tại")


@router.post("/content-plans/{plan_id}/performance")
async def update_content_performance(plan_id: int, payload: ContentPerformanceUpdate):
    for idx, plan in enumerate(content_plans):
        if plan.id == plan_id:
            data = plan.model_dump()
            for field, value in payload.model_dump(exclude_none=True).items():
                data[field] = value
            updated = ContentPlan(**data, updated_by=1)
            content_plans[idx] = updated
            return updated
    raise HTTPException(status_code=404, detail="Content plan không tồn tại")


@router.get("/content-plans/analytics")
async def content_performance_analytics():
    analytics = []

    for content in content_plans:
        if content.status not in ("published", "Đã đăng") or not content.actual_revenue:
            continue

        cost_to_create = 0
        roi = 0

        views = content.actual_views or 0
        inquiries = content.actual_inquiries or 0
        content_orders = content.actual_orders or 0

        view_to_inquiry = (inquiries / views * 100) if views > 0 else 0
        inquiry_to_order = (content_orders / inquiries * 100) if inquiries > 0 else 0
        view_to_order = (content_orders / views * 100) if views > 0 else 0
        revenue_per_view = content.actual_revenue / views if views > 0 else 0

        analytics.append({
            "content_id": content.id,
            "product_id": content.related_product_id,
            "format": content.format,
            "channel": content.channel,
            "published_date": content.published_date,
            "views": views,
            "inquiries": inquiries,
            "orders": content_orders,
            "revenue": content.actual_revenue,
            "cost": cost_to_create,
            "roi": round(roi, 2),
            "view_to_inquiry_rate": round(view_to_inquiry, 2),
            "inquiry_to_order_rate": round(inquiry_to_order, 2),
            "view_to_order_rate": round(view_to_order, 2),
            "revenue_per_view": round(revenue_per_view, 2)
        })

    format_stats = {}
    for a in analytics:
        fmt = a["format"]
        if fmt not in format_stats:
            format_stats[fmt] = {"count": 0, "total_revenue": 0, "total_views": 0, "total_roi": 0}
        format_stats[fmt]["count"] += 1
        format_stats[fmt]["total_revenue"] += a["revenue"]
        format_stats[fmt]["total_views"] += a["views"]
        format_stats[fmt]["total_roi"] += a["roi"]

    best_formats = [
        {
            "format": fmt,
            "count": stats["count"],
            "avg_revenue": round(stats["total_revenue"] / stats["count"], 2),
            "avg_views": round(stats["total_views"] / stats["count"], 2),
            "avg_roi": round(stats["total_roi"] / stats["count"], 2)
        }
        for fmt, stats in format_stats.items()
    ]
    best_formats.sort(key=lambda x: x["avg_roi"], reverse=True)

    day_stats = {}
    for a in analytics:
        if a["published_date"]:
            day = a["published_date"].strftime("%A")
            if day not in day_stats:
                day_stats[day] = {"count": 0, "total_views": 0, "total_revenue": 0}
            day_stats[day]["count"] += 1
            day_stats[day]["total_views"] += a["views"]
            day_stats[day]["total_revenue"] += a["revenue"]

    best_days = [
        {
            "day": day,
            "count": stats["count"],
            "avg_views": round(stats["total_views"] / stats["count"], 2),
            "avg_revenue": round(stats["total_revenue"] / stats["count"], 2)
        }
        for day, stats in day_stats.items()
    ]
    best_days.sort(key=lambda x: x["avg_revenue"], reverse=True)

    product_frequency = {}
    for content in content_plans:
        if content.related_product_id:
            product_frequency[content.related_product_id] = product_frequency.get(content.related_product_id, 0) + 1

    fatigued_products = [
        {"product_id": pid, "post_count": count}
        for pid, count in product_frequency.items()
        if count > 10
    ]

    return {
        "contents": analytics,
        "best_formats": best_formats,
        "best_posting_days": best_days,
        "fatigued_products": fatigued_products,
        "summary": {
            "total_contents": len(analytics),
            "total_revenue": round(sum(a["revenue"] for a in analytics), 2),
            "total_cost": round(sum(a["cost"] for a in analytics), 2),
            "avg_roi": round(sum(a["roi"] for a in analytics) / len(analytics), 2) if analytics else 0,
            "avg_conversion": round(sum(a["view_to_order_rate"] for a in analytics) / len(analytics), 2) if analytics else 0
        }
    }


@router.delete("/content-plans/{plan_id}")
async def delete_content_plan(plan_id: int):
    for plan in content_plans:
        if plan.id == plan_id:
            content_plans.remove(plan)
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Content plan không tồn tại")


# --- Business health ----------------------------------------------------------

@router.get("/business-health")
async def get_business_health():
    total_customers = len(customers)
    total_orders_count = len(orders)
    total_revenue = sum(compute_order_totals(o)["revenue"] for o in orders)

    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    sixty_days_ago = now - timedelta(days=60)

    recent_orders = [o for o in orders if o.date >= thirty_days_ago.date()]
    recent_revenue = sum(compute_order_totals(o)["revenue"] for o in recent_orders)
    recent_customers = len(set(o.customer_id for o in recent_orders))

    previous_orders = [o for o in orders if sixty_days_ago.date() <= o.date < thirty_days_ago.date()]
    previous_revenue = sum(compute_order_totals(o)["revenue"] for o in previous_orders)

    mar = recent_revenue / recent_customers if recent_customers > 0 else 0

    total_content = len(content_plans)
    estimated_content_cost = total_content * 50000
    cac = estimated_content_cost / total_customers if total_customers > 0 else 0

    avg_order_value = total_revenue / total_orders_count if total_orders_count > 0 else 0

    customer_order_counts = {}
    for order in orders:
        customer_order_counts[order.customer_id] = customer_order_counts.get(order.customer_id, 0) + 1

    repeat_customers = sum(1 for count in customer_order_counts.values() if count > 1)
    repeat_rate = repeat_customers / total_customers if total_customers > 0 else 0

    avg_purchases_per_customer = total_orders_count / total_customers if total_customers > 0 else 1
    ltv = avg_order_value * avg_purchases_per_customer * 2

    ltv_cac_ratio = ltv / cac if cac > 0 else 0

    monthly_revenue_per_customer = mar
    payback_period = cac / monthly_revenue_per_customer if monthly_revenue_per_customer > 0 else 0

    monthly_material_cost = sum(m.stock_quantity * m.unit_price for m in materials) / 12
    monthly_fixed_costs = 5000000
    monthly_burn = monthly_material_cost + monthly_fixed_costs + estimated_content_cost / 12

    total_material_cost = sum(
        sum(
            usage.quantity * next((m.unit_price for m in materials if m.id == usage.material_id), 0)
            for usage in p.materials
        )
        for p in products
    )
    gross_margin = (total_revenue - total_material_cost) / total_revenue if total_revenue > 0 else 0

    health_components = {
        "revenue_growth": min(100, ((recent_revenue - previous_revenue) / previous_revenue * 100) if previous_revenue > 0 else 50),
        "ltv_cac_ratio": min(100, ltv_cac_ratio / 5 * 100),
        "gross_margin": gross_margin * 100,
        "repeat_rate": repeat_rate * 100,
        "inventory_efficiency": min(100, (1 - len([m for m in materials if m.stock_quantity < m.low_threshold]) / len(materials)) * 100 if materials else 0)
    }

    health_score = sum(health_components.values()) / len(health_components)
    revenue_growth_rate = ((recent_revenue - previous_revenue) / previous_revenue * 100) if previous_revenue > 0 else 0

    return {
        "north_star_metric": {
            "name": "Monthly Active Revenue (MAR)",
            "value": round(mar, 0),
            "unit": "VND/customer",
            "description": "Revenue per active customer in last 30 days"
        },
        "unit_economics": {
            "cac": round(cac, 0),
            "ltv": round(ltv, 0),
            "ltv_cac_ratio": round(ltv_cac_ratio, 2),
            "payback_period": round(payback_period, 1),
            "avg_order_value": round(avg_order_value, 0),
            "repeat_rate": round(repeat_rate * 100, 1)
        },
        "financial_metrics": {
            "total_revenue": round(total_revenue, 0),
            "recent_revenue": round(recent_revenue, 0),
            "revenue_growth_rate": round(revenue_growth_rate, 1),
            "gross_margin": round(gross_margin * 100, 1),
            "monthly_burn": round(monthly_burn, 0)
        },
        "health_score": {
            "overall": round(health_score, 1),
            "components": {k: round(v, 1) for k, v in health_components.items()},
            "rating": "excellent" if health_score >= 80 else "good" if health_score >= 60 else "fair" if health_score >= 40 else "poor"
        },
        "summary": {
            "total_customers": total_customers,
            "total_orders": total_orders_count,
            "active_customers_30d": recent_customers,
            "avg_purchases_per_customer": round(avg_purchases_per_customer, 2)
        }
    }


# --- AARRR metrics ------------------------------------------------------------

@router.get("/growth/aarrr-metrics")
async def get_aarrr_metrics():
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    ninety_days_ago = now - timedelta(days=90)

    new_customers_30d = [c for c in customers if c.created_at >= thirty_days_ago]
    new_customers_90d = [c for c in customers if c.created_at >= ninety_days_ago]

    content_views = sum(cp.estimate_views or 0 for cp in content_plans)
    content_engagement = sum(cp.estimate_inquiries or 0 for cp in content_plans)

    activated_customers = 0
    for customer in new_customers_30d:
        first_order = next((o for o in orders if hasattr(o, 'customer_id') and o.customer_id == customer.id), None)
        if first_order and hasattr(first_order, 'date') and first_order.date:
            order_datetime = datetime.combine(first_order.date, datetime.min.time())
            days_diff = (order_datetime - customer.created_at).days
            if days_diff <= 7:
                activated_customers += 1

    activation_rate = activated_customers / len(new_customers_30d) if new_customers_30d else 0

    sixty_days_ago = now - timedelta(days=60)
    cohort_customers = [c for c in customers if c.created_at and ninety_days_ago <= c.created_at < sixty_days_ago]
    retained_customers = []
    for c in cohort_customers:
        has_recent_order = any(
            hasattr(o, 'customer_id') and hasattr(o, 'date') and
            o.customer_id == c.id and o.date and o.date >= thirty_days_ago.date()
            for o in orders
        )
        if has_recent_order:
            retained_customers.append(c)
    retention_rate = len(retained_customers) / len(cohort_customers) if cohort_customers else 0

    total_revenue = 0
    revenue_30d = 0
    paying_customer_ids = set()

    for o in orders:
        try:
            totals = compute_order_totals(o)
            revenue = totals.get("revenue", 0)
            total_revenue += revenue
            if hasattr(o, 'date') and o.date and o.date >= thirty_days_ago.date():
                revenue_30d += revenue
            if hasattr(o, 'customer_id') and o.customer_id:
                paying_customer_ids.add(o.customer_id)
        except Exception:
            continue

    arpu = total_revenue / len(customers) if customers else 0
    paying_customers = len(paying_customer_ids)
    arppu = total_revenue / paying_customers if paying_customers > 0 else 0

    referral_customers = []
    for c in customers:
        tags_list = c.tags if c.tags else []
        tags_str = ' '.join(tags_list).lower() if isinstance(tags_list, list) else str(tags_list).lower()
        if 'referral' in tags_str or 'word-of-mouth' in tags_str:
            referral_customers.append(c)
    referral_rate = len(referral_customers) / len(customers) if customers else 0

    funnel_data = {
        "acquisition": {
            "visitors": content_views,
            "leads": content_engagement,
            "customers": len(new_customers_30d)
        },
        "activation": {
            "signups": len(new_customers_30d),
            "activated": activated_customers,
            "rate": round(activation_rate * 100, 1)
        },
        "retention": {
            "cohort_size": len(cohort_customers),
            "retained": len(retained_customers),
            "rate": round(retention_rate * 100, 1)
        },
        "revenue": {
            "total_customers": len(customers),
            "paying_customers": paying_customers,
            "arpu": round(arpu, 0),
            "arppu": round(arppu, 0),
            "mrr": round(revenue_30d, 0)
        },
        "referral": {
            "total_customers": len(customers),
            "referral_customers": len(referral_customers),
            "rate": round(referral_rate * 100, 1)
        }
    }

    insights = []
    if activation_rate < 0.3:
        insights.append({
            "type": "warning",
            "metric": "Activation",
            "message": f"Activation rate is low ({activation_rate*100:.1f}%). Focus on first-time buyer experience.",
            "action": "Create welcome discount or first-purchase bundle"
        })

    if retention_rate < 0.2:
        insights.append({
            "type": "warning",
            "metric": "Retention",
            "message": f"Retention rate is {retention_rate*100:.1f}%. Customers not coming back.",
            "action": "Implement loyalty program or email remarketing"
        })

    if referral_rate < 0.1:
        insights.append({
            "type": "opportunity",
            "metric": "Referral",
            "message": f"Only {referral_rate*100:.1f}% customers from referrals. Huge growth opportunity.",
            "action": "Create referral program with incentives"
        })

    if activation_rate > 0.5:
        insights.append({
            "type": "success",
            "metric": "Activation",
            "message": f"Strong activation rate ({activation_rate*100:.1f}%). Keep this momentum!",
            "action": "Document what works and scale acquisition"
        })

    revenue_prev_period = total_revenue - revenue_30d
    if revenue_prev_period > 0:
        revenue_growth = round((revenue_30d / revenue_prev_period * 100), 1)
    else:
        revenue_growth = 100.0 if revenue_30d > 0 else 0.0

    return {
        "funnel": funnel_data,
        "insights": insights,
        "summary": {
            "acquisition_velocity": len(new_customers_30d),
            "activation_rate": round(activation_rate * 100, 1),
            "retention_rate": round(retention_rate * 100, 1),
            "revenue_growth": revenue_growth,
            "referral_rate": round(referral_rate * 100, 1)
        },
        "period": "last_30_days"
    }


# --- Customer lifecycle -------------------------------------------------------

@router.get("/customers/lifecycle-analysis")
async def customer_lifecycle_analysis():
    compute_customer_metrics()
    today = date.today()

    segments = {
        "champions": [],
        "loyal": [],
        "at_risk": [],
        "win_back": [],
        "new": [],
        "promising": []
    }

    for customer in customers:
        if customer.total_orders == 0:
            continue

        recency_days = (today - customer.last_order_date).days if customer.last_order_date else 999
        frequency = customer.total_orders
        monetary = customer.total_spent / customer.total_orders if customer.total_orders else 0

        r_score = 5 if recency_days <= 30 else 4 if recency_days <= 60 else 3 if recency_days <= 120 else 2 if recency_days <= 180 else 1
        f_score = 5 if frequency >= 10 else 4 if frequency >= 6 else 3 if frequency >= 3 else 2 if frequency >= 2 else 1
        m_score = 5 if monetary >= 1_000_000 else 4 if monetary >= 500_000 else 3 if monetary >= 200_000 else 2 if monetary >= 100_000 else 1
        rfm_score = r_score + f_score + m_score

        customer_data = {
            "customer_id": customer.id,
            "name": customer.name,
            "recency_days": recency_days,
            "frequency": frequency,
            "monetary": round(monetary, 2),
            "rfm_score": rfm_score,
            "suggested_action": ""
        }

        if r_score >= 4 and f_score >= 4 and m_score >= 4:
            customer_data["suggested_action"] = "VIP treatment: Exclusive offers, early access"
            segments["champions"].append(customer_data)
        elif f_score >= 3 and m_score >= 3:
            customer_data["suggested_action"] = "Loyalty rewards, thank you notes"
            segments["loyal"].append(customer_data)
        elif r_score <= 2 and f_score >= 2:
            customer_data["suggested_action"] = "Win-back campaign: Special discount"
            segments["win_back"].append(customer_data)
        elif r_score == 3 and f_score >= 2:
            customer_data["suggested_action"] = "Re-engagement: New collection"
            segments["at_risk"].append(customer_data)
        elif frequency == 1 and recency_days <= 30:
            customer_data["suggested_action"] = "Welcome series, second purchase"
            segments["new"].append(customer_data)
        elif frequency == 1 and recency_days <= 60:
            customer_data["suggested_action"] = "Follow-up, ask for feedback"
            segments["promising"].append(customer_data)

    return {
        "segments": segments,
        "summary": {
            "champions": len(segments["champions"]),
            "loyal": len(segments["loyal"]),
            "at_risk": len(segments["at_risk"]),
            "win_back": len(segments["win_back"]),
            "new": len(segments["new"]),
            "promising": len(segments["promising"])
        }
    }


# --- Cohort analysis ----------------------------------------------------------

@router.get("/customers/cohort-analysis")
async def get_cohort_analysis():
    cohorts = defaultdict(list)
    for customer in customers:
        cohort_month = customer.created_at.strftime("%Y-%m")
        cohorts[cohort_month].append(customer)

    cohort_data = []
    for cohort_month, cohort_customers in sorted(cohorts.items()):
        cohort_size = len(cohort_customers)
        cohort_start = datetime.strptime(cohort_month, "%Y-%m")

        retention_by_month = {}
        revenue_by_month = {}

        for i in range(12):
            month_start = cohort_start + timedelta(days=30 * i)
            month_end = month_start + timedelta(days=30)

            active_in_month = set()
            revenue_in_month = 0

            cohort_customer_ids = {c.id for c in cohort_customers}
            for order in orders:
                if order.customer_id in cohort_customer_ids:
                    order_dt = datetime.combine(order.date, datetime.min.time()) if hasattr(order.date, 'year') else order.created_at
                    if month_start <= order_dt < month_end:
                        active_in_month.add(order.customer_id)
                        revenue_in_month += compute_order_totals(order).get("revenue", 0)

            retention_rate = len(active_in_month) / cohort_size if cohort_size > 0 else 0
            avg_revenue = revenue_in_month / cohort_size if cohort_size > 0 else 0

            retention_by_month[f"month_{i}"] = round(retention_rate * 100, 1)
            revenue_by_month[f"month_{i}"] = round(avg_revenue, 0)

        cohort_orders = [o for o in orders if o.customer_id in [c.id for c in cohort_customers]]
        cohort_revenue = sum(compute_order_totals(o)["revenue"] for o in cohort_orders)
        cohort_ltv = cohort_revenue / cohort_size if cohort_size > 0 else 0

        cohort_data.append({
            "cohort": cohort_month,
            "size": cohort_size,
            "retention": retention_by_month,
            "revenue": revenue_by_month,
            "ltv": round(cohort_ltv, 0),
            "total_orders": len(cohort_orders)
        })

    if cohort_data:
        avg_month_1_retention = sum(c["retention"]["month_1"] for c in cohort_data) / len(cohort_data)
        avg_month_3_retention = sum(c["retention"]["month_3"] for c in cohort_data if "month_3" in c["retention"]) / len([c for c in cohort_data if "month_3" in c["retention"]]) if any("month_3" in c["retention"] for c in cohort_data) else 0
        avg_month_6_retention = sum(c["retention"]["month_6"] for c in cohort_data if "month_6" in c["retention"]) / len([c for c in cohort_data if "month_6" in c["retention"]]) if any("month_6" in c["retention"] for c in cohort_data) else 0
    else:
        avg_month_1_retention = avg_month_3_retention = avg_month_6_retention = 0

    return {
        "cohorts": cohort_data,
        "summary": {
            "total_cohorts": len(cohort_data),
            "avg_cohort_size": round(sum(c["size"] for c in cohort_data) / len(cohort_data), 1) if cohort_data else 0,
            "avg_month_1_retention": round(avg_month_1_retention, 1),
            "avg_month_3_retention": round(avg_month_3_retention, 1),
            "avg_month_6_retention": round(avg_month_6_retention, 1),
            "avg_ltv": round(sum(c["ltv"] for c in cohort_data) / len(cohort_data), 0) if cohort_data else 0
        },
        "insights": [
            {
                "type": "info",
                "message": f"Month 1 retention: {avg_month_1_retention:.1f}%. Industry benchmark for handmade: 25-35%"
            },
            {
                "type": "warning" if avg_month_3_retention < 15 else "success",
                "message": f"Month 3 retention: {avg_month_3_retention:.1f}%. {'Need improvement' if avg_month_3_retention < 15 else 'Good performance'}"
            }
        ]
    }


# --- Signal detection ---------------------------------------------------------

@router.get("/analytics/signals")
async def detect_signals():
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    sixty_days_ago = now - timedelta(days=60)

    current_period_start = thirty_days_ago.date()
    current_period_end = now.date()
    previous_period_start = sixty_days_ago.date()
    previous_period_end = thirty_days_ago.date()

    signals = []

    for product in products:
        product_signals = []

        current_demand = [d for d in demand_signals if d.product_id == product.id and current_period_start <= d.week_of <= current_period_end]
        previous_demand = [d for d in demand_signals if d.product_id == product.id and previous_period_start <= d.week_of <= previous_period_end]

        # 1. VIEW DROP
        current_views = sum(d.views for d in current_demand)
        previous_views = sum(d.views for d in previous_demand)

        if previous_views > 0:
            view_change = ((current_views - previous_views) / previous_views) * 100
            if view_change < -20:
                product_signals.append({
                    "type": "view_drop",
                    "severity": "critical" if view_change < -50 else "high" if view_change < -30 else "medium",
                    "change_percent": round(view_change, 1),
                    "prev_value": previous_views,
                    "curr_value": current_views,
                })

        # 2. CTR DROP
        current_ctr = (sum(d.inquiries for d in current_demand) / current_views * 100) if current_views > 0 else 0
        previous_ctr = (sum(d.inquiries for d in previous_demand) / previous_views * 100) if previous_views > 0 else 0

        if previous_ctr > 0 and current_ctr > 0:
            ctr_change = ((current_ctr - previous_ctr) / previous_ctr) * 100
            if ctr_change < -15:
                product_signals.append({
                    "type": "ctr_drop",
                    "severity": "high" if ctr_change < -30 else "medium",
                    "change_percent": round(ctr_change, 1),
                    "prev_value": round(previous_ctr, 1),
                    "curr_value": round(current_ctr, 1),
                })

        # 3. CONVERSION DROP
        current_orders_prod = [o for o in orders if any(line.product_id == product.id for line in o.order_lines) and current_period_start <= o.date <= current_period_end]
        previous_orders_prod = [o for o in orders if any(line.product_id == product.id for line in o.order_lines) and previous_period_start <= o.date <= previous_period_end]

        current_inquiries = sum(d.inquiries for d in current_demand)
        previous_inquiries = sum(d.inquiries for d in previous_demand)

        current_conversion = (len(current_orders_prod) / current_inquiries * 100) if current_inquiries > 0 else 0
        previous_conversion = (len(previous_orders_prod) / previous_inquiries * 100) if previous_inquiries > 0 else 0

        if previous_conversion > 0 and current_conversion > 0:
            conversion_change = ((current_conversion - previous_conversion) / previous_conversion) * 100
            if conversion_change < -20:
                product_signals.append({
                    "type": "conversion_drop",
                    "severity": "critical" if conversion_change < -40 else "high",
                    "change_percent": round(conversion_change, 1),
                    "prev_value": round(previous_conversion, 1),
                    "curr_value": round(current_conversion, 1),
                })

        # 4. RATING DROP
        reviews_for_product = [r for r in product_reviews if r.product_id == product.id]
        if len(reviews_for_product) >= 5:
            recent_reviews = [r for r in reviews_for_product if r.created_at >= thirty_days_ago]
            older_reviews = [r for r in reviews_for_product if r.created_at < thirty_days_ago]

            if recent_reviews and older_reviews:
                recent_avg = sum(r.rating for r in recent_reviews) / len(recent_reviews)
                older_avg = sum(r.rating for r in older_reviews) / len(older_reviews)

                if recent_avg < older_avg - 0.5:
                    product_signals.append({
                        "type": "rating_drop",
                        "severity": "critical" if recent_avg < 3.5 else "high",
                        "change_percent": round((recent_avg - older_avg) / older_avg * 100, 1),
                        "prev_value": round(older_avg, 1),
                        "curr_value": round(recent_avg, 1),
                    })

        if product_signals:
            signals.append({
                "product_id": product.id,
                "product_code": product.id,
                "product_name": product.name,
                "lifecycle": getattr(product, "lifecycle", getattr(product, "lifecycle_status", None)),
                "signals": product_signals,
                "total_severity": sum(1 for s in product_signals if s["severity"] == "critical") * 3 +
                                  sum(1 for s in product_signals if s["severity"] == "high") * 2 +
                                  sum(1 for s in product_signals if s["severity"] == "medium")
            })

    signals.sort(key=lambda x: x["total_severity"], reverse=True)

    total_critical = sum(len([s for s in p["signals"] if s["severity"] == "critical"]) for p in signals)
    total_high = sum(len([s for s in p["signals"] if s["severity"] == "high"]) for p in signals)
    total_medium = sum(len([s for s in p["signals"] if s["severity"] == "medium"]) for p in signals)

    return {
        "signals": signals,
        "summary": {
            "products_affected": len(signals),
            "total_signals": sum(len(p["signals"]) for p in signals),
            "critical_signals": total_critical,
            "high_signals": total_high,
            "medium_signals": total_medium,
            "health_status": "critical" if total_critical > 0 else "warning" if total_high > 2 else "good"
        },
        "period": {
            "current": f"{current_period_start.strftime('%Y-%m-%d')} to {current_period_end.strftime('%Y-%m-%d')}",
            "previous": f"{previous_period_start.strftime('%Y-%m-%d')} to {previous_period_end.strftime('%Y-%m-%d')}"
        }
    }


# --- Issues diagnosis ---------------------------------------------------------

@router.get("/analytics/issues/{product_id}")
async def diagnose_issues(product_id: int):
    product = next((p for p in products if p.id == product_id), None)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    diag_issues = []
    lifecycle = getattr(product, "lifecycle_status", getattr(product, "lifecycle", "idea"))

    # 1. PRODUCT ISSUES
    product_issues = []
    if lifecycle in ["failed", "archived"]:
        product_issues.append("Product lifecycle indicates failure")
    if product.feasibility_score < 50:
        product_issues.append(f"Low feasibility score ({product.feasibility_score}/100)")
    if product.updated_at and (datetime.utcnow() - product.updated_at).days > 90:
        product_issues.append("Product not updated in 90+ days (may look outdated)")

    if product_issues:
        diag_issues.append({
            "category": "product",
            "severity": "high" if lifecycle == "failed" else "medium",
            "problems": product_issues,
            "solutions": [
                "Refresh product design/materials",
                "Add new variants or colors",
                "Research current market trends",
                "Consider discontinuing if can't improve"
            ]
        })

    # 2. PRICE ISSUES
    price_issues = []
    material_cost = sum(
        usage.quantity * next((m.unit_price for m in materials if m.id == usage.material_id), 0)
        for usage in product.materials
    )
    profit_margin = ((product.price - material_cost) / product.price * 100) if product.price > 0 else 0

    if profit_margin < 30:
        price_issues.append(f"Low profit margin ({profit_margin:.1f}% - target >50% for handmade)")

    recent_price_changes = [pc for pc in price_changes if pc.product_id == product.id and (datetime.utcnow() - pc.changed_at).days < 30]
    if recent_price_changes and recent_price_changes[-1].new_price > recent_price_changes[-1].old_price:
        increase_percent = ((recent_price_changes[-1].new_price - recent_price_changes[-1].old_price) / recent_price_changes[-1].old_price) * 100
        if increase_percent > 15:
            price_issues.append(f"Recent price increase of {increase_percent:.1f}% may hurt conversions")

    if price_issues:
        diag_issues.append({
            "category": "price",
            "severity": "high",
            "problems": price_issues,
            "solutions": [
                "Run limited-time promotion to test price sensitivity",
                "Bundle with complementary products",
                "Highlight value proposition (why worth the price)",
                "Optimize material costs to improve margin"
            ]
        })

    # 3. CREATIVE ISSUES
    creative_issues = []
    images_for_product = [img for img in product_images if img.product_id == product.id]
    if len(images_for_product) < 3:
        creative_issues.append(f"Only {len(images_for_product)} images (recommend 5-8)")
    if not any(img.type == "video" for img in images_for_product):
        creative_issues.append("No product video (videos increase conversion 80%)")

    if creative_issues:
        diag_issues.append({
            "category": "creative",
            "severity": "high",
            "problems": creative_issues,
            "solutions": [
                "Add lifestyle images showing product in use",
                "Create 15-30s product video",
                "Add size comparison images",
                "Include close-up detail shots"
            ]
        })

    # 4. TRUST ISSUES
    trust_issues = []
    reviews = [r for r in product_reviews if r.product_id == product.id]
    avg_rating = sum(r.rating for r in reviews) / len(reviews) if reviews else 0

    if len(reviews) < 5:
        trust_issues.append(f"Only {len(reviews)} reviews (need 20+ for trust)")
    if avg_rating < 4.0:
        trust_issues.append(f"Low rating ({avg_rating:.1f}/5.0)")
    if reviews and not any(r.has_image for r in reviews):
        trust_issues.append("No customer photo reviews")

    if trust_issues:
        diag_issues.append({
            "category": "trust",
            "severity": "critical" if avg_rating < 3.5 else "high",
            "problems": trust_issues,
            "solutions": [
                "Send follow-up emails requesting reviews",
                "Offer small discount for photo reviews",
                "Feature customer testimonials prominently",
                "Add money-back guarantee"
            ]
        })

    # 5. SEASONALITY
    seasonal_issues = []
    if product.seasons:
        current_month = datetime.utcnow().month
        in_season = any(s for s in seasons if s.id in product.seasons and s.start_month <= current_month <= s.end_month)
        if not in_season:
            seasonal_issues.append("Currently off-season for this product")

    if seasonal_issues:
        diag_issues.append({
            "category": "seasonality",
            "severity": "low",
            "problems": seasonal_issues,
            "solutions": [
                "Reduce ad spend during off-season",
                "Create content for upcoming season prep",
                "Focus on evergreen complementary products",
                "Plan inventory for next season"
            ]
        })

    # 6. OPERATIONS
    operations_issues = []
    for usage in product.materials:
        material = next((m for m in materials if m.id == usage.material_id), None)
        if material and material.stock_quantity < material.low_threshold:
            operations_issues.append(f"Low stock for {material.name}")

    if operations_issues:
        diag_issues.append({
            "category": "operations",
            "severity": "high",
            "problems": operations_issues,
            "solutions": [
                "Order materials immediately",
                "Set auto-reorder points",
                "Buffer stock for popular items",
                "Update product availability status"
            ]
        })

    severity_weights = {"critical": 10, "high": 5, "medium": 2, "low": 1}
    total_severity = sum(severity_weights.get(issue["severity"], 0) for issue in diag_issues)
    health_score = max(0, 100 - total_severity * 5)

    return {
        "product": {
            "id": product.id,
            "name": product.name,
            "price": getattr(product, "price", getattr(product, "base_price", 0)),
            "lifecycle": lifecycle
        },
        "issues": diag_issues,
        "health_score": health_score,
        "health_status": "excellent" if health_score >= 80 else "good" if health_score >= 60 else "fair" if health_score >= 40 else "poor",
        "summary": {
            "total_issues": len(diag_issues),
            "critical": len([i for i in diag_issues if i["severity"] == "critical"]),
            "high": len([i for i in diag_issues if i["severity"] == "high"]),
            "medium": len([i for i in diag_issues if i["severity"] == "medium"]),
            "low": len([i for i in diag_issues if i["severity"] == "low"])
        }
    }


# --- Funnel analysis ----------------------------------------------------------

@router.get("/analytics/funnel")
async def analyze_funnel(product_id: Optional[int] = None):
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    thirty_days_ago_date = thirty_days_ago.date()

    if product_id:
        product = next((p for p in products if p.id == product_id), None)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        product_demand = [d for d in demand_signals if d.product_id == product_id and d.week_of >= thirty_days_ago_date]
        product_orders = [o for o in orders if any(line.product_id == product_id for line in o.order_lines) and o.date >= thirty_days_ago.date()]

        views = sum(d.views for d in product_demand)
        clicks = sum(d.inquiries for d in product_demand)
        saves = sum(d.saves for d in product_demand)
        purchases = len(product_orders)
        impressions = views * 3

        funnel = [
            {"stage": "impressions", "count": impressions, "rate": 100},
            {"stage": "views", "count": views, "rate": round(views / impressions * 100, 1) if impressions > 0 else 0},
            {"stage": "clicks", "count": clicks, "rate": round(clicks / views * 100, 1) if views > 0 else 0},
            {"stage": "saves", "count": saves, "rate": round(saves / clicks * 100, 1) if clicks > 0 else 0},
            {"stage": "purchases", "count": purchases, "rate": round(purchases / saves * 100, 1) if saves > 0 else 0}
        ]

        biggest_drop = {"stage": None, "drop": 0}
        for i in range(len(funnel) - 1):
            drop = funnel[i]["rate"] - funnel[i + 1]["rate"]
            if drop > biggest_drop["drop"]:
                biggest_drop = {"stage": funnel[i + 1]["stage"], "drop": drop}

        bottleneck_solutions = {
            "views": ["Improve search ranking", "Increase ad spend", "Optimize product title for SEO"],
            "clicks": ["A/B test main image", "Add benefit overlay to thumbnail", "Improve title copy"],
            "saves": ["Strengthen product description", "Add social proof", "Highlight unique value"],
            "purchases": ["Reduce friction in checkout", "Add trust badges", "Offer free shipping", "Create urgency with limited stock"]
        }

        return {
            "product": {"id": product.id, "name": product.name},
            "funnel": funnel,
            "bottleneck": {
                "stage": biggest_drop["stage"],
                "drop_rate": round(biggest_drop["drop"], 1),
                "solutions": bottleneck_solutions.get(biggest_drop["stage"], [])
            },
            "overall_conversion": round(purchases / impressions * 100, 2) if impressions > 0 else 0
        }
    else:
        all_demand = [d for d in demand_signals if d.week_of >= thirty_days_ago_date]
        all_orders = [o for o in orders if o.date >= thirty_days_ago.date()]

        total_views = sum(d.views for d in all_demand)
        total_clicks = sum(d.inquiries for d in all_demand)
        total_saves = sum(d.saves for d in all_demand)
        total_purchases = len(all_orders)
        total_impressions = total_views * 3

        funnel = [
            {"stage": "impressions", "count": total_impressions, "rate": 100},
            {"stage": "views", "count": total_views, "rate": round(total_views / total_impressions * 100, 1) if total_impressions > 0 else 0},
            {"stage": "clicks", "count": total_clicks, "rate": round(total_clicks / total_views * 100, 1) if total_views > 0 else 0},
            {"stage": "saves", "count": total_saves, "rate": round(total_saves / total_clicks * 100, 1) if total_clicks > 0 else 0},
            {"stage": "purchases", "count": total_purchases, "rate": round(total_purchases / total_saves * 100, 1) if total_saves > 0 else 0}
        ]

        return {
            "funnel": funnel,
            "overall_conversion": round(total_purchases / total_impressions * 100, 2) if total_impressions > 0 else 0,
            "period": "last_30_days"
        }


# --- Market benchmark ---------------------------------------------------------

@router.get("/analytics/market-benchmark/{product_id}")
async def get_market_benchmark(product_id: int):
    product = next((p for p in products if p.id == product_id), None)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    similar_products = [p for p in products if p.id != product_id and (
        p.lifecycle_status == product.lifecycle_status or
        any(s in product.seasons for s in p.seasons) if product.seasons and p.seasons else False
    )][:5]

    all_active_products = [p for p in products if p.lifecycle_status in ["live", "experiment"]] or products[:]

    if not all_active_products:
        raise HTTPException(status_code=404, detail="No active products for comparison")

    market_avg_price = sum(p.price for p in all_active_products) / len(all_active_products)

    product_reviews_count = len([r for r in product_reviews if r.product_id == product.id])
    market_avg_reviews = sum(len([r for r in product_reviews if r.product_id == p.id]) for p in all_active_products) / len(all_active_products)

    product_ratings = [r.rating for r in product_reviews if r.product_id == product.id]
    product_avg_rating = sum(product_ratings) / len(product_ratings) if product_ratings else 0

    market_ratings = []
    for p in all_active_products:
        p_ratings = [r.rating for r in product_reviews if r.product_id == p.id]
        if p_ratings:
            market_ratings.append(sum(p_ratings) / len(p_ratings))
    market_avg_rating = sum(market_ratings) / len(market_ratings) if market_ratings else 0

    product_images_count = len([img for img in product_images if img.product_id == product.id])
    market_avg_images = sum(len([img for img in product_images if img.product_id == p.id]) for p in all_active_products) / len(all_active_products)

    product_material_cost = sum(
        usage.quantity * next((m.unit_price for m in materials if m.id == usage.material_id), 0)
        for usage in product.materials
    )
    product_profit_margin = ((product.price - product_material_cost) / product.price * 100) if product.price > 0 else 0

    market_margins = []
    for p in all_active_products:
        p_cost = sum(
            usage.quantity * next((m.unit_price for m in materials if m.id == usage.material_id), 0)
            for usage in p.materials
        )
        if p.price > 0:
            market_margins.append((p.price - p_cost) / p.price * 100)
    market_avg_margin = sum(market_margins) / len(market_margins) if market_margins else 0

    positioning = {
        "price": "premium" if product.price > market_avg_price * 1.2 else "competitive" if product.price > market_avg_price * 0.8 else "budget",
        "quality": "high" if product_avg_rating > market_avg_rating + 0.3 else "average" if product_avg_rating > market_avg_rating - 0.3 else "low",
        "trust": "high" if product_reviews_count > market_avg_reviews * 1.5 else "average" if product_reviews_count > market_avg_reviews * 0.5 else "low",
        "content_quality": "high" if product_images_count >= market_avg_images else "low"
    }

    insights = []

    price_diff_percent = ((product.price - market_avg_price) / market_avg_price * 100) if market_avg_price > 0 else 0
    if abs(price_diff_percent) > 20:
        if price_diff_percent > 0:
            insights.append({
                "category": "pricing",
                "type": "warning",
                "message": f"Price {price_diff_percent:.1f}% higher than market average",
                "recommendation": "Justify premium pricing with superior quality/story, or consider lowering price to improve conversion"
            })
        else:
            insights.append({
                "category": "pricing",
                "type": "opportunity",
                "message": f"Price {abs(price_diff_percent):.1f}% lower than market average",
                "recommendation": "Opportunity to increase price gradually or position as budget-friendly option"
            })

    if product_avg_rating < market_avg_rating - 0.5:
        insights.append({
            "category": "quality",
            "type": "critical",
            "message": f"Rating {product_avg_rating:.1f} vs market {market_avg_rating:.1f}",
            "recommendation": "Critical: Fix quality issues immediately. Survey recent buyers to identify problems"
        })
    elif product_avg_rating > market_avg_rating + 0.5:
        insights.append({
            "category": "quality",
            "type": "success",
            "message": f"Rating {product_avg_rating:.1f} exceeds market {market_avg_rating:.1f}",
            "recommendation": "Leverage high rating in marketing. Feature customer testimonials prominently"
        })

    if product_reviews_count < market_avg_reviews * 0.5:
        insights.append({
            "category": "trust",
            "type": "high",
            "message": f"Only {product_reviews_count} reviews vs market avg {market_avg_reviews:.0f}",
            "recommendation": "Send follow-up emails to request reviews. Offer incentive for photo reviews"
        })

    if product_images_count < market_avg_images:
        insights.append({
            "category": "content",
            "type": "medium",
            "message": f"{product_images_count} images vs market avg {market_avg_images:.1f}",
            "recommendation": "Add more lifestyle images and detail shots. Market leaders have 5-8 images"
        })

    margin_diff = product_profit_margin - market_avg_margin
    if margin_diff < -10:
        insights.append({
            "category": "profitability",
            "type": "warning",
            "message": f"Profit margin {product_profit_margin:.1f}% vs market {market_avg_margin:.1f}%",
            "recommendation": "Optimize material costs or increase price to improve profitability"
        })

    advantages = []
    if positioning["price"] == "budget" and positioning["quality"] != "low":
        advantages.append("Great value proposition: Good quality at low price")
    if positioning["quality"] == "high":
        advantages.append("Superior quality backed by ratings")
    if positioning["trust"] == "high":
        advantages.append("Strong social proof with many reviews")
    if product_profit_margin > 50:
        advantages.append("Healthy profit margins allow for marketing investment")

    weaknesses = []
    if positioning["price"] == "premium" and positioning["quality"] != "high":
        weaknesses.append("High price not justified by quality")
    if positioning["trust"] == "low":
        weaknesses.append("Lack of social proof hurts conversion")
    if positioning["content_quality"] == "low":
        weaknesses.append("Inferior presentation vs competitors")
    if product_profit_margin < 30:
        weaknesses.append("Low margins limit growth potential")

    return {
        "product": {
            "id": product.id,
            "name": product.name,
            "price": product.price,
            "rating": round(product_avg_rating, 2),
            "reviews": product_reviews_count,
            "images": product_images_count,
            "profit_margin": round(product_profit_margin, 1)
        },
        "market_benchmarks": {
            "avg_price": round(market_avg_price, 0),
            "avg_rating": round(market_avg_rating, 2),
            "avg_reviews": round(market_avg_reviews, 1),
            "avg_images": round(market_avg_images, 1),
            "avg_profit_margin": round(market_avg_margin, 1)
        },
        "positioning": positioning,
        "competitive_advantages": advantages,
        "competitive_weaknesses": weaknesses,
        "insights": insights,
        "similar_products": [
            {
                "id": p.id,
                "name": p.name,
                "price": p.price,
                "lifecycle": p.lifecycle_status
            }
            for p in similar_products
        ]
    }


# --- Marketing frameworks -----------------------------------------------------

@router.get("/content/marketing-frameworks")
async def get_marketing_frameworks():
    return {
        "frameworks": {
            "aida": {
                "name": "AIDA (Attention, Interest, Desire, Action)",
                "description": "Classic 4-stage customer journey framework",
                "stages": [
                    {
                        "stage": "attention",
                        "goal": "Stop the scroll, grab eyeballs",
                        "tactics": [
                            "Bold visual: bright colors, contrasting elements",
                            "Pattern interrupt: unexpected image or text",
                            "Curiosity gap: tease without revealing all",
                            "Social proof: '10,000+ sold' badge"
                        ],
                        "examples": [
                            "🔥 Bán chạy nhất tuần!",
                            "Bạn có biết bí mật này?",
                            "Chỉ còn 3 cái cuối cùng!"
                        ]
                    },
                    {
                        "stage": "interest",
                        "goal": "Make them want to know more",
                        "tactics": [
                            "Relate to their pain point",
                            "Show unique solution",
                            "Demonstrate expertise/authority",
                            "Use storytelling"
                        ],
                        "examples": [
                            "Mệt mỏi với túi xách nặng nề?",
                            "Sản phẩm handmade từ chất liệu thiên nhiên...",
                            "Nghệ nhân 20 năm kinh nghiệm"
                        ]
                    },
                    {
                        "stage": "desire",
                        "goal": "Make them WANT it, not just interested",
                        "tactics": [
                            "Paint the transformation (before/after)",
                            "Emotional connection (how it feels to own)",
                            "Social proof (reviews, testimonials)",
                            "Scarcity/exclusivity"
                        ],
                        "examples": [
                            "Hình ảnh bạn tự tin đeo túi đẹp đi làm",
                            "'Tôi cảm thấy sang trọng hơn' - Chị Mai",
                            "Chỉ làm 10 cái mỗi tháng"
                        ]
                    },
                    {
                        "stage": "action",
                        "goal": "Get them to buy NOW",
                        "tactics": [
                            "Clear CTA (Call-to-Action)",
                            "Remove friction (easy checkout)",
                            "Urgency (limited time/stock)",
                            "Risk reversal (guarantee, return policy)"
                        ],
                        "examples": [
                            "Đặt ngay - Miễn phí ship",
                            "Sale kết thúc trong 24h",
                            "Hoàn tiền 100% nếu không hài lòng"
                        ]
                    }
                ],
                "common_mistakes": [
                    "Jump straight to Action without building Desire",
                    "Focus on features (Attention) instead of benefits (Interest)",
                    "Not creating urgency in Action stage"
                ]
            },
            "stp": {
                "name": "STP (Segmentation, Targeting, Positioning)",
                "description": "Strategic marketing framework for finding your niche",
                "stages": [
                    {
                        "stage": "segmentation",
                        "goal": "Divide market into groups",
                        "questions": [
                            "Who are different customer types?",
                            "What are their characteristics?",
                            "Demographics: age, gender, location, income",
                            "Psychographics: values, lifestyle, interests",
                            "Behavioral: usage, loyalty, benefits sought"
                        ],
                        "example": "Túi handmade: (1) Sinh viên trendy (18-25), (2) Công sở chuyên nghiệp (25-40), (3) Mẹ bỉm trẻ em nhỏ"
                    },
                    {
                        "stage": "targeting",
                        "goal": "Choose which segment(s) to focus on",
                        "criteria": [
                            "Size: Đủ lớn để có lợi nhuận?",
                            "Growth: Segment đang tăng hay giảm?",
                            "Competition: Ít cạnh tranh?",
                            "Fit: Phù hợp với năng lực của bạn?"
                        ],
                        "strategies": [
                            "Undifferentiated: Một sản phẩm cho tất cả",
                            "Differentiated: Nhiều sản phẩm cho nhiều segment",
                            "Concentrated: Focus vào 1 segment (niche)"
                        ],
                        "recommendation": "Handmade nên chọn Concentrated (niche) vì nguồn lực hạn chế"
                    },
                    {
                        "stage": "positioning",
                        "goal": "How you want to be perceived in customer's mind",
                        "dimensions": [
                            "Price vs Quality: Premium, Mid-range, Budget",
                            "Functional vs Emotional: Practical vs Lifestyle",
                            "Traditional vs Modern: Classic vs Trendy"
                        ],
                        "positioning_statement": "For [target segment], [brand] is the [category] that [unique benefit] because [reason to believe]",
                        "example": "For eco-conscious millennials, GreenBag is the handmade bag that helps save the planet because we use 100% recycled materials and plant a tree for each purchase"
                    }
                ]
            },
            "hook_story": {
                "name": "Hook & Story Framework",
                "description": "Content structure that captures attention and builds connection",
                "components": [
                    {
                        "element": "hook",
                        "goal": "Stop them in first 3 seconds",
                        "types": [
                            "Question: 'Bạn có biết...?'",
                            "Bold statement: 'Đây là lý do 90% túi handmade thất bại'",
                            "Curiosity: 'Bí mật này đã giúp tôi bán 1000 túi'",
                            "Shocking fact: '80% túi da giả trên thị trường'",
                            "Relatable pain: 'Mệt mỏi với túi rách sau 3 tháng?'"
                        ],
                        "formula": "[Pain/Desire] + [Promise] + [Proof]"
                    },
                    {
                        "element": "story",
                        "goal": "Build emotional connection and trust",
                        "structure": [
                            "Before: Vấn đề/khó khăn/nỗi đau",
                            "Journey: Quá trình tìm kiếm giải pháp",
                            "After: Cuộc sống thay đổi thế nào",
                            "Lesson: Bài học/insight"
                        ],
                        "story_types": [
                            "Founder story: Tại sao bạn bắt đầu",
                            "Customer story: Khách hàng thay đổi thế nào",
                            "Product story: Sản phẩm được tạo ra như thế nào",
                            "Behind-the-scenes: Quy trình sản xuất"
                        ]
                    },
                    {
                        "element": "value",
                        "goal": "Educate and position as expert",
                        "content_types": [
                            "How-to: Cách chọn túi phù hợp",
                            "Tips: 5 cách bảo quản túi da",
                            "Comparison: Da thật vs da PU",
                            "Trend: Xu hướng túi 2025"
                        ]
                    },
                    {
                        "element": "cta",
                        "goal": "Guide next step",
                        "types": [
                            "Soft CTA: 'Tag bạn bè cần biết điều này'",
                            "Engagement: 'Comment \\'YES\\' để nhận catalog'",
                            "Direct: 'Inbox ngay để đặt hàng'",
                            "Link: 'Link in bio để xem thêm'"
                        ]
                    }
                ],
                "content_formula": "Hook (3s) → Story/Value (30-60s) → CTA (5s)"
            }
        },
        "customer_psychology": {
            "principles": [
                {
                    "name": "Fear of Missing Out (FOMO)",
                    "description": "Sự bỏ lỡ cơ hội",
                    "triggers": ["Limited stock", "Time-limited offer", "Exclusive access"],
                    "examples": ["Chỉ còn 3 cái", "Sale kết thúc 23:59 hôm nay", "Chỉ dành cho 100 người đầu"]
                },
                {
                    "name": "Social Proof",
                    "description": "Làm theo đám đông",
                    "triggers": ["Reviews", "Testimonials", "User count", "Influencer endorsement"],
                    "examples": ["1000+ khách hàng hài lòng", "Sản phẩm bán chạy #1", "Được báo chí đưa tin"]
                },
                {
                    "name": "Reciprocity",
                    "description": "Đền đáp khi nhận được",
                    "triggers": ["Free value", "Gifts", "Discounts for loyal customers"],
                    "examples": ["Ebook miễn phí", "Quà tặng khi mua", "Giảm 10% cho lần mua tiếp"]
                },
                {
                    "name": "Authority",
                    "description": "Tin tưởng chuyên gia",
                    "triggers": ["Certifications", "Years of experience", "Press mentions"],
                    "examples": ["Nghệ nhân 20 năm", "Chứng nhận organic", "Feature trên VnExpress"]
                },
                {
                    "name": "Scarcity",
                    "description": "Giá trị tăng khi khan hiếm",
                    "triggers": ["Limited edition", "Low stock", "Exclusive"],
                    "examples": ["Bộ sưu tập giới hạn", "Chỉ làm 50 cái", "Không bán lại"]
                },
                {
                    "name": "Anchoring",
                    "description": "Quyết định dựa trên thông tin đầu tiên",
                    "triggers": ["Original price shown", "Most popular option highlighted"],
                    "examples": ["Giá gốc 500k, giảm còn 350k", "Best seller (định hướng lựa chọn)"]
                }
            ],
            "buying_psychology": {
                "what_customers_fear": [
                    "Mua sai → waste money",
                    "Chất lượng kém → disappointment",
                    "Không đẹp như ảnh → regret",
                    "Giao hàng lâu → frustration"
                ],
                "what_customers_want": [
                    "Feel good về purchase",
                    "Được công nhận/khen ngợi",
                    "Giải quyết vấn đề thực tế",
                    "Experience tốt (unboxing, service)"
                ],
                "decision_process": [
                    "Buy with emotion (cảm xúc: đẹp, sang, độc đáo)",
                    "Justify with logic (lý trí: giá hợp lý, chất lượng tốt, đánh giá cao)"
                ]
            }
        },
        "content_templates": [
            {
                "type": "product_launch",
                "template": "[Hook: New arrival 🔥] → [Story: Behind the design] → [Benefits: 3 lý do phải có] → [CTA: Pre-order now]"
            },
            {
                "type": "customer_testimonial",
                "template": "[Hook: Real customer story] → [Before: Problem they had] → [After: How product helped] → [CTA: Your turn]"
            },
            {
                "type": "educational",
                "template": "[Hook: Did you know?] → [Value: Teach something useful] → [Connect to product] → [Soft CTA]"
            },
            {
                "type": "urgency",
                "template": "[Hook: Time-sensitive] → [Scarcity: Limited stock/time] → [Social proof: Others buying] → [Direct CTA]"
            }
        ]
    }
