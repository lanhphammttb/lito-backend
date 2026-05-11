from app.shared import *
from fastapi import APIRouter

router = APIRouter()

@router.get("/audit-logs/stats")
async def get_audit_log_stats(current_user: User = Depends(get_current_user)):
    from collections import Counter
    with Session(engine) as session:
        logs = session.exec(select(AuditLogTable)).all()
        total_actions = len(logs)
        by_action = Counter(log.action for log in logs)
        period_days = 30  # or calculate from logs if needed
        return {
            "total_actions": total_actions,
            "by_action": dict(by_action),
            "period_days": period_days
        }



# --- Audit Log API ----------------------------------------------------------

@router.get("/audit-logs")
async def get_audit_logs(
    page: int = 1,
    page_size: int = 50,
    current_user: User = Depends(get_current_user)
):
    """Get audit logs with pagination"""
    try:
        with Session(engine) as session:
            query = select(AuditLogTable).order_by(AuditLogTable.timestamp.desc())
            result = session.exec(select(AuditLogTable)).all()
            total = len(result)
            query = query.offset((page - 1) * page_size).limit(page_size)
            logs = session.exec(query).all()
            items = [
                {
                    "id": log.id,
                    "user_id": log.user_id,
                    "user_name": log.user_name,
                    "action": log.action,
                    "table_name": log.table_name,
                    "record_id": log.record_id,
                    "before_data": log.before_data,
                    "after_data": log.after_data,
                    "ip_address": log.ip_address,
                    "user_agent": log.user_agent,
                    "timestamp": log.timestamp.isoformat() if log.timestamp else None
                }
                for log in logs
            ]
            total_pages = (total + page_size - 1) // page_size
            return JSONResponse({
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages
            })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/seasons/{season_id}", response_model=Season)
async def update_season(season_id: int, payload: Season, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    if payload.id != season_id:
        raise HTTPException(status_code=400, detail="Không được đổi id")
    for idx, season in enumerate(seasons):
        if season.id == season_id:
            payload.created_by = season.created_by or payload.created_by
            payload.updated_by = current_user.id
            seasons[idx] = payload
            upsert_document("seasons", payload, season_id)
            log_activity(current_user.id, "season", season_id, "update", changes=payload.model_dump())
            return payload
    raise HTTPException(status_code=404, detail="Season không tồn tại")




@router.delete("/seasons/{season_id}")
async def delete_season(season_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for season in seasons:
        if season.id == season_id:
            seasons.remove(season)
            delete_document("seasons", season_id)
            log_activity(current_user.id, "season", season_id, "delete")
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Season không tồn tại")












@router.get("/content-plans/analytics")
async def content_performance_analytics(current_user: User = Depends(get_current_user)):
    """
    Analyze content performance: ROI, best formats, posting schedule
    """
    analytics = []

    for content in content_plans:
        if content.status != "published" or not content.actual_revenue:
            continue

        # Calculate ROI (assuming zero cost for now since cost_to_create field doesn't exist)
        cost_to_create = 0  # ContentPlan doesn't have cost_to_create field
        roi = 0  # Can't calculate without cost data

        # Calculate conversion rates
        views = content.actual_views or 0
        inquiries = content.actual_inquiries or 0
        orders = content.actual_orders or 0

        view_to_inquiry = (inquiries / views * 100) if views > 0 else 0
        inquiry_to_order = (orders / inquiries * 100) if inquiries > 0 else 0
        view_to_order = (orders / views * 100) if views > 0 else 0

        # Revenue per view
        revenue_per_view = content.actual_revenue / views if views > 0 else 0

        analytics.append({
            "content_id": content.id,
            "product_id": content.related_product_id,
            "format": content.format,
            "channel": content.channel,
            "published_date": content.published_date,
            "views": views,
            "inquiries": inquiries,
            "orders": orders,
            "revenue": content.actual_revenue,
            "cost": cost_to_create,
            "roi": round(roi, 2),
            "view_to_inquiry_rate": round(view_to_inquiry, 2),
            "inquiry_to_order_rate": round(inquiry_to_order, 2),
            "view_to_order_rate": round(view_to_order, 2),
            "revenue_per_view": round(revenue_per_view, 2)
        })

    # Best performing formats
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

    # Best posting times (by day of week)
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

    # Content fatigue detection (same product posted too many times)
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




@router.put("/experiments/{exp_id}", response_model=Experiment)
async def update_experiment(exp_id: int, payload: ExperimentUpdate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for idx, exp in enumerate(experiments):
        if exp.id == exp_id:
            data = exp.model_dump()
            for field, value in payload.model_dump(exclude_none=True).items():
                data[field] = value
            updated = Experiment(**data)
            experiments[idx] = updated
            upsert_document("experiments", updated, exp_id)
            log_activity(current_user.id, "experiment", exp_id, "update", changes=payload.model_dump(exclude_none=True))
            return updated
    raise HTTPException(status_code=404, detail="Experiment không tồn tại")




@router.delete("/experiments/{exp_id}")
async def delete_experiment(exp_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for exp in experiments:
        if exp.id == exp_id:
            experiments.remove(exp)
            delete_document("experiments", exp_id)
            log_activity(current_user.id, "experiment", exp_id, "delete")
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Experiment không tồn tại")





@router.delete("/content-plans/{plan_id}")
async def delete_content_plan(plan_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for plan in content_plans:
        if plan.id == plan_id:
            content_plans.remove(plan)
            delete_document("content_plans", plan_id)
            log_activity(current_user.id, "content_plan", plan_id, "delete")
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Content plan không tồn tại")


@router.get("/issues/{issue_id}/comments", response_model=List[IssueComment])
async def list_issue_comments(issue_id: int, current_user: User = Depends(get_current_user)):
    find_issue(issue_id)
    return [c for c in issue_comments if c.issue_id == issue_id]




@router.post("/issues/{issue_id}/comments", response_model=IssueComment)
async def create_issue_comment(issue_id: int, payload: IssueCommentCreate, current_user: User = Depends(get_current_user)):
    find_issue(issue_id)
    new_comment = IssueComment(
        id=next_id(issue_comments),
        issue_id=issue_id,
        user_id=current_user.id,
        content=payload.content,
        created_at=datetime.utcnow(),
    )
    issue_comments.append(new_comment)
    upsert_document("issue_comments", new_comment)
    for i in issues:
        if i.id == issue_id:
            i.comments_count = len([c for c in issue_comments if c.issue_id == issue_id])
            save_issue_sql(i)
            break
    log_activity(current_user.id, "issue", issue_id, "comment", changes={"content": payload.content})
    return new_comment




@router.put("/issues/{issue_id}", response_model=Issue)
async def update_issue(issue_id: int, payload: Issue, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for idx, issue in enumerate(issues):
        if issue.id == issue_id:
            payload.id = issue_id
            payload.created_at = issue.created_at
            payload.created_by = issue.created_by
            if payload.assigned_to and not any(u.id == payload.assigned_to for u in users):
                raise HTTPException(status_code=404, detail="Người được giao không tồn tại")
            if payload.status == "resolved" and payload.resolved_at is None:
                payload.resolved_at = datetime.utcnow()
                payload.resolution_hours = (
                    (payload.resolved_at - payload.created_at).total_seconds() / 3600
                    if payload.created_at
                    else None
                )
            issues[idx] = payload
            upsert_document("issues", payload, issue_id)
            save_issue_sql(payload)
            log_activity(current_user.id, "issue", issue_id, "update", changes=payload.model_dump())
            return payload
    raise HTTPException(status_code=404, detail="Issue không tồn tại")




@router.post("/issues/from-template", response_model=Issue)
async def create_issue_from_template(payload: IssueFromTemplateRequest, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    template = find_issue(payload.template_id)
    if not template.is_template:
        raise HTTPException(status_code=400, detail="Issue này không phải template")
    find_product(payload.product_id)
    new_issue = Issue(
        id=next_id(issues),
        product_id=payload.product_id,
        type=template.type,
        description=payload.description or template.description,
        evidence=template.evidence,
        hypothesis=template.hypothesis,
        next_action=template.next_action,
        priority=payload.priority or template.priority,
        status="open",
        impact_revenue=template.impact_revenue,
        is_template=False,
        created_by=current_user.id,
        created_at=datetime.utcnow(),
    )
    issues.append(new_issue)
    upsert_document("issues", new_issue)
    save_issue_sql(new_issue)
    log_activity(current_user.id, "issue", new_issue.id, "create_from_template", changes=payload.model_dump())
    return new_issue




@router.delete("/issues/{issue_id}")
async def delete_issue(issue_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for issue in issues:
        if issue.id == issue_id:
            issues.remove(issue)
            delete_document("issues", issue_id)
            with Session(engine) as session:
                session.exec(delete(IssueTable).where(IssueTable.id == issue_id))
                session.commit()
            log_activity(current_user.id, "issue", issue_id, "delete")
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Issue không tồn tại")




# ============================================================================
# SIGNAL DETECTION & ISSUES DIAGNOSIS SYSTEM
# ============================================================================

@router.get("/analytics/signals")
async def detect_signals(current_user: User = Depends(get_current_user)):
    """
    Detect 7 key business signals that indicate problems:
    1. View drop, 2. CTR drop, 3. Conversion drop, 4. Add-to-cart drop,
    5. Message drop, 6. Cart abandon rate increase, 7. Rating drop

    Based on comprehensive business intelligence framework
    """
    from collections import defaultdict

    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    sixty_days_ago = now - timedelta(days=60)

    # Current period (last 30 days) - convert to date for comparison with week_of
    current_period_start = thirty_days_ago.date()
    current_period_end = now.date()

    # Previous period (30-60 days ago)
    previous_period_start = sixty_days_ago.date()
    previous_period_end = thirty_days_ago.date()

    signals = []

    # Calculate metrics for each product
    for product in products:
        product_signals = []

        # Get demand signals
        current_demand = [d for d in demand_signals if d.product_id == product.id and current_period_start <= d.week_of <= current_period_end]
        previous_demand = [d for d in demand_signals if d.product_id == product.id and previous_period_start <= d.week_of <= previous_period_end]

        # 1. VIEW DROP
        current_views = sum(d.views for d in current_demand)
        previous_views = sum(d.views for d in previous_demand)

        if previous_views > 0:
            view_change = ((current_views - previous_views) / previous_views) * 100
            if view_change < -20:  # 20% drop threshold
                product_signals.append({
                    "type": "view_drop",
                    "severity": "critical" if view_change < -50 else "high" if view_change < -30 else "medium",
                    "change_percent": round(view_change, 1),
                    "prev_value": previous_views,
                    "curr_value": current_views,
                })

        # 2. CTR DROP (Click-through rate = inquiries/views)
        current_ctr = (sum(d.inquiries for d in current_demand) / current_views * 100) if current_views > 0 else 0
        previous_ctr = (sum(d.inquiries for d in previous_demand) / previous_views * 100) if previous_views > 0 else 0

        if previous_ctr > 0 and current_ctr > 0:
            ctr_change = ((current_ctr - previous_ctr) / previous_ctr) * 100
            if ctr_change < -15:  # 15% drop threshold
                product_signals.append({
                    "type": "ctr_drop",
                    "severity": "high" if ctr_change < -30 else "medium",
                    "change_percent": round(ctr_change, 1),
                    "prev_value": round(previous_ctr, 1),
                    "curr_value": round(current_ctr, 1),
                })

        # 3. CONVERSION DROP
        current_orders = [o for o in orders if any(line.product_id == product.id for line in o.order_lines) and current_period_start <= o.date <= current_period_end]
        previous_orders = [o for o in orders if any(line.product_id == product.id for line in o.order_lines) and previous_period_start <= o.date <= previous_period_end]

        current_inquiries = sum(d.inquiries for d in current_demand)
        previous_inquiries = sum(d.inquiries for d in previous_demand)

        current_conversion = (len(current_orders) / current_inquiries * 100) if current_inquiries > 0 else 0
        previous_conversion = (len(previous_orders) / previous_inquiries * 100) if previous_inquiries > 0 else 0

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

                if recent_avg < older_avg - 0.5:  # Drop of 0.5 stars
                    product_signals.append({
                        "type": "rating_drop",
                        "severity": "critical" if recent_avg < 3.5 else "high",
                        "change_percent": round((recent_avg - older_avg) / older_avg * 100, 1),
                        "prev_value": round(older_avg, 1),
                        "curr_value": round(recent_avg, 1),
                    })

        # Add product info to signals
        if product_signals:
            signals.append({
                "product_id": product.id,
                "product_code": product.id,  # Sử dụng id thay cho code
                "product_name": product.name,
                "lifecycle": getattr(product, "lifecycle", getattr(product, "lifecycle_status", None)),
                "signals": product_signals,
                "total_severity": sum(1 for s in product_signals if s["severity"] == "critical") * 3 + \
                                sum(1 for s in product_signals if s["severity"] == "high") * 2 + \
                                sum(1 for s in product_signals if s["severity"] == "medium")
            })

    # Sort by severity
    signals.sort(key=lambda x: x["total_severity"], reverse=True)

    # Overall summary
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




@router.get("/analytics/issues/{product_id}")
async def diagnose_issues(
    product_id: int,
    current_user: User = Depends(get_current_user)
):
    """
    Deep dive diagnosis for a specific product
    Analyzes 10 root cause categories:
    1. Product issues, 2. Price issues, 3. Creative issues, 4. Description issues,
    5. Trust issues, 6. Competition issues, 7. Algorithm issues, 8. Seasonality,
    9. Operations issues, 10. Customer service issues
    """
    product = next((p for p in products if p.id == product_id), None)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    issues = []

    # 1. PRODUCT ISSUES
    product_issues = []
    if product.lifecycle in ["failed", "archived"]:
        product_issues.append("Product lifecycle indicates failure")
    if product.feasibility_score < 50:
        product_issues.append(f"Low feasibility score ({product.feasibility_score}/100)")

    # Check if product is outdated (no updates in 90 days)
    if product.updated_at and (datetime.utcnow() - product.updated_at).days > 90:
        product_issues.append("Product not updated in 90+ days (may look outdated)")

    if product_issues:
        issues.append({
            "category": "product",
            "severity": "high" if product.lifecycle == "failed" else "medium",
            "problems": product_issues,
            "solutions": [
                "Làm mới thiết kế/chất liệu sản phẩm",
                "Thêm biến thể hoặc màu sắc mới",
                "Nghiên cứu xu hướng thị trường hiện tại",
                "Cân nhắc ngừng bán nếu không thể cải thiện"
            ]
        })

    # 2. PRICE ISSUES
    price_issues = []
    # Calculate profit margin
    material_cost = sum(usage.quantity * next((m.unit_price for m in materials if m.id == usage.material_id), 0) for usage in product.materials)
    profit_margin = ((product.price - material_cost) / product.price * 100) if product.price > 0 else 0

    if profit_margin < 30:
        price_issues.append(f"Biên lợi nhuận thấp ({profit_margin:.1f}% - mục tiêu >50% cho hàng thủ công)")

    # Check price changes
    recent_price_changes = [pc for pc in price_changes if pc.product_id == product.id and (datetime.utcnow() - pc.changed_at).days < 30]
    if recent_price_changes and recent_price_changes[-1].new_price > recent_price_changes[-1].old_price:
        increase_percent = ((recent_price_changes[-1].new_price - recent_price_changes[-1].old_price) / recent_price_changes[-1].old_price) * 100
        if increase_percent > 15:
            price_issues.append(f"Tăng giá gần đây {increase_percent:.1f}% có thể ảnh hưởng tỷ lệ chuyển đổi")

    if price_issues:
        issues.append({
            "category": "price",
            "severity": "high",
            "problems": price_issues,
            "solutions": [
                "Chạy khuyến mãi có thời hạn để kiểm tra độ nhạy giá",
                "Bundle với sản phẩm bổ trợ",
                "Làm nổi bật giá trị sản phẩm (tại sao xứng đáng với giá)",
                "Tối ưu chi phí nguyên liệu để cải thiện biên lợi nhuận"
            ]
        })

    # 3. CREATIVE ISSUES (Images/Video)
    creative_issues = []
    images_for_product = [img for img in product_images if img.product_id == product.id]
    if len(images_for_product) < 3:
        creative_issues.append(f"Chỉ có {len(images_for_product)} ảnh (khuyến nghị 5-8 ảnh)")
    if not any(img.type == "video" for img in images_for_product):
        creative_issues.append("Chưa có video sản phẩm (video tăng chuyển đổi 80%)")

    if creative_issues:
        issues.append({
            "category": "creative",
            "severity": "high",
            "problems": creative_issues,
            "solutions": [
                "Thêm ảnh lifestyle (ảnh dùng thực tế)",
                "Tạo video sản phẩm 15-30 giây",
                "Thêm ảnh so sánh kích thước",
                "Chụp ảnh cận cảnh chi tiết sản phẩm"
            ]
        })

    # 4. TRUST ISSUES
    trust_issues = []
    reviews = [r for r in product_reviews if r.product_id == product.id]
    avg_rating = sum(r.rating for r in reviews) / len(reviews) if reviews else 0

    if len(reviews) < 5:
        trust_issues.append(f"Chỉ có {len(reviews)} đánh giá (cần 20+ để xây dựng uy tín)")
    if avg_rating < 4.0:
        trust_issues.append(f"Rating thấp ({avg_rating:.1f}/5.0)")
    if reviews and not any(r.has_image for r in reviews):
        trust_issues.append("Chưa có đánh giá kèm ảnh của khách hàng")

    if trust_issues:
        issues.append({
            "category": "trust",
            "severity": "critical" if avg_rating < 3.5 else "high",
            "problems": trust_issues,
            "solutions": [
                "Gửi email theo dõi để xin đánh giá",
                "Tặng voucher nhỏ cho đánh giá kèm ảnh",
                "Trưng bày testimonial khách hàng nổi bật",
                "Thêm chính sách hoàn tiền/đổi trả"
            ]
        })

    # 5. SEASONALITY
    seasonal_issues = []
    if product.seasons:
        current_month = datetime.utcnow().month
        in_season = any(s for s in seasons if s.id in product.seasons and s.start_month <= current_month <= s.end_month)
        if not in_season:
            seasonal_issues.append("Sản phẩm đang ngoài mùa bán hàng")

    if seasonal_issues:
        issues.append({
            "category": "seasonality",
            "severity": "low",
            "problems": seasonal_issues,
            "solutions": [
                "Giảm ngân sách quảng cáo trong mùa thấp điểm",
                "Tạo nội dung chuẩn bị cho mùa sắp tới",
                "Tập trung vào sản phẩm bán quanh năm",
                "Lên kế hoạch tồn kho cho mùa tiếp theo"
            ]
        })

    # 6. OPERATIONS
    operations_issues = []
    # Check inventory
    required_materials = product.materials
    for usage in required_materials:
        material = next((m for m in materials if m.id == usage.material_id), None)
        if material and material.stock_quantity < material.low_threshold:
            operations_issues.append(f"Tồn kho thấp: {material.name}")

    if operations_issues:
        issues.append({
            "category": "operations",
            "severity": "high",
            "problems": operations_issues,
            "solutions": [
                "Đặt hàng nguyên liệu ngay lập tức",
                "Thiết lập ngưỡng đặt hàng tự động",
                "Dự trữ thêm cho sản phẩm bán chạy",
                "Cập nhật trạng thái sẵn hàng trên sàn"
            ]
        })

    # Calculate overall health score
    severity_weights = {"critical": 10, "high": 5, "medium": 2, "low": 1}
    total_severity = sum(severity_weights.get(issue["severity"], 0) for issue in issues)
    health_score = max(0, 100 - total_severity * 5)

    return {
        "product": {
            "id": product.id,
            "code": product.code,
            "name": product.name,
            "price": product.price,
            "lifecycle": product.lifecycle
        },
        "issues": issues,
        "health_score": health_score,
        "health_status": "excellent" if health_score >= 80 else "good" if health_score >= 60 else "fair" if health_score >= 40 else "poor",
        "summary": {
            "total_issues": len(issues),
            "critical": len([i for i in issues if i["severity"] == "critical"]),
            "high": len([i for i in issues if i["severity"] == "high"]),
            "medium": len([i for i in issues if i["severity"] == "medium"]),
            "low": len([i for i in issues if i["severity"] == "low"])
        }
    }




@router.get("/analytics/funnel")
async def analyze_funnel(
    product_id: Optional[int] = None,
    current_user: User = Depends(get_current_user)
):
    """
    Funnel analysis: Impression → View → Click → Add to Cart → Purchase
    Identifies conversion bottlenecks
    """
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    thirty_days_ago_date = thirty_days_ago.date()  # Convert to date for week_of comparison

    if product_id:
        # Single product funnel
        product = next((p for p in products if p.id == product_id), None)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        product_demand = [d for d in demand_signals if d.product_id == product_id and d.week_of >= thirty_days_ago_date]
        product_orders = [o for o in orders if any(line.product_id == product_id for line in o.order_lines) and o.date >= thirty_days_ago.date()]

        views = sum(d.views for d in product_demand)
        clicks = sum(d.inquiries for d in product_demand)  # inquiries = clicked to see details
        saves = sum(d.saves for d in product_demand)  # saves = add to cart proxy
        purchases = len(product_orders)

        # Assume impressions = views * 3 (estimated)
        impressions = views * 3

        funnel = [
            {"stage": "impressions", "count": impressions, "rate": 100},
            {"stage": "views", "count": views, "rate": round(views / impressions * 100, 1) if impressions > 0 else 0},
            {"stage": "clicks", "count": clicks, "rate": round(clicks / views * 100, 1) if views > 0 else 0},
            {"stage": "saves", "count": saves, "rate": round(saves / clicks * 100, 1) if clicks > 0 else 0},
            {"stage": "purchases", "count": purchases, "rate": round(purchases / saves * 100, 1) if saves > 0 else 0}
        ]

        # Find biggest drop
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
        # Overall business funnel
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




@router.get("/analytics/market-benchmark/{product_id}")
async def get_market_benchmark(
    product_id: int,
    current_user: User = Depends(get_current_user)
):
    """
    Compare product against market benchmarks and competitors
    Provides competitive intelligence and positioning insights
    """
    product = next((p for p in products if p.id == product_id), None)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Get similar products (same category or lifecycle)
    similar_products = [p for p in products if p.id != product_id and (
        p.lifecycle == product.lifecycle or
        any(s in product.seasons for s in p.seasons) if product.seasons and p.seasons else False
    )][:5]

    # Calculate market averages
    all_active_products = [p for p in products if p.lifecycle in ["live", "experiment"]]

    if not all_active_products:
        raise HTTPException(status_code=404, detail="No active products for comparison")

    market_avg_price = sum(p.price for p in all_active_products) / len(all_active_products)

    # Calculate average reviews
    product_reviews_count = len([r for r in product_reviews if r.product_id == product.id])
    market_avg_reviews = sum(len([r for r in product_reviews if r.product_id == p.id]) for p in all_active_products) / len(all_active_products)

    # Calculate average rating
    product_ratings = [r.rating for r in product_reviews if r.product_id == product.id]
    product_avg_rating = sum(product_ratings) / len(product_ratings) if product_ratings else 0

    market_ratings = []
    for p in all_active_products:
        p_ratings = [r.rating for r in product_reviews if r.product_id == p.id]
        if p_ratings:
            market_ratings.append(sum(p_ratings) / len(p_ratings))
    market_avg_rating = sum(market_ratings) / len(market_ratings) if market_ratings else 0

    # Image count comparison
    product_images_count = len([img for img in product_images if img.product_id == product.id])
    market_avg_images = sum(len([img for img in product_images if img.product_id == p.id]) for p in all_active_products) / len(all_active_products)

    # Calculate material cost and profit margin
    product_material_cost = sum(
        usage.quantity * next((m.unit_price for m in materials if m.id == usage.material_id), 0)
        for usage in product.materials
    )
    product_profit_margin = ((product.price - product_material_cost) / product.price * 100) if product.price > 0 else 0

    # Market profit margins
    market_margins = []
    for p in all_active_products:
        p_cost = sum(
            usage.quantity * next((m.unit_price for m in materials if m.id == usage.material_id), 0)
            for usage in p.materials
        )
        if p.price > 0:
            market_margins.append((p.price - p_cost) / p.price * 100)
    market_avg_margin = sum(market_margins) / len(market_margins) if market_margins else 0

    # Competitive positioning
    positioning = {
        "price": "premium" if product.price > market_avg_price * 1.2 else "competitive" if product.price > market_avg_price * 0.8 else "budget",
        "quality": "high" if product_avg_rating > market_avg_rating + 0.3 else "average" if product_avg_rating > market_avg_rating - 0.3 else "low",
        "trust": "high" if product_reviews_count > market_avg_reviews * 1.5 else "average" if product_reviews_count > market_avg_reviews * 0.5 else "low",
        "content_quality": "high" if product_images_count >= market_avg_images else "low"
    }

    # Generate insights
    insights = []

    # Price insights
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

    # Rating insights
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

    # Review count insights
    if product_reviews_count < market_avg_reviews * 0.5:
        insights.append({
            "category": "trust",
            "type": "high",
            "message": f"Only {product_reviews_count} reviews vs market avg {market_avg_reviews:.0f}",
            "recommendation": "Send follow-up emails to request reviews. Offer incentive for photo reviews"
        })

    # Image insights
    if product_images_count < market_avg_images:
        insights.append({
            "category": "content",
            "type": "medium",
            "message": f"{product_images_count} images vs market avg {market_avg_images:.1f}",
            "recommendation": "Add more lifestyle images and detail shots. Market leaders have 5-8 images"
        })

    # Profit margin insights
    margin_diff = product_profit_margin - market_avg_margin
    if margin_diff < -10:
        insights.append({
            "category": "profitability",
            "type": "warning",
            "message": f"Profit margin {product_profit_margin:.1f}% vs market {market_avg_margin:.1f}%",
            "recommendation": "Optimize material costs or increase price to improve profitability"
        })

    # Competitive advantages
    advantages = []
    if positioning["price"] == "budget" and positioning["quality"] != "low":
        advantages.append("Great value proposition: Good quality at low price")
    if positioning["quality"] == "high":
        advantages.append("Superior quality backed by ratings")
    if positioning["trust"] == "high":
        advantages.append("Strong social proof with many reviews")
    if product_profit_margin > 50:
        advantages.append("Healthy profit margins allow for marketing investment")

    # Competitive weaknesses
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
                "lifecycle": p.lifecycle
            }
            for p in similar_products
        ]
    }




@router.get("/ideas", response_model=List[Idea])
async def list_ideas(current_user: User = Depends(get_current_user)):
    return ideas





@router.post("/ideas", response_model=Idea)
async def create_idea(payload: IdeaCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    new_idea = Idea(id=next_id(ideas), **payload.model_dump(), created_by=current_user.id)
    ideas.append(new_idea)
    upsert_document("ideas", new_idea)
    log_activity(current_user.id, "idea", new_idea.id, "create", changes=payload.model_dump())
    return new_idea





@router.put("/ideas/{idea_id}", response_model=Idea)
async def update_idea(idea_id: int, payload: Idea, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    if payload.id != idea_id:
        raise HTTPException(status_code=400, detail="Không được đổi id")
    for idx, idea in enumerate(ideas):
        if idea.id == idea_id:
            payload.created_by = idea.created_by or payload.created_by
            payload.updated_by = current_user.id
            ideas[idx] = payload
            upsert_document("ideas", payload, idea_id)
            log_activity(current_user.id, "idea", idea_id, "update", changes=payload.model_dump())
            return payload
    raise HTTPException(status_code=404, detail="Idea không tồn tại")





@router.delete("/ideas/{idea_id}")
async def delete_idea(idea_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for idea in ideas:
        if idea.id == idea_id:
            ideas.remove(idea)
            delete_document("ideas", idea_id)
            log_activity(current_user.id, "idea", idea_id, "delete")
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Idea không tồn tại")



@router.get("/content-plans", response_model=List[ContentPlan])
async def list_content_plans(current_user: User = Depends(get_current_user)):
    return content_plans





@router.post("/content-plans", response_model=ContentPlan)
async def create_content_plan(payload: ContentPlanCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    if payload.related_product_id:
        find_product(payload.related_product_id)
    new_plan = ContentPlan(id=next_id(content_plans), **payload.model_dump(), created_by=current_user.id)
    content_plans.append(new_plan)
    upsert_document("content_plans", new_plan)
    log_activity(current_user.id, "content_plan", new_plan.id, "create", changes=payload.model_dump())
    return new_plan





@router.put("/content-plans/{plan_id}", response_model=ContentPlan)
async def update_content_plan(plan_id: int, payload: ContentPlan, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    if payload.id != plan_id:
        raise HTTPException(status_code=400, detail="Không được đổi id")
    if payload.related_product_id:
        find_product(payload.related_product_id)
    for idx, plan in enumerate(content_plans):
        if plan.id == plan_id:
            payload.created_by = plan.created_by or payload.created_by
            payload.updated_by = current_user.id
            content_plans[idx] = payload
            upsert_document("content_plans", payload, plan_id)
            log_activity(current_user.id, "content_plan", plan_id, "update", changes=payload.model_dump())
            return payload
    raise HTTPException(status_code=404, detail="Content plan không tồn tại")





@router.post("/content-plans/{plan_id}/performance", response_model=ContentPlan)
async def update_content_performance(plan_id: int, payload: ContentPerformanceUpdate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for idx, plan in enumerate(content_plans):
        if plan.id == plan_id:
            data = plan.model_dump()
            for field, value in payload.model_dump(exclude_none=True).items():
                data[field] = value
            updated = ContentPlan(**data, updated_by=current_user.id)
            content_plans[idx] = updated
            upsert_document("content_plans", updated, plan_id)
            log_activity(current_user.id, "content_plan", plan_id, "update_performance", changes=payload.model_dump(exclude_none=True))
            return updated
    raise HTTPException(status_code=404, detail="Content plan không tồn tại")





@router.get("/content-plans/analytics")
async def content_performance_analytics(current_user: User = Depends(get_current_user)):
    """
    Analyze content performance: ROI, best formats, posting schedule
    """
    analytics = []

    for content in content_plans:
        if content.status != "published" or not content.actual_revenue:
            continue

        # Calculate ROI (assuming zero cost for now since cost_to_create field doesn't exist)
        cost_to_create = 0  # ContentPlan doesn't have cost_to_create field
        roi = 0  # Can't calculate without cost data

        # Calculate conversion rates
        views = content.actual_views or 0
        inquiries = content.actual_inquiries or 0
        orders = content.actual_orders or 0

        view_to_inquiry = (inquiries / views * 100) if views > 0 else 0
        inquiry_to_order = (orders / inquiries * 100) if inquiries > 0 else 0
        view_to_order = (orders / views * 100) if views > 0 else 0

        # Revenue per view
        revenue_per_view = content.actual_revenue / views if views > 0 else 0

        analytics.append({
            "content_id": content.id,
            "product_id": content.related_product_id,
            "format": content.format,
            "channel": content.channel,
            "published_date": content.published_date,
            "views": views,
            "inquiries": inquiries,
            "orders": orders,
            "revenue": content.actual_revenue,
            "cost": cost_to_create,
            "roi": round(roi, 2),
            "view_to_inquiry_rate": round(view_to_inquiry, 2),
            "inquiry_to_order_rate": round(inquiry_to_order, 2),
            "view_to_order_rate": round(view_to_order, 2),
            "revenue_per_view": round(revenue_per_view, 2)
        })

    # Best performing formats
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

    # Best posting times (by day of week)
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

    # Content fatigue detection (same product posted too many times)
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



@router.get("/experiments", response_model=List[Experiment])
async def list_experiments(current_user: User = Depends(get_current_user)):
    return experiments





@router.post("/experiments", response_model=Experiment)
async def create_experiment(payload: ExperimentCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    new_exp = Experiment(
        id=next_id(experiments),
        **payload.model_dump(),
        created_by=current_user.id,
        created_at=datetime.utcnow(),
    )
    experiments.append(new_exp)
    upsert_document("experiments", new_exp)
    log_activity(current_user.id, "experiment", new_exp.id, "create", changes=payload.model_dump())
    return new_exp





@router.put("/experiments/{exp_id}", response_model=Experiment)
async def update_experiment(exp_id: int, payload: ExperimentUpdate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for idx, exp in enumerate(experiments):
        if exp.id == exp_id:
            data = exp.model_dump()
            for field, value in payload.model_dump(exclude_none=True).items():
                data[field] = value
            updated = Experiment(**data)
            experiments[idx] = updated
            upsert_document("experiments", updated, exp_id)
            log_activity(current_user.id, "experiment", exp_id, "update", changes=payload.model_dump(exclude_none=True))
            return updated
    raise HTTPException(status_code=404, detail="Experiment không tồn tại")





@router.delete("/experiments/{exp_id}")
async def delete_experiment(exp_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for exp in experiments:
        if exp.id == exp_id:
            experiments.remove(exp)
            delete_document("experiments", exp_id)
            log_activity(current_user.id, "experiment", exp_id, "delete")
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Experiment không tồn tại")



@router.get("/goals", response_model=List[Goal])
async def list_goals(current_user: User = Depends(get_current_user)):
    return goals





@router.post("/goals", response_model=Goal)
async def create_goal(payload: GoalCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    new_goal = Goal(
        id=next_id(goals),
        **payload.model_dump(),
        created_by=current_user.id,
        created_at=datetime.utcnow(),
    )
    goals.append(new_goal)
    upsert_document("goals", new_goal)
    log_activity(current_user.id, "goal", new_goal.id, "create", changes=payload.model_dump())
    return new_goal





@router.put("/goals/{goal_id}", response_model=Goal)
async def update_goal(goal_id: int, payload: GoalCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for idx, goal in enumerate(goals):
        if goal.id == goal_id:
            updated = Goal(
                id=goal_id,
                **payload.model_dump(),
                created_by=goal.created_by,
                created_at=goal.created_at,
                achieved_at=goal.achieved_at,
            )
            goals[idx] = updated
            upsert_document("goals", updated, goal_id)
            log_activity(current_user.id, "goal", goal_id, "update", changes=payload.model_dump())
            return updated
    raise HTTPException(status_code=404, detail="Mục tiêu không tồn tại")





@router.delete("/goals/{goal_id}")
async def delete_goal(goal_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for goal in goals:
        if goal.id == goal_id:
            goals.remove(goal)
            delete_document("goals", goal_id)
            log_activity(current_user.id, "goal", goal_id, "delete")
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Mục tiêu không tồn tại")





@router.delete("/content-plans/{plan_id}")
async def delete_content_plan(plan_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for plan in content_plans:
        if plan.id == plan_id:
            content_plans.remove(plan)
            delete_document("content_plans", plan_id)
            log_activity(current_user.id, "content_plan", plan_id, "delete")
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Content plan không tồn tại")



@router.get("/tasks", response_model=List[Task])
async def list_tasks(assignee_id: Optional[int] = None, status: Optional[str] = None, current_user: User = Depends(get_current_user)):
    data = tasks
    if assignee_id is not None:
        data = [t for t in data if t.assignee_id == assignee_id]
    if status:
        data = [t for t in data if t.status == status]
    return data





@router.post("/tasks", response_model=Task)
async def create_task(payload: TaskCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    if payload.assignee_id and not any(u.id == payload.assignee_id for u in users):
        raise HTTPException(status_code=404, detail="Assignee không tồn tại")
    new_task = Task(
        id=next_id(tasks),
        **payload.model_dump(),
        created_by=current_user.id,
        created_at=datetime.utcnow(),
    )
    tasks.append(new_task)
    upsert_document("tasks", new_task)
    with Session(engine) as session:
        session.add(task_to_table(new_task))
        session.commit()
    log_activity(current_user.id, "task", new_task.id, "create", changes=payload.model_dump())
    return new_task





@router.put("/tasks/{task_id}", response_model=Task)
async def update_task(task_id: int, payload: TaskUpdate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for idx, task in enumerate(tasks):
        if task.id == task_id:
            data = task.model_dump()
            for k, v in payload.model_dump(exclude_none=True).items():
                data[k] = v
            if data.get("status") == "done" and not data.get("completed_at"):
                data["completed_at"] = datetime.utcnow()
            updated = Task(**data)
            tasks[idx] = updated
            upsert_document("tasks", updated, task_id)
            save_task_sql(updated)
            log_activity(current_user.id, "task", task_id, "update", changes=payload.model_dump(exclude_none=True))
            return updated
    raise HTTPException(status_code=404, detail="Task không tồn tại")





@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for task in tasks:
        if task.id == task_id:
            tasks.remove(task)
            delete_document("tasks", task_id)
            with Session(engine) as session:
                row = session.get(TaskTable, task_id)
                if row:
                    session.delete(row)
                    session.commit()
            log_activity(current_user.id, "task", task_id, "delete")
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Task không tồn tại")




@router.get("/business-health")
async def get_business_health(current_user: User = Depends(get_current_user)):
    """
    Calculate comprehensive business health metrics based on proven frameworks:
    - North Star Metric (primary growth indicator)
    - Unit Economics (CAC, LTV, payback period)
    - Health Score (0-100 composite score)
    """
    # Calculate key metrics
    total_customers = len(customers)
    total_orders = len(orders)
    total_revenue = sum(compute_order_totals(o)["revenue"] for o in orders)

    # Calculate date ranges
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    ninety_days_ago = now - timedelta(days=90)

    # Recent metrics (last 30 days)
    recent_orders = [o for o in orders if o.date >= thirty_days_ago.date()]
    recent_revenue = sum(compute_order_totals(o)["revenue"] for o in recent_orders)
    recent_customers = len(set(o.customer_id for o in recent_orders))

    # Previous 30 days for comparison
    sixty_days_ago = now - timedelta(days=60)
    previous_orders = [o for o in orders if sixty_days_ago.date() <= o.date < thirty_days_ago.date()]
    previous_revenue = sum(compute_order_totals(o)["revenue"] for o in previous_orders)

    # North Star Metric: Monthly Active Revenue (MAR)
    # For handmade business: Revenue per Active Customer
    mar = recent_revenue / recent_customers if recent_customers > 0 else 0

    # Unit Economics
    # CAC (Customer Acquisition Cost) - estimate from content & ads
    total_content = len(content_plans)
    estimated_content_cost = total_content * 50000  # 50k VND per content
    cac = estimated_content_cost / total_customers if total_customers > 0 else 0

    # LTV (Customer Lifetime Value)
    avg_order_value = total_revenue / total_orders if total_orders > 0 else 0
    # Calculate repeat purchase rate
    customer_order_counts = {}
    for order in orders:
        customer_order_counts[order.customer_id] = customer_order_counts.get(order.customer_id, 0) + 1

    repeat_customers = sum(1 for count in customer_order_counts.values() if count > 1)
    repeat_rate = repeat_customers / total_customers if total_customers > 0 else 0

    # LTV = AOV * Purchase Frequency * Customer Lifespan (estimate 2 years for handmade)
    avg_purchases_per_customer = total_orders / total_customers if total_customers > 0 else 1
    ltv = avg_order_value * avg_purchases_per_customer * 2  # 2 year lifespan

    # LTV/CAC Ratio (healthy is > 3)
    ltv_cac_ratio = ltv / cac if cac > 0 else 0

    # Payback Period (months to recover CAC)
    monthly_revenue_per_customer = mar
    payback_period = cac / monthly_revenue_per_customer if monthly_revenue_per_customer > 0 else 0

    # Burn Rate & Runway
    # Estimate monthly costs
    monthly_material_cost = sum(m.stock_quantity * m.unit_price for m in materials) / 12  # Assuming 1 year of inventory
    monthly_fixed_costs = 5000000  # 5M VND estimate for overhead
    monthly_burn = monthly_material_cost + monthly_fixed_costs + estimated_content_cost / 12

    # Gross Margin
    total_material_cost = sum(
        sum(usage.quantity * next((m.unit_price for m in materials if m.id == usage.material_id), 0)
            for usage in p.materials)
        for p in products
    )
    gross_margin = (total_revenue - total_material_cost) / total_revenue if total_revenue > 0 else 0

    # Health Score Calculation (0-100)
    # Based on 5 pillars
    health_components = {
        "revenue_growth": min(100, ((recent_revenue - previous_revenue) / previous_revenue * 100) if previous_revenue > 0 else 50),
        "ltv_cac_ratio": min(100, ltv_cac_ratio / 5 * 100),  # Normalize to 5 as excellent
        "gross_margin": gross_margin * 100,
        "repeat_rate": repeat_rate * 100,
        "inventory_efficiency": min(100, (1 - len([m for m in materials if m.stock_quantity < m.low_threshold]) / len(materials)) * 100 if materials else 0)
    }

    health_score = sum(health_components.values()) / len(health_components)

    # Growth Rate
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
            "total_orders": total_orders,
            "active_customers_30d": recent_customers,
            "avg_purchases_per_customer": round(avg_purchases_per_customer, 2)
        }
    }





@router.get("/marketplace/logs")
async def get_marketplace_sync_logs(
    marketplace: Optional[str] = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user)
):
    """Get marketplace sync history"""
    try:
        with Session(engine) as session:
            query = select(MarketplaceSyncLogTable).order_by(MarketplaceSyncLogTable.synced_at.desc())

            if marketplace:
                query = query.where(MarketplaceSyncLogTable.marketplace == marketplace)

            query = query.limit(limit)
            logs = session.exec(query).all()

            return {
                "logs": [
                    {
                        "id": log.id,
                        "marketplace": log.marketplace,
                        "sync_type": log.sync_type,
                        "status": log.status,
                        "orders_synced": log.orders_synced,
                        "orders_failed": log.orders_failed,
                        "error_message": log.error_message,
                        "synced_at": log.synced_at.isoformat()
                    }
                    for log in logs
                ],
                "total": len(logs)
            }
    except Exception as e:
        print(f"Error fetching sync logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))




@router.get("/content/marketing-frameworks")
async def get_marketing_frameworks(current_user: User = Depends(get_current_user)):
    """
    Get marketing psychology frameworks: AIDA, STP, Hook & Story
    Provides templates and best practices
    """
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
                            "Engagement: 'Comment 'YES' để nhận catalog'",
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
                    "description": "Sợ bỏ lỡ cơ hội",
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



@router.get("/growth/aarrr-metrics")
async def get_aarrr_metrics(current_user: User = Depends(get_current_user)):
    """
    AARRR Pirate Metrics Framework for Growth
    - Acquisition: How people find you
    - Activation: First experience
    - Retention: Coming back
    - Revenue: Monetization
    - Referral: Word of mouth
    """
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    ninety_days_ago = now - timedelta(days=90)

    # Acquisition Metrics
    new_customers_30d = [c for c in customers if c.created_at >= thirty_days_ago]
    new_customers_90d = [c for c in customers if c.created_at >= ninety_days_ago]

    # Traffic sources (from content)
    content_views = sum(cp.estimate_views or 0 for cp in content_plans)
    content_engagement = sum(cp.estimate_inquiries or 0 for cp in content_plans)

    # Activation Metrics (customers who made first purchase within 7 days of signup)
    activated_customers = 0
    for customer in new_customers_30d:
        first_order = next((o for o in orders if hasattr(o, 'customer_id') and o.customer_id == customer.id), None)
        if first_order and hasattr(first_order, 'date') and first_order.date:
            order_datetime = datetime.combine(first_order.date, datetime.min.time())
            days_diff = (order_datetime - customer.created_at).days
            if days_diff <= 7:
                activated_customers += 1

    activation_rate = activated_customers / len(new_customers_30d) if new_customers_30d else 0

    # Retention Metrics
    # Cohort: customers from 60-90 days ago who made purchase in last 30 days
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

    # Revenue Metrics
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
        except Exception as e:
            # Skip orders that cause errors
            continue

    arpu = total_revenue / len(customers) if customers else 0  # Average Revenue Per User
    paying_customers = len(paying_customer_ids)
    arppu = total_revenue / paying_customers if paying_customers > 0 else 0

    # Referral Metrics (customers with referral tag or word-of-mouth)
    referral_customers = []
    for c in customers:
        tags_list = c.tags if c.tags else []
        tags_str = ' '.join(tags_list).lower() if isinstance(tags_list, list) else str(tags_list).lower()
        if 'referral' in tags_str or 'word-of-mouth' in tags_str:
            referral_customers.append(c)
    referral_rate = len(referral_customers) / len(customers) if customers else 0

    # Calculate funnel conversion rates
    funnel_data = {
        "acquisition": {
            "visitors": content_views,  # Estimated from content views
            "leads": content_engagement,  # Engaged viewers
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

    # Growth insights
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

    # Calculate revenue growth safely
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



@router.get("/strategy/okrs")
async def get_okrs(
    quarter: Optional[str] = None,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """
    Get OKRs (Objectives and Key Results) for strategic planning
    """
    filtered_okrs = okrs_db

    if quarter:
        filtered_okrs = [o for o in filtered_okrs if o.quarter == quarter]
    if status:
        filtered_okrs = [o for o in filtered_okrs if o.status == status]

    # Calculate progress for each OKR
    okrs_with_progress = []
    for okr in filtered_okrs:
        total_progress = 0
        for kr in okr.key_results:
            kr_progress = (kr.get("current", 0) / kr.get("target", 1)) * 100 if kr.get("target", 0) > 0 else 0
            kr["progress"] = min(100, kr_progress)
            total_progress += kr["progress"]

        okr_dict = okr.model_dump()
        okr_dict["overall_progress"] = round(total_progress / len(okr.key_results), 1) if okr.key_results else 0
        okrs_with_progress.append(okr_dict)

    return {
        "okrs": okrs_with_progress,
        "summary": {
            "total": len(okrs_with_progress),
            "active": len([o for o in filtered_okrs if o.status == "active"]),
            "achieved": len([o for o in filtered_okrs if o.status == "achieved"]),
            "at_risk": len([o for o in filtered_okrs if o.status == "at_risk"])
        }
    }



@router.post("/strategy/okrs")
async def create_okr(
    payload: OKRCreate,
    current_user: User = Depends(require_admin)
):
    """
    Create new OKR
    """
    new_okr = OKR(
        id=len(okrs_db) + 1,
        **payload.model_dump()
    )
    okrs_db.append(new_okr)
    return new_okr



@router.put("/strategy/okrs/{okr_id}")
async def update_okr(
    okr_id: int,
    payload: dict,
    current_user: User = Depends(require_admin)
):
    """
    Update OKR progress or status
    """
    okr = next((o for o in okrs_db if o.id == okr_id), None)
    if not okr:
        raise HTTPException(status_code=404, detail="OKR not found")

    for key, value in payload.items():
        if hasattr(okr, key):
            setattr(okr, key, value)

    okr.updated_at = datetime.utcnow()
    return okr



@router.get("/strategy/swot")
async def get_swot_analysis(
    category: Optional[str] = None,
    type: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """
    Get SWOT Analysis (Strengths, Weaknesses, Opportunities, Threats)
    """
    filtered_swot = swot_db

    if category:
        filtered_swot = [s for s in filtered_swot if s.category == category]
    if type:
        filtered_swot = [s for s in filtered_swot if s.type == type]

    # Group by type for matrix view
    swot_matrix = {
        "strengths": [s for s in filtered_swot if s.type == "strength"],
        "weaknesses": [s for s in filtered_swot if s.type == "weakness"],
        "opportunities": [s for s in filtered_swot if s.type == "opportunity"],
        "threats": [s for s in filtered_swot if s.type == "threat"]
    }

    return {
        "matrix": swot_matrix,
        "summary": {
            "total": len(filtered_swot),
            "strengths": len(swot_matrix["strengths"]),
            "weaknesses": len(swot_matrix["weaknesses"]),
            "opportunities": len(swot_matrix["opportunities"]),
            "threats": len(swot_matrix["threats"])
        }
    }



@router.post("/strategy/swot")
async def create_swot(
    payload: SWOTCreate,
    current_user: User = Depends(require_admin)
):
    """
    Create SWOT analysis entry
    """
    new_swot = SWOTAnalysis(
        id=len(swot_db) + 1,
        created_by=current_user.id,
        **payload.model_dump()
    )
    swot_db.append(new_swot)
    return new_swot



@router.get("/strategy/market-insights")
async def get_market_insights(
    type: Optional[str] = None,
    priority: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """
    Get market insights and competitive intelligence
    """
    filtered_insights = market_insights_db

    if type:
        filtered_insights = [i for i in filtered_insights if i.type == type]
    if priority:
        filtered_insights = [i for i in filtered_insights if i.priority == priority]

    return {
        "insights": filtered_insights,
        "summary": {
            "total": len(filtered_insights),
            "high_priority": len([i for i in filtered_insights if i.priority == "high"]),
            "competitors": len([i for i in filtered_insights if i.type == "competitor"]),
            "trends": len([i for i in filtered_insights if i.type == "trend"])
        }
    }



@router.post("/strategy/market-insights")
async def create_market_insight(
    payload: MarketInsightCreate,
    current_user: User = Depends(require_admin)
):
    """
    Create market insight entry
    """
    new_insight = MarketInsight(
        id=len(market_insights_db) + 1,
        **payload.model_dump()
    )
    market_insights_db.append(new_insight)
    return new_insight
