"""Dashboard routes - Analytics and reports."""
from typing import Optional
from datetime import date, timedelta
from fastapi import APIRouter, Depends, Query

from models.user import User
from services.auth import get_current_user
from services.order import compute_order_totals
from services.material import get_low_stock_alerts

router = APIRouter()

orders = []
products = []
materials = []
customers = []
tasks = []
purchase_orders = []
_expenses = []
_seasons = []
_goals = []


def set_data_stores(o, p, m, c, t, po=None, exp=None, seasons=None, goals=None):
    global orders, products, materials, customers, tasks, purchase_orders, _expenses, _seasons, _goals
    orders = o
    products = p
    materials = m
    customers = c
    tasks = t
    purchase_orders = po or []
    _expenses = exp or []
    _seasons = seasons or []
    _goals = goals or []


def _revenue_trend(period_orders, start_date, end_date):
    """Daily revenue for every day in the range."""
    daily = {}
    for o in period_orders:
        key = o.date.isoformat()
        totals = compute_order_totals(o)
        if key not in daily:
            daily[key] = {"date": key, "revenue": 0, "orders": 0}
        daily[key]["revenue"] += totals["revenue"]
        daily[key]["orders"] += 1

    result = []
    cur = start_date
    while cur <= end_date:
        key = cur.isoformat()
        result.append(daily.get(key, {"date": key, "revenue": 0, "orders": 0}))
        cur += timedelta(days=1)
    return result


def _top_products(period_orders, limit=10):
    product_map = {p.id: p for p in products}
    agg = {}
    for o in period_orders:
        for line in o.order_lines:
            pid = line.product_id
            if pid not in agg:
                agg[pid] = {"product_id": pid, "units_sold": 0, "revenue": 0}
            agg[pid]["units_sold"] += line.quantity
            agg[pid]["revenue"] += line.unit_price * line.quantity

    result = []
    for pid, data in agg.items():
        p = product_map.get(pid)
        result.append({
            **data,
            "product_name": p.name if p else f"#{pid}",
            "revenue": round(data["revenue"], 2),
        })
    result.sort(key=lambda x: x["units_sold"], reverse=True)
    return result[:limit]


def _channel_performance(period_orders):
    agg = {}
    for o in period_orders:
        ch = o.channel or "direct"
        totals = compute_order_totals(o)
        if ch not in agg:
            agg[ch] = {"channel": ch, "revenue": 0, "count": 0}
        agg[ch]["revenue"] += totals["revenue"]
        agg[ch]["count"] += 1
    result = [{"channel": k, "revenue": round(v["revenue"], 2), "count": v["count"]} for k, v in agg.items()]
    result.sort(key=lambda x: x["revenue"], reverse=True)
    return result


def _cashflow(period_orders, start_date, end_date):
    cash_in = 0
    for o in period_orders:
        if o.status not in ("cancelled",):
            cash_in += compute_order_totals(o)["revenue"]

    # PO spending in period
    purchase_spend = 0
    for po in purchase_orders:
        po_date = getattr(po, "created_at", None)
        if po_date:
            po_d = po_date.date() if hasattr(po_date, "date") else po_date
            if start_date <= po_d <= end_date:
                purchase_spend += getattr(po, "paid_amount", 0) or 0

    operating_expenses = sum(
        e.amount for e in _expenses
        if start_date <= e.date <= end_date
    )
    refunds = 0
    total_out = purchase_spend + operating_expenses
    net_cash = round(cash_in - total_out - refunds, 2)
    return {
        "cash_in": round(cash_in, 2),
        "cash_out": round(total_out, 2),
        "refunds": refunds,
        "purchase_spend": round(purchase_spend, 2),
        "operating_expenses": round(operating_expenses, 2),
        "net_cash": net_cash,
    }


def _material_forecast():
    alerts = get_low_stock_alerts()
    result = []
    for a in alerts:
        current = a.get("stock_quantity", 0)
        threshold = a.get("low_threshold", 10)
        weeks = round(current / threshold * 4, 1) if threshold > 0 else 0
        result.append({
            "material_id": a["material_id"],
            "name": a["name"],
            "code": a.get("code", ""),
            "unit": a["unit"],
            "current_stock": current,
            "low_threshold": threshold,
            "weeks_remaining": weeks,
            "urgency": "critical" if current <= 0 else "high" if current < threshold else "medium",
        })
    result.sort(key=lambda x: x["weeks_remaining"])
    return result


def _inventory_valuation():
    items = []
    for m in materials:
        val = round(m.stock_quantity * m.unit_price, 2)
        items.append({
            "material_id": m.id,
            "name": m.name,
            "quantity": m.stock_quantity,
            "unit": m.unit,
            "unit_price": m.unit_price,
            "total_value": val,
        })
    items.sort(key=lambda x: x["total_value"], reverse=True)
    total = round(sum(i["total_value"] for i in items), 2)
    return {"total_value": total, "items": items}


def _pnl_waterfall(revenue, cost, profit):
    return [
        {"label": "Doanh thu", "value": round(revenue, 2), "type": "income"},
        {"label": "Chi phí NVL", "value": -round(cost, 2), "type": "expense"},
        {"label": "Lợi nhuận gộp", "value": round(profit, 2), "type": "total"},
    ]


def _customer_analytics(period_orders, limit=20):
    customer_map = {c.id: c for c in customers}
    today = date.today()
    agg = {}
    for o in period_orders:
        cid = o.customer_id
        if not cid:
            continue
        totals = compute_order_totals(o)
        if cid not in agg:
            agg[cid] = {"customer_id": cid, "order_count": 0, "revenue": 0, "last_order": None}
        agg[cid]["order_count"] += 1
        agg[cid]["revenue"] += totals["revenue"]
        if agg[cid]["last_order"] is None or o.date > agg[cid]["last_order"]:
            agg[cid]["last_order"] = o.date

    result = []
    for cid, data in agg.items():
        c = customer_map.get(cid)
        result.append({
            **data,
            "name": c.name if c else f"Khách #{cid}",
            "revenue": round(data["revenue"], 2),
            "last_order": data["last_order"].isoformat() if data["last_order"] else None,
        })
    result.sort(key=lambda x: x["revenue"], reverse=True)
    return result[:limit]


def _customer_rfm(all_orders):
    customer_map = {c.id: c for c in customers}
    today = date.today()
    agg = {}
    for o in all_orders:
        cid = o.customer_id
        if not cid:
            continue
        totals = compute_order_totals(o)
        if cid not in agg:
            agg[cid] = {"last_date": o.date, "count": 0, "monetary": 0}
        if o.date > agg[cid]["last_date"]:
            agg[cid]["last_date"] = o.date
        agg[cid]["count"] += 1
        agg[cid]["monetary"] += totals["revenue"]

    result = []
    for cid, data in agg.items():
        c = customer_map.get(cid)
        recency = (today - data["last_date"]).days
        result.append({
            "customer_id": cid,
            "customer_name": c.name if c else f"Khách #{cid}",
            "recency": recency,
            "frequency": data["count"],
            "monetary": round(data["monetary"], 2),
            "rfm_score": round((1 / (max(0, recency) + 1)) * data["count"] * data["monetary"] / 1000, 2),
        })
    return result


def _inventory_treemap(limit=20):
    items = []
    for m in materials:
        val = round(m.stock_quantity * m.unit_price, 2)
        if val > 0:
            items.append({"name": m.name, "value": val, "unit": m.unit})
    items.sort(key=lambda x: x["value"], reverse=True)
    return items[:limit]


def _balance_sheet(cash_in, purchase_spend):
    inventory_value = sum(m.stock_quantity * m.unit_price for m in materials)
    total_assets = round(cash_in + inventory_value, 2)
    liabilities = round(sum(
        max(0, (po.total_amount or 0) - (getattr(po, "paid_amount", 0) or 0))
        for po in purchase_orders
    ), 2)
    equity = round(total_assets - liabilities, 2)
    return {
        "assets": {
            "cash": round(cash_in, 2),
            "inventory": round(inventory_value, 2),
            "total": total_assets,
        },
        "liabilities": liabilities,
        "equity": equity,
    }


def _monthly_pnl(months=6):
    """Revenue vs costs for the last N months (including expenses)."""
    from datetime import date as date_cls
    today = date_cls.today()
    result = {}

    # Build months list (current month last)
    for i in range(months - 1, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        key = f"{y}-{m:02d}"
        result[key] = {"month": key, "revenue": 0, "material_cost": 0, "operating_expense": 0, "net": 0}

    for o in orders:
        key = o.date.strftime("%Y-%m")
        if key not in result:
            continue
        t = compute_order_totals(o)
        result[key]["revenue"] += t["revenue"]
        result[key]["material_cost"] += t["cost"]

    for po in purchase_orders:
        po_date = getattr(po, "created_at", None)
        if not po_date:
            continue
        po_d = po_date.date() if hasattr(po_date, "date") else po_date
        key = po_d.strftime("%Y-%m")
        if key not in result:
            continue
        result[key]["material_cost"] += getattr(po, "paid_amount", 0) or 0

    for e in _expenses:
        key = e.date.strftime("%Y-%m")
        if key not in result:
            continue
        result[key]["operating_expense"] += e.amount

    for v in result.values():
        v["revenue"] = round(v["revenue"], 2)
        v["material_cost"] = round(v["material_cost"], 2)
        v["operating_expense"] = round(v["operating_expense"], 2)
        v["net"] = round(v["revenue"] - v["material_cost"] - v["operating_expense"], 2)

    return list(result.values())


def _top_feasibility(limit=5):
    mat_map = {m.id: m for m in materials}
    result = []
    for p in products:
        if not getattr(p, "materials", None):
            continue
        min_units = float("inf")
        for usage in p.materials:
            mat = mat_map.get(usage.material_id)
            if not mat:
                continue
            avail = getattr(mat, "available_qty", None) or mat.stock_quantity
            max_for = avail / (usage.quantity or 1)
            min_units = min(min_units, max_for)
        feasible = int(min_units) if min_units != float("inf") else 0
        if feasible > 0:
            result.append({
                "product_id": p.id,
                "product_name": p.name,
                "feasible_units": feasible,
                "price": getattr(p, "price", 0),
            })
    result.sort(key=lambda x: x["feasible_units"], reverse=True)
    return result[:limit]


def _upcoming_seasons(days_ahead: int = 60):
    today = date.today()
    result = []
    for s in _seasons:
        try:
            if isinstance(s, dict):
                fd = s.get("from_date") or s.get("start_date")
                td = s.get("to_date") or s.get("end_date")
            else:
                fd = getattr(s, "from_date", None) or getattr(s, "start_date", None)
                td = getattr(s, "to_date", None) or getattr(s, "end_date", None)
            from_date = date.fromisoformat(str(fd)[:10])
            to_date = date.fromisoformat(str(td)[:10])
        except Exception:
            continue
        if from_date <= today + timedelta(days=days_ahead) and to_date >= today:
            result.append({
                "id": s.get("id") if isinstance(s, dict) else getattr(s, "id", None),
                "name": s.get("name") if isinstance(s, dict) else getattr(s, "name", ""),
                "from_date": str(from_date),
                "to_date": str(to_date),
                "from": str(from_date),
                "to": str(to_date),
                "days_until": max(0, (from_date - today).days),
                "active": from_date <= today <= to_date,
            })
    result.sort(key=lambda x: x["days_until"])
    return result


def _compute_goal_current(goal) -> float:
    target_type = getattr(goal, 'target_type', None) or (goal.get('target_type') if isinstance(goal, dict) else 'revenue')
    try:
        start = date.fromisoformat(str(getattr(goal, 'start_date', None) or (goal.get('start_date') if isinstance(goal, dict) else None))[:10])
        end = date.fromisoformat(str(getattr(goal, 'end_date', None) or (goal.get('end_date') if isinstance(goal, dict) else None))[:10])
    except Exception:
        return float(getattr(goal, 'current_value', 0) or (goal.get('current_value', 0) if isinstance(goal, dict) else 0))

    relevant = [
        o for o in orders
        if start <= o.date <= end and getattr(o, 'status', '') not in ('cancelled', 'returned')
    ]
    if target_type == 'revenue':
        return round(sum(compute_order_totals(o)["revenue"] for o in relevant), 2)
    elif target_type == 'orders':
        return float(len(relevant))
    elif target_type == 'customers':
        return float(len({getattr(o, 'customer_id', None) for o in relevant if getattr(o, 'customer_id', None)}))
    return float(getattr(goal, 'current_value', 0) or 0)


def _active_goals():
    today = date.today()
    result = []
    for g in _goals:
        status = getattr(g, 'status', None) or (g.get('status') if isinstance(g, dict) else None)
        if status not in ('active',):
            continue
        try:
            end_date = date.fromisoformat(str(getattr(g, 'end_date', None) or (g.get('end_date') if isinstance(g, dict) else ''))[:10])
        except Exception:
            end_date = None
        d = g.model_dump() if hasattr(g, 'model_dump') else dict(g)
        current = _compute_goal_current(g)
        target = float(d.get('target_value') or 1)
        d['current_value'] = current
        d['progress'] = min(100, round(current / target * 100, 1)) if target > 0 else 0
        d['days_remaining'] = (end_date - today).days if end_date else None
        result.append(d)
    return result


@router.get("")
async def get_dashboard(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    user: User = Depends(get_current_user)
):
    today = date.today()
    if not start_date:
        start_date = today - timedelta(days=30)
    if not end_date:
        end_date = today

    period_orders = [o for o in orders if start_date <= o.date <= end_date]

    total_revenue = 0
    total_cost = 0
    total_profit = 0
    for o in period_orders:
        t = compute_order_totals(o)
        total_revenue += t["revenue"]
        total_cost += t["cost"]
        total_profit += t["profit"]

    status_breakdown = {}
    for o in period_orders:
        status_breakdown[o.status] = status_breakdown.get(o.status, 0) + 1

    low_stock = get_low_stock_alerts()
    pending_tasks = [t for t in tasks if t.status != "done"]

    seven_days_ago = today - timedelta(days=7)
    overdue_orders = [
        {
            "id": o.id,
            "customer_name": f"Khách #{o.customer_id}",
            "expected_date": o.date.isoformat() if hasattr(o.date, "isoformat") else str(o.date),
        }
        for o in orders
        if o.status not in ("done", "shipped", "cancelled")
        and o.date < seven_days_ago
    ]

    cf = _cashflow(period_orders, start_date, end_date)
    valuation = _inventory_valuation()

    return {
        "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "metrics": {
            "total_revenue": round(total_revenue, 2),
            "total_cost": round(total_cost, 2),
            "total_profit": round(total_profit, 2),
            "profit_margin": round(total_profit / total_revenue, 4) if total_revenue else 0,
            "order_count": len(period_orders),
            "total_orders": len(period_orders),
            "customer_count": len(customers),
            "product_count": len(products),
            "avg_order_value": round(total_revenue / len(period_orders), 2) if period_orders else 0,
        },
        "orders": {
            "count": len(period_orders),
            "revenue": round(total_revenue, 2),
            "cost": round(total_cost, 2),
            "profit": round(total_profit, 2),
            "profit_margin": round(total_profit / total_revenue, 4) if total_revenue else 0,
            "by_status": status_breakdown,
        },
        "products": {"total": len(products), "active": len([p for p in products if getattr(p, "is_active", True)])},
        "materials": {"total": len(materials), "low_stock_count": len(low_stock)},
        "customers": {"total": len(customers)},
        "tasks": {"pending": len(pending_tasks)},
        "alerts": {
            "low_stock": low_stock[:5],
            "overdue_orders": overdue_orders[:10],
        },
        # Chart data
        "revenue_trend": _revenue_trend(period_orders, start_date, end_date),
        "top_products": _top_products(period_orders),
        "top_feasibility": _top_feasibility(),
        "channel_performance": _channel_performance(period_orders),
        "order_status": [{"status": k, "count": v} for k, v in status_breakdown.items()],
        "material_forecast": _material_forecast(),
        "inventory_valuation": valuation,
        "inventory_treemap": _inventory_treemap(),
        "pnl": {"revenue": round(total_revenue, 2), "cost": round(total_cost, 2), "profit": round(total_profit, 2)},
        "pnl_waterfall": _pnl_waterfall(total_revenue, total_cost, total_profit),
        "cashflow": cf,
        "balance_sheet": _balance_sheet(cf["cash_in"], cf["purchase_spend"]),
        "customer_analytics": _customer_analytics(period_orders),
        "customer_rfm_scatter": _customer_rfm(orders),
        "monthly_pnl": _monthly_pnl(6),
        "funnel": {},
        "demand_history": [],
        "upcoming_seasons": _upcoming_seasons(),
        "goals": _active_goals(),
        # Raw lists for AI widget context
        "materials_list": [m.model_dump(mode="json") for m in materials],
        "products_list": [p.model_dump(mode="json") for p in products],
    }


@router.get("/summary")
async def get_dashboard_summary(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    user: User = Depends(get_current_user)
):
    return await get_dashboard(start_date, end_date, user)


def _linear_regression(values: list) -> tuple:
    n = len(values)
    if n < 2:
        return 0.0, (values[0] if values else 0.0)
    sum_x = n * (n - 1) / 2
    sum_x2 = n * (n - 1) * (2 * n - 1) / 6
    sum_y = sum(values)
    sum_xy = sum(i * v for i, v in enumerate(values))
    denom = n * sum_x2 - sum_x ** 2
    if denom == 0:
        return 0.0, sum_y / n
    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    return slope, intercept


@router.post("/forecast")
async def get_forecast(
    payload: dict = {},
    user: User = Depends(get_current_user)
):
    today = date.today()
    lookback_days = payload.get("lookback_days", 90)
    forecast_days = payload.get("days", 30)
    start = today - timedelta(days=lookback_days)

    daily_orders: dict = {}
    daily_revenue: dict = {}
    for o in orders:
        if o.date >= start:
            key = (o.date - start).days
            daily_orders[key] = daily_orders.get(key, 0) + 1
            daily_revenue[key] = daily_revenue.get(key, 0.0) + compute_order_totals(o)["revenue"]

    order_series = [daily_orders.get(i, 0) for i in range(lookback_days)]
    revenue_series = [daily_revenue.get(i, 0.0) for i in range(lookback_days)]

    o_slope, o_intercept = _linear_regression(order_series)
    r_slope, r_intercept = _linear_regression(revenue_series)

    forecast_order_total = sum(
        max(0, o_slope * (lookback_days + i) + o_intercept)
        for i in range(forecast_days)
    )
    forecast_revenue_total = sum(
        max(0, r_slope * (lookback_days + i) + r_intercept)
        for i in range(forecast_days)
    )

    daily_avg = sum(order_series) / lookback_days if lookback_days else 0
    revenue_avg = sum(revenue_series) / lookback_days if lookback_days else 0

    return {
        "method": "linear_regression",
        "lookback_days": lookback_days,
        "period_days": forecast_days,
        "trend": {
            "order_slope_per_day": round(o_slope, 4),
            "revenue_slope_per_day": round(r_slope, 2),
        },
        "daily_order_avg": round(daily_avg, 2),
        "daily_revenue_avg": round(revenue_avg, 2),
        "forecast_orders": round(forecast_order_total, 0),
        "forecast_revenue": round(forecast_revenue_total, 2),
    }


@router.get("/revenue-chart")
async def get_revenue_chart(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    group_by: str = "day",
    user: User = Depends(get_current_user)
):
    today = date.today()
    if not start_date:
        start_date = today - timedelta(days=30)
    if not end_date:
        end_date = today

    period_orders = [o for o in orders if start_date <= o.date <= end_date]
    data = {}
    for order in period_orders:
        if group_by == "day":
            key = order.date.isoformat()
        elif group_by == "week":
            key = f"{order.date.year}-W{order.date.isocalendar()[1]:02d}"
        else:
            key = f"{order.date.year}-{order.date.month:02d}"

        if key not in data:
            data[key] = {"revenue": 0, "cost": 0, "profit": 0, "orders": 0}

        totals = compute_order_totals(order)
        data[key]["revenue"] += totals["revenue"]
        data[key]["cost"] += totals["cost"]
        data[key]["profit"] += totals["profit"]
        data[key]["orders"] += 1

    return [{"period": k, **v} for k, v in sorted(data.items())]


@router.get("/top-products")
async def get_top_products(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 10,
    user: User = Depends(get_current_user)
):
    today = date.today()
    if not start_date:
        start_date = today - timedelta(days=30)
    if not end_date:
        end_date = today
    period_orders = [o for o in orders if start_date <= o.date <= end_date]
    return _top_products(period_orders, limit)


@router.get("/top-customers")
async def get_top_customers(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 10,
    user: User = Depends(get_current_user)
):
    today = date.today()
    if not start_date:
        start_date = today - timedelta(days=30)
    if not end_date:
        end_date = today
    period_orders = [o for o in orders if start_date <= o.date <= end_date and o.customer_id]
    return _customer_analytics(period_orders, limit)


@router.get("/business-health")
async def get_business_health(user: User = Depends(get_current_user)):
    today = date.today()
    thirty_days_ago = today - timedelta(days=30)
    sixty_days_ago = today - timedelta(days=60)

    recent_orders = [o for o in orders if o.date >= thirty_days_ago]
    prev_orders = [o for o in orders if sixty_days_ago <= o.date < thirty_days_ago]

    recent_revenue = sum(compute_order_totals(o)["revenue"] for o in recent_orders)
    prev_revenue = sum(compute_order_totals(o)["revenue"] for o in prev_orders)

    revenue_growth = (recent_revenue - prev_revenue) / prev_revenue if prev_revenue else 0
    revenue_score = min(100, max(0, 50 + revenue_growth * 100))

    low_stock_count = len(get_low_stock_alerts())
    total_materials = len(materials)
    inventory_score = 100 - (low_stock_count / total_materials * 100) if total_materials else 100

    completed_orders = len([o for o in recent_orders if o.status in ("done", "shipped")])
    total_recent = len(recent_orders)
    fulfillment_score = (completed_orders / total_recent * 100) if total_recent else 100

    overall_score = revenue_score * 0.4 + inventory_score * 0.3 + fulfillment_score * 0.3

    return {
        "overall_score": round(overall_score, 1),
        "revenue": {
            "score": round(revenue_score, 1),
            "growth": round(revenue_growth * 100, 1),
            "current": round(recent_revenue, 2),
            "previous": round(prev_revenue, 2),
        },
        "inventory": {"score": round(inventory_score, 1), "low_stock_count": low_stock_count},
        "fulfillment": {"score": round(fulfillment_score, 1), "completed": completed_orders, "total": total_recent},
    }
