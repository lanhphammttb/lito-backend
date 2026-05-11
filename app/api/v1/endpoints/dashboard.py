from app.shared import *
from fastapi import APIRouter

router = APIRouter()

@router.get("/dashboard/summary")
async def dashboard_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """Tổng hợp toàn bộ dữ liệu dashboard trong 1 API call duy nhất"""
    # Parse dates
    if start_date and end_date:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    else:
        today = date.today()
        start = date(today.year, today.month, 1)
        end = today

    # Filter orders by date range
    filtered_orders = [o for o in orders if start <= o.date <= end]
    orders_with_totals = [OrderComputed(**o.model_dump(), **compute_order_totals(o)) for o in filtered_orders]

    # Basic metrics
    total_profit = sum(o.profit for o in orders_with_totals)
    total_revenue = sum(o.revenue for o in orders_with_totals)
    total_orders = len(orders_with_totals)

    # Product sales
    product_sales: Dict[int, Dict[str, float]] = {}
    for order in filtered_orders:
        for line in order.order_lines:
            if line.product_id not in product_sales:
                product_sales[line.product_id] = {"units": 0, "revenue": 0, "profit": 0}

            product_sales[line.product_id]["units"] += line.quantity
            product_sales[line.product_id]["revenue"] += line.quantity * line.unit_price

            # Calculate profit for this line
            product = find_product(line.product_id)
            if product:
                cost_info = get_product_cost_cached(product)
                line_profit = (line.unit_price - cost_info.get("cost_per_unit", 0)) * line.quantity
                product_sales[line.product_id]["profit"] += line_profit

    top_products = sorted(
        [{
            "product_id": pid,
            "product_name": find_product(pid).name,
            "units_sold": stats["units"],
            "revenue": stats["revenue"],
            "profit": stats.get("profit", 0)
        } for pid, stats in product_sales.items()],
        key=lambda x: x["units_sold"],
        reverse=True,
    )[:5]

    # Feasibility scores
    top_feasibility = sorted(
        [{
            "product_id": p.id,
            "product_name": p.name,
            "feasibility_score": get_product_cost_cached(p).get("feasibility_score", 0),
            "profit_per_unit": get_product_cost_cached(p).get("profit_per_unit", 0),
            "max_units": get_product_cost_cached(p).get("max_units_from_stock")
        } for p in products],
        key=lambda x: x["feasibility_score"],
        reverse=True,
    )[:5]

    # Alerts
    low_stock = [{"material": m.name, "code": m.code, "stock": m.stock_quantity, "unit": m.unit, "threshold": m.low_threshold}
                 for m in materials if m.stock_quantity <= m.low_threshold]
    overdue_orders = [{"id": o.id, "date": o.date.isoformat(), "customer_name": find_customer(o.customer_id).name if o.customer_id else "N/A", "expected_date": o.date.isoformat()}
                      for o in orders if o.status != "delivered" and (date.today() - o.date).days > 7]

    # Channel performance
    channel_revenue = {}
    for order in filtered_orders:
        ch = order.channel or "direct"
        channel_revenue[ch] = channel_revenue.get(ch, 0) + compute_order_totals(order)["revenue"]

    channels = [{"channel": ch, "revenue": rev} for ch, rev in channel_revenue.items()]
    channels.sort(key=lambda x: x["revenue"], reverse=True)

    # Daily revenue trend (last 30 days for chart)
    daily_revenue = {}
    for order in [o for o in orders if (date.today() - o.date).days <= 30]:
        day_key = order.date.isoformat()
        daily_revenue[day_key] = daily_revenue.get(day_key, 0) + compute_order_totals(order)["revenue"]

    revenue_trend = [{"date": day, "revenue": rev} for day, rev in sorted(daily_revenue.items())]

    # Order status breakdown
    status_counts = {}
    for order in filtered_orders:
        status_counts[order.status] = status_counts.get(order.status, 0) + 1

    order_status = [{"status": status, "count": count} for status, count in status_counts.items()]

    # Material usage forecast
    material_forecast = []
    for material in materials[:10]:  # Top 10 materials
        weekly_usage = sum(
            usage.quantity
            for product in products
            for usage in product.materials
            if usage.material_id == material.id
        )
        weeks_remaining = material.stock_quantity / weekly_usage if weekly_usage > 0 else 999
        material_forecast.append({
            "material": material.name,
            "code": material.code,
            "stock": material.stock_quantity,
            "weeks_remaining": round(weeks_remaining, 1)
        })

    # P&L Report
    gross_revenue = total_revenue
    discount = sum(o.discount or 0 for o in filtered_orders)
    returns = 0  # TODO: track returns
    net_revenue = gross_revenue - discount - returns
    cogs = sum(
        get_product_cost_cached(find_product(line.product_id)).get("cost_per_unit", 0) * line.quantity
        for order in filtered_orders
        for line in order.order_lines
        if find_product(line.product_id)
    )
    shipping_cost = sum(o.shipping_fee or 0 for o in filtered_orders)
    gross_profit = net_revenue - cogs - shipping_cost

    # Inventory valuation
    inventory_value = sum(m.stock_quantity * m.unit_price for m in materials)
    valuation_items = [{
        "material_id": m.id,
        "code": m.code,
        "name": m.name,
        "stock_quantity": m.stock_quantity,
        "unit_price": m.unit_price,
        "value": m.stock_quantity * m.unit_price
    } for m in materials[:20]]

    # Funnel metrics
    total_views = sum(d.views for d in demand_signals)
    total_inquiries = sum(d.inquiries for d in demand_signals)
    total_saves = sum(d.saves for d in demand_signals)
    conv_inquiry = round(total_inquiries / total_views * 100, 2) if total_views > 0 else 0
    conv_order_view = round(total_orders / total_views * 100, 2) if total_views > 0 else 0
    conv_order_inquiry = round(total_orders / total_inquiries * 100, 2) if total_inquiries > 0 else 0

    # Customer analytics (RFM)
    customer_stats = []
    for customer in customers[:10]:
        customer_orders = [o for o in filtered_orders if o.customer_id == customer.id]
        if not customer_orders:
            continue
        total_spent = sum(compute_order_totals(o)["revenue"] for o in customer_orders)
        last_order = max(customer_orders, key=lambda o: o.date)
        recency_days = (date.today() - last_order.date).days
        rfm_score = min(100, (10 - min(recency_days / 30, 10)) * 3 + len(customer_orders) * 2 + total_spent / 1000)
        customer_stats.append({
            "customer_id": customer.id,
            "name": customer.name,
            "source": customer.source or "N/A",
            "total_orders": len(customer_orders),
            "total_spent": round(total_spent, 2),
            "avg_order": round(total_spent / len(customer_orders), 2),
            "recency_days": recency_days,
            "rfm_score": round(rfm_score, 1)
        })

    # Cashflow
    cash_in = total_revenue
    cash_out = cogs + shipping_cost
    refunds = 0  # TODO
    purchase_spend = sum(
        line.quantity * line.unit_price
        for po in purchase_orders
        if po.created_at and start <= po.created_at.date() <= end
        for line in po.lines
    )
    net_cash = cash_in - cash_out - refunds - purchase_spend

    # Balance sheet (simplified)
    cash_balance = net_cash
    assets = {
        "cash": round(cash_balance, 2),
        "inventory": round(inventory_value, 2),
        "total": round(cash_balance + inventory_value, 2)
    }
    liabilities = 0  # TODO
    equity = assets["total"] - liabilities

    # Demand history for chart
    demand_history = []
    for signal in sorted(demand_signals, key=lambda d: d.week_of)[-12:]:
        demand_history.append({
            "week": signal.week_of.strftime("%d/%m") if hasattr(signal.week_of, 'strftime') else str(signal.week_of),
            "views": signal.views,
            "inquiries": signal.inquiries,
            "saves": signal.saves
        })

    # Upcoming seasons
    upcoming_seasons = []
    today = date.today()
    for season in seasons:
        if today <= season.to_date and (season.from_date - today).days <= 60:
            related = [p.name for p in products if season.id in p.seasons]
            upcoming_seasons.append({
                "name": season.name,
                "from": season.from_date.isoformat(),
                "to": season.to_date.isoformat(),
                "products": related
            })

    # Goals tracking
    active_goals = [g for g in goals if g.status == "active" and start <= g.end_date and g.start_date <= end]
    goals_data = []
    for goal in active_goals:
        # Calculate current value based on goal type
        if goal.target_type == "revenue":
            current = total_revenue
        elif goal.target_type == "profit":
            current = total_profit
        elif goal.target_type == "orders":
            current = total_orders
        elif goal.target_type == "customers":
            current = len(set(o.customer_id for o in filtered_orders if o.customer_id))
        else:
            current = goal.current_value

        progress = min(100, (current / goal.target_value * 100) if goal.target_value > 0 else 0)
        goals_data.append({
            "id": goal.id,
            "title": goal.title,
            "target_type": goal.target_type,
            "target_value": round(goal.target_value, 2),
            "current_value": round(current, 2),
            "progress": round(progress, 2),
            "status": "achieved" if current >= goal.target_value else "active",
            "end_date": goal.end_date.isoformat()
        })

    # P&L Waterfall data (for chart)
    pnl_waterfall = [
        {"label": "Gross Revenue", "value": gross_revenue, "type": "total"},
        {"label": "Discount", "value": -discount, "type": "decrease"},
        {"label": "Returns", "value": -returns, "type": "decrease"},
        {"label": "Net Revenue", "value": net_revenue, "type": "total"},
        {"label": "COGS", "value": -cogs, "type": "decrease"},
        {"label": "Shipping", "value": -shipping_cost, "type": "decrease"},
        {"label": "Gross Profit", "value": gross_profit, "type": "total"}
    ]

    # Customer RFM scatter data (for visualization)
    customer_rfm_scatter = [
        {
            "name": c["name"],
            "recency": c["recency_days"],
            "frequency": c["total_orders"],
            "monetary": c["total_spent"],
            "rfm_score": c["rfm_score"]
        }
        for c in customer_stats[:20]
    ]

    # Inventory treemap data
    inventory_treemap = [
        {
            "name": item["name"],
            "value": item["value"],
            "category": item["code"][:2] if len(item["code"]) > 2 else "Other"
        }
        for item in valuation_items[:15]
    ]

    return {
        "period": {"start_date": start.isoformat(), "end_date": end.isoformat()},
        "metrics": {
            "total_profit": round(total_profit, 2),
            "total_revenue": round(total_revenue, 2),
            "total_orders": total_orders,
            "avg_order_value": round(total_revenue / total_orders, 2) if total_orders > 0 else 0,
        },
        "top_products": top_products,
        "top_feasibility": top_feasibility,
        "alerts": {
            "low_stock": low_stock[:5],
            "overdue_orders": overdue_orders[:5],
        },
        "channel_performance": channels,
        "revenue_trend": revenue_trend,
        "order_status": order_status,
        "material_forecast": material_forecast,
        "pnl": {
            "gross_revenue": round(gross_revenue, 2),
            "discount": round(discount, 2),
            "returns": round(returns, 2),
            "net_revenue": round(net_revenue, 2),
            "cogs": round(cogs, 2),
            "shipping_cost": round(shipping_cost, 2),
            "gross_profit": round(gross_profit, 2),
        },
        "pnl_waterfall": pnl_waterfall,
        "inventory_valuation": {
            "total_value": round(inventory_value, 2),
            "items": valuation_items
        },
        "inventory_treemap": inventory_treemap,
        "funnel": {
            "views": total_views,
            "inquiries": total_inquiries,
            "orders": total_orders,
            "saves": total_saves,
            "conv_inquiry": conv_inquiry,
            "conv_order_view": conv_order_view,
            "conv_order_inquiry": conv_order_inquiry
        },
        "customer_analytics": customer_stats,
        "customer_rfm_scatter": customer_rfm_scatter,
        "cashflow": {
            "cash_in": round(cash_in, 2),
            "cash_out": round(cash_out, 2),
            "refunds": round(refunds, 2),
            "purchase_spend": round(purchase_spend, 2),
            "net_cash": round(net_cash, 2)
        },
        "balance_sheet": {
            "assets": assets,
            "liabilities": round(liabilities, 2),
            "equity": round(equity, 2)
        },
        "demand_history": demand_history,
        "upcoming_seasons": upcoming_seasons,
        "goals": goals_data
    }



@router.post("/dashboard/forecast", response_model=ForecastResponse)
async def revenue_forecast(
    request: ForecastRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Dự báo doanh thu sử dụng Simple Linear Regression.
    - Tính toán trend từ dữ liệu lịch sử
    - Dự báo cho N kỳ tiếp theo
    - Trả về độ tin cậy và chỉ số thống kê
    """
    from datetime import timedelta

    now = datetime.now()

    # Xác định khoảng thời gian theo period_type
    if request.period_type == "day":
        delta = timedelta(days=1)
        history_periods = 90  # 90 ngày gần nhất
        date_format = "%Y-%m-%d"
    elif request.period_type == "week":
        delta = timedelta(weeks=1)
        history_periods = 52  # 52 tuần
        date_format = "%Y-W%W"
    else:  # month
        delta = timedelta(days=30)
        history_periods = 24  # 24 tháng
        date_format = "%Y-%m"

    # Thu thập dữ liệu lịch sử
    historical_data = []

    for i in range(history_periods, 0, -1):
        if request.period_type == "month":
            # Tính theo tháng thực
            year = now.year
            month = now.month - i
            while month <= 0:
                month += 12
                year -= 1
            start_date = datetime(year, month, 1)
            if month == 12:
                end_date = datetime(year + 1, 1, 1)
            else:
                end_date = datetime(year, month + 1, 1)
            period_label = start_date.strftime("%Y-%m")
        elif request.period_type == "week":
            start_date = now - timedelta(weeks=i)
            start_date = start_date - timedelta(days=start_date.weekday())  # Monday
            end_date = start_date + timedelta(weeks=1)
            period_label = start_date.strftime("%Y-W%W")
        else:  # day
            start_date = now - timedelta(days=i)
            start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = start_date + timedelta(days=1)
            period_label = start_date.strftime("%Y-%m-%d")

        # Tính doanh thu trong kỳ
        period_revenue = 0
        period_orders = 0
        for order in orders:
            order_dt = (
                order.date
                if isinstance(order.date, datetime)
                else datetime.combine(order.date, datetime.min.time()) if hasattr(order.date, 'year') else datetime.fromisoformat(str(order.date))
            )
            if start_date <= order_dt < end_date:
                totals = compute_order_totals(order)
                period_revenue += totals["revenue"]
                period_orders += 1

        historical_data.append({
            "period": period_label,
            "revenue": round(period_revenue, 2),
            "orders": period_orders
        })

    # Lọc bỏ các kỳ không có dữ liệu ở đầu
    while historical_data and historical_data[0]["revenue"] == 0 and historical_data[0]["orders"] == 0:
        historical_data.pop(0)

    # Simple Linear Regression
    n = len(historical_data)
    if n < 3:
        # Không đủ dữ liệu
        return ForecastResponse(
            historical=historical_data,
            forecast=[],
            metrics={"error": "Not enough historical data"},
            trend="unknown",
            confidence=0.0
        )

    # Chuẩn bị dữ liệu cho regression
    x = list(range(n))  # [0, 1, 2, ..., n-1]
    y = [d["revenue"] for d in historical_data]

    # Tính mean
    x_mean = sum(x) / n
    y_mean = sum(y) / n

    # Tính slope (beta) và intercept (alpha)
    numerator = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
    denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

    if denominator == 0:
        slope = 0
        intercept = y_mean
    else:
        slope = numerator / denominator
        intercept = y_mean - slope * x_mean

    # Tính R-squared (coefficient of determination)
    ss_tot = sum((y[i] - y_mean) ** 2 for i in range(n))
    y_pred = [slope * x[i] + intercept for i in range(n)]
    ss_res = sum((y[i] - y_pred[i]) ** 2 for i in range(n))

    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
    r_squared = max(0, min(1, r_squared))  # Clamp to [0, 1]

    # Dự báo cho các kỳ tiếp theo
    forecast_data = []
    for i in range(request.periods):
        future_x = n + i
        predicted_revenue = slope * future_x + intercept
        predicted_revenue = max(0, predicted_revenue)  # Không âm

        # Tính label cho kỳ dự báo
        if request.period_type == "month":
            year = now.year
            month = now.month + i + 1
            while month > 12:
                month -= 12
                year += 1
            period_label = f"{year}-{month:02d}"
        elif request.period_type == "week":
            future_date = now + timedelta(weeks=i+1)
            period_label = future_date.strftime("%Y-W%W")
        else:
            future_date = now + timedelta(days=i+1)
            period_label = future_date.strftime("%Y-%m-%d")

        # Tính khoảng tin cậy (±20% dựa trên variance)
        std_error = (ss_res / (n - 2)) ** 0.5 if n > 2 else 0
        margin = 1.96 * std_error * ((1 + 1/n + (future_x - x_mean)**2 / denominator) ** 0.5) if denominator > 0 else predicted_revenue * 0.2

        forecast_data.append({
            "period": period_label,
            "predicted_revenue": round(predicted_revenue, 2),
            "lower_bound": round(max(0, predicted_revenue - margin), 2),
            "upper_bound": round(predicted_revenue + margin, 2)
        })

    # Xác định trend
    if slope > 0.01 * y_mean:
        trend = "increasing"
    elif slope < -0.01 * y_mean:
        trend = "decreasing"
    else:
        trend = "stable"

    # Tính các metrics bổ sung
    avg_revenue = y_mean
    growth_rate = (slope / y_mean * 100) if y_mean > 0 else 0

    return ForecastResponse(
        historical=historical_data[-12:],  # Chỉ trả về 12 kỳ gần nhất
        forecast=forecast_data,
        metrics={
            "slope": round(slope, 2),
            "intercept": round(intercept, 2),
            "r_squared": round(r_squared, 4),
            "avg_revenue": round(avg_revenue, 2),
            "growth_rate_per_period": round(growth_rate, 2),
            "total_historical_periods": n
        },
        trend=trend,
        confidence=round(r_squared * 100, 1)  # Confidence as percentage
    )

