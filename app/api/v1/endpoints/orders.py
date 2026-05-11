from app.shared import *
from fastapi import APIRouter

router = APIRouter()

@router.post("/customers/import", response_model=BulkImportResponse)
@limiter.limit("10/minute")
async def import_customers(request: Request, payload: BulkImportRequest, current_user: User = Depends(get_current_user)):
    """Bulk import customers from Excel/CSV"""
    require_admin(current_user)
    imported = 0
    failed = 0
    errors = []

    for idx, item in enumerate(payload.items):
        try:
            if not item.get("name"):
                errors.append(f"Row {idx + 1}: Missing name")
                failed += 1
                continue

            customer_data = {
                "name": item["name"],
                "phone": item.get("phone"),
                "email": item.get("email"),
                "address": item.get("address"),
                "source": item.get("source"),
                "tags": item.get("tags", "").split(",") if isinstance(item.get("tags"), str) else item.get("tags", []),
                "notes": item.get("notes"),
            }

            new_customer = Customer(
                id=next_id(customers),
                **customer_data,
                total_orders=0,
                total_spent=0,
                created_by=current_user.id,
                created_at=datetime.utcnow()
            )
            customers.append(new_customer)
            upsert_document("customers", new_customer)
            with Session(engine) as session:
                session.add(CustomerTable(
                    id=new_customer.id,
                    name=new_customer.name,
                    phone=new_customer.phone,
                    email=new_customer.email,
                    address=new_customer.address,
                    source=new_customer.source,
                    tags=",".join(new_customer.tags) if new_customer.tags else "",
                    total_orders=0,
                    total_spent=0,
                    notes=new_customer.notes,
                    created_by=new_customer.created_by,
                    created_at=new_customer.created_at,
                ))
                session.commit()
            imported += 1
        except Exception as e:
            errors.append(f"Row {idx + 1}: {str(e)}")
            failed += 1

    log_activity(current_user.id, "customer", None, "bulk_import", changes={"imported": imported, "failed": failed})
    return BulkImportResponse(imported=imported, failed=failed, errors=errors[:10])




# --- Orders endpoints -------------------------------------------------------
@router.get("/orders/summary")
async def orders_summary(current_user: User = Depends(get_current_user)):
    """Tổng hợp dữ liệu cho trang Orders trong 1 API call"""
    try:
        # Get paginated orders
        orders_with_totals = []
        for o in orders:
            try:
                totals = compute_order_totals(o)
                order_computed = OrderComputed(**o.model_dump(), **totals)
                orders_with_totals.append(order_computed)
            except Exception as e:
                print(f"Error computing order {o.id}: {e}")
                continue

        # Sort by date desc
        orders_with_totals.sort(key=lambda x: x.date, reverse=True)

        # Get products (with pagination data)
        products_data = []
        for p in products:
            try:
                cost_info = get_product_cost_cached(p)
                products_data.append({
                    "id": p.id,
                    "name": p.name,
                    "price": p.base_price,
                    "profit_per_unit": cost_info.get("profit_per_unit", 0),
                    "feasibility_score": cost_info.get("feasibility_score", 0)
                })
            except Exception as e:
                print(f"Error processing product {p.id}: {e}")
                continue

        # Get customers
        customers_data = []
        for c in customers:
            try:
                customers_data.append({
                    "id": c.id,
                    "name": c.name,
                    "source": getattr(c, 'source', '') or ""
                })
            except Exception as e:
                print(f"Error processing customer {c.id}: {e}")
                continue

        # Get content plans
        content_data = []
        for cp in content_plans:
            try:
                content_data.append({
                    "id": cp.id,
                    "title": cp.title,
                    "platform": getattr(cp, 'platform', '')
                })
            except Exception as e:
                print(f"Error processing content plan {cp.id}: {e}")
                continue

        # Get users
        users_data = []
        for u in users:
            try:
                users_data.append({
                    "id": u.id,
                    "username": u.name,
                    "role": u.role
                })
            except Exception as e:
                print(f"Error processing user {u.id}: {e}")
                continue

        # Get maker report - show all users who have orders with maker_user_id
        maker_report = []

        for user in users:
            try:
                # Find orders made by this user (admin can also be maker)
                user_orders = [o for o in orders_with_totals if getattr(o, 'maker_user_id', None) == user.id]
                if user_orders:
                    total_revenue = sum(getattr(o, 'revenue', 0) for o in user_orders)
                    total_profit = sum(getattr(o, 'profit', 0) for o in user_orders)
                    maker_report.append({
                        "maker_id": user.id,
                        "maker_name": user.name,
                        "orders": len(user_orders),
                        "revenue": total_revenue,
                        "profit": total_profit
                    })
            except Exception as e:
                print(f"Error processing maker report for user {user.id}: {e}")
                continue

        return {
            "orders": orders_with_totals[:100],  # Limit to 100 most recent
            "total_orders": len(orders),
            "products": products_data,
            "customers": customers_data,
            "contents": content_data,
            "users": users_data,
            "maker_report": maker_report
        }
    except Exception as e:
        print(f"Error in orders_summary: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error generating summary: {str(e)}")




@router.get("/orders")
async def list_orders(
    page: int = 1,
    page_size: int = 50,
    status: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    customer_id: Optional[int] = None,
    current_user: User = Depends(get_current_user)
):
    # Filter orders
    filtered = orders
    if status:
        filtered = [o for o in filtered if o.status == status]
    if start_date:
        filtered = [o for o in filtered if o.date >= start_date]
    if end_date:
        filtered = [o for o in filtered if o.date <= end_date]
    if customer_id:
        filtered = [o for o in filtered if o.customer_id == customer_id]

    # Sort by date descending
    filtered = sorted(filtered, key=lambda x: x.date, reverse=True)

    # Pagination
    total = len(filtered)
    total_pages = (total + page_size - 1) // page_size
    start = (page - 1) * page_size
    end = start + page_size
    page_items = filtered[start:end]

    # Compute totals for page items only
    enriched = []
    for order in page_items:
        totals = compute_order_totals(order)
        enriched.append(OrderComputed(**order.model_dump(), **totals))

    return {
        "items": enriched,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }




@router.post("/orders", response_model=OrderComputed)
@limiter.limit("30/minute")  # Giới hạn tạo đơn hàng
async def create_order(request: Request, payload: OrderCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    validate_order_payload(payload)
    apply_promo(payload)

    # Validate stock availability if order is confirmed
    if payload.status in ["confirmed", "processing"]:
        stock_errors = []
        for line in payload.order_lines:
            product = find_product(line.product_id)
            for usage in product.materials:
                material = find_material(usage.material_id)
                needed = usage.quantity * line.quantity
                if material.stock_quantity < needed:
                    stock_errors.append(
                        f"Thiếu {material.code}: cần {needed} {material.unit}, chỉ còn {material.stock_quantity}"
                    )

        if stock_errors:
            raise HTTPException(
                status_code=400,
                detail=f"Không đủ nguyên liệu: {'; '.join(stock_errors)}"
            )

    # Create order
    new_order = Order(id=next_id(orders), **payload.model_dump(), created_by=current_user.id)
    orders.append(new_order)

    # Auto-deduct stock if order is confirmed
    if new_order.status in ["confirmed", "processing"]:
        deduct_stock_for_order(new_order, current_user)

    # Update customer stats if customer_id provided
    if new_order.customer_id:
        for customer in customers:
            if customer.id == new_order.customer_id:
                customer.total_orders += 1
                totals = compute_order_totals(new_order)
                customer.total_spent += totals["revenue"]
                customer.last_order_date = new_order.date
                upsert_document("customers", customer, customer.id)
                with Session(engine) as session:
                    row = session.get(CustomerTable, customer.id)
                    if row:
                        row.total_orders = customer.total_orders
                        row.total_spent = customer.total_spent
                        row.last_order_date = customer.last_order_date
                        session.add(row)
                        session.commit()
                break

    upsert_document("orders", new_order)
    save_order_sql(new_order)
    totals = compute_order_totals(new_order)
    log_activity(current_user.id, "order", new_order.id, "create", changes=payload.model_dump())
    return OrderComputed(**new_order.model_dump(), **totals)




@router.put("/orders/{order_id}", response_model=OrderComputed)
async def update_order(order_id: int, payload: Order, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    validate_order_payload(payload)
    apply_promo(payload)
    if payload.id != order_id:
        raise HTTPException(status_code=400, detail="Không được đổi id")
    for idx, order in enumerate(orders):
        if order.id == order_id:
            previous_status = order.status
            payload.created_by = order.created_by or payload.created_by
            payload.updated_by = current_user.id
            orders[idx] = payload
            upsert_document("orders", payload, order_id)
            save_order_sql(payload)

            # Nếu chuyển từ trạng thái chưa trừ kho sang confirmed/processing thì trừ kho
            if payload.status in ["confirmed", "processing"] and previous_status not in ["confirmed", "processing"]:
                # kiểm tra tồn đủ
                stock_errors = []
                for line in payload.order_lines:
                    product = find_product(line.product_id)
                    for usage in product.materials:
                        material = find_material(usage.material_id)
                        needed = usage.quantity * line.quantity
                        if material.stock_quantity < needed:
                            stock_errors.append(
                                f"Thiếu {material.code}: cần {needed} {material.unit}, chỉ còn {material.stock_quantity}"
                            )
                if stock_errors:
                    raise HTTPException(status_code=400, detail=f"Không đủ nguyên liệu: {'; '.join(stock_errors)}")
                deduct_stock_for_order(payload, current_user)

            # Nếu huỷ đơn và đã trừ kho thì hoàn kho
            if payload.status == "cancelled" and previous_status in ["confirmed", "processing", "completed", "shipped", "delivered"]:
                restock_for_order(payload, current_user)

            totals = compute_order_totals(payload)
            log_activity(current_user.id, "order", order_id, "update", changes=payload.model_dump())
            return OrderComputed(**payload.model_dump(), **totals)
    raise HTTPException(status_code=404, detail="Order không tồn tại")




@router.post("/orders/{order_id}/tracking", response_model=OrderComputed)
async def add_tracking_update(order_id: int, payload: ShippingUpdatePayload, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    order = find_order(order_id)
    if payload.status and payload.status not in ORDER_STATUS_ALLOWED:
        raise HTTPException(status_code=400, detail="Trạng thái vận chuyển không hợp lệ")

    # append shipping update
    if payload.status or payload.note:
        order.shipping_updates = list(order.shipping_updates or [])
        order.shipping_updates.append(ShippingUpdate(status=payload.status, note=payload.note, timestamp=datetime.utcnow()))

    if payload.tracking_number:
        order.tracking_number = payload.tracking_number
    if payload.shipping_carrier:
        order.shipping_carrier = payload.shipping_carrier
    if payload.estimated_delivery_date:
        order.estimated_delivery_date = payload.estimated_delivery_date
    if payload.status:
        order.status = payload.status
    order.updated_by = current_user.id

    upsert_document("orders", order, order.id)
    save_order_sql(order)
    totals = compute_order_totals(order)
    log_activity(current_user.id, "order", order_id, "tracking_update", changes=payload.model_dump())
    return OrderComputed(**order.model_dump(), **totals)




@router.post("/orders/{order_id}/auto-assign-maker")
async def auto_assign_maker(order_id: int, current_user: User = Depends(get_current_user)):
    """
    Automatically assign maker based on workload
    """
    require_admin(current_user)

    order = None
    for o in orders:
        if o.id == order_id:
            order = o
            break

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Get all makers (users with role admin or maker)
    makers = [u for u in users if u.role in ["admin", "maker"]]

    if not makers:
        raise HTTPException(status_code=400, detail="No makers available")

    # Calculate current workload for each maker
    maker_workload = {m.id: 0 for m in makers}
    for o in orders:
        if o.status in ["confirmed", "processing"] and o.maker_user_id:
            # Count time_minutes for all products in this order
            for line in o.order_lines:
                product = find_product(line.product_id)
                if product:
                    maker_workload[o.maker_user_id] = maker_workload.get(o.maker_user_id, 0) + (product.time_minutes * line.quantity)

    # Assign to maker with lowest workload
    selected_maker = min(makers, key=lambda m: maker_workload[m.id])

    order.maker_user_id = selected_maker.id
    upsert_document("orders", order, order.id)
    save_order_sql(order)

    return {
        "order_id": order_id,
        "assigned_maker_id": selected_maker.id,
        "assigned_maker_name": selected_maker.name,
        "current_workload_minutes": maker_workload[selected_maker.id]
    }




@router.get("/orders/workflow-automation")
async def order_workflow_automation(current_user: User = Depends(get_current_user)):
    """
    Analyze orders for workflow automation opportunities
    """
    automation_suggestions = []

    for order in orders:
        suggestions = []

        # Suggest auto-assign if no maker assigned
        if order.status in ["confirmed", "processing"] and not order.maker_user_id:
            suggestions.append({
                "type": "assign_maker",
                "action": "Auto-assign maker based on workload",
                "priority": "high"
            })

        # Suggest tracking update if processing but no tracking
        if order.status == "processing" and not order.tracking_number:
            suggestions.append({
                "type": "add_tracking",
                "action": "Add tracking number and carrier",
                "priority": "medium"
            })

        # Suggest delivery confirmation if shipped >3 days
        if order.status == "shipped" and order.estimated_delivery_date:
            days_since_shipped = (date.today() - order.date).days
            if days_since_shipped > 3:
                suggestions.append({
                    "type": "confirm_delivery",
                    "action": "Confirm delivery and request review",
                    "priority": "high"
                })

        # Suggest follow-up if delivered >3 days
        if order.status == "delivered":
            days_since_delivered = (date.today() - order.date).days
            if days_since_delivered >= 3:
                suggestions.append({
                    "type": "request_review",
                    "action": "Send review request to customer",
                    "priority": "medium"
                })

        if suggestions:
            automation_suggestions.append({
                "order_id": order.id,
                "customer_id": order.customer_id,
                "status": order.status,
                "date": order.date,
                "suggestions": suggestions
            })

    return {
        "total_suggestions": len(automation_suggestions),
        "orders_needing_action": automation_suggestions[:20]  # Top 20
    }




@router.delete("/orders/{order_id}")
async def delete_order(order_id: int, request: Request, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for order in orders:
        if order.id == order_id:
            old_data = order.model_dump()
            orders.remove(order)
            delete_document("orders", order_id)
            with Session(engine) as session:
                session.exec(delete(OrderTable).where(OrderTable.id == order_id))
                session.commit()
            log_activity(current_user.id, "order", order_id, "delete")
            await create_audit_log(current_user, "DELETE", "orders", order_id, old_data, None, request)
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Order không tồn tại")




# --- Customer endpoints -----------------------------------------------------
@router.get("/customers")
async def list_customers(
    page: int = 1,
    page_size: int = 50,
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    # Filter
    filtered = customers
    if search:
        search_lower = search.lower()
        filtered = [c for c in filtered if
                   search_lower in c.name.lower() or
                   search_lower in (c.phone or "").lower() or
                   search_lower in (c.email or "").lower()]

    # Sort by total_spent descending
    filtered = sorted(filtered, key=lambda x: x.total_spent, reverse=True)

    # Pagination
    total = len(filtered)
    total_pages = (total + page_size - 1) // page_size
    start = (page - 1) * page_size
    end = start + page_size

    return {
        "items": filtered[start:end],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }




@router.get("/customers/summary")
async def customers_summary(current_user: User = Depends(get_current_user)):
    """
    Optimized endpoint for Customers page - returns all necessary data in 1 call
    Replaces: /customers, /orders, /reports/customer-analytics
    """
    compute_customer_metrics()
    today = date.today()

    # Customer analytics with RFM
    analytics = []
    for cust in customers:
        if cust.total_orders == 0:
            continue
        recency_days = (today - cust.last_order_date).days if cust.last_order_date else 999
        frequency = cust.total_orders
        monetary = cust.total_spent / cust.total_orders if cust.total_orders else 0
        # RFM scoring 1-5
        r_score = 5 if recency_days <= 30 else 4 if recency_days <= 60 else 3 if recency_days <= 120 else 2 if recency_days <= 180 else 1
        f_score = 5 if frequency >= 10 else 4 if frequency >= 6 else 3 if frequency >= 3 else 2 if frequency >= 2 else 1
        m_score = 5 if monetary >= 1_000_000 else 4 if monetary >= 500_000 else 3 if monetary >= 200_000 else 2 if monetary >= 100_000 else 1
        rfm = r_score + f_score + m_score
        analytics.append({
            "customer_id": cust.id,
            "name": cust.name,
            "source": cust.source,
            "total_orders": cust.total_orders,
            "total_spent": round(cust.total_spent, 2),
            "avg_order": round(monetary, 2),
            "recency_days": recency_days,
            "rfm_score": rfm,
        })

    # Statistics
    total_customers = len(customers)
    vip_customers = sum(1 for c in customers if "VIP" in (c.tags or []))
    repeat_customers = sum(1 for c in customers if c.total_orders > 1)
    avg_ltv = sum(c.total_spent for c in customers) / total_customers if total_customers > 0 else 0

    return {
        "customers": customers,
        "orders": orders,
        "analytics": sorted(analytics, key=lambda x: x["total_spent"], reverse=True),
        "statistics": {
            "total": total_customers,
            "vip": vip_customers,
            "repeat": repeat_customers,
            "avg_ltv": round(avg_ltv, 2)
        }
    }




@router.post("/customers", response_model=Customer)
@limiter.limit("30/minute")  # Giới hạn tạo khách hàng
async def create_customer(request: Request, payload: CustomerCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    new_customer = Customer(
        id=next_id(customers),
        **payload.model_dump(),
        created_by=current_user.id,
        created_at=datetime.utcnow()
    )
    customers.append(new_customer)
    upsert_document("customers", new_customer)
    with Session(engine) as session:
        session.add(CustomerTable(
            id=new_customer.id,
            name=new_customer.name,
            phone=new_customer.phone,
            email=new_customer.email,
            address=new_customer.address,
            source=new_customer.source,
            tags_json=json.dumps(new_customer.tags or []),
            total_orders=0,
            total_spent=0,
            last_order_date=new_customer.last_order_date,
            notes=new_customer.notes,
            created_by=new_customer.created_by,
            created_at=new_customer.created_at,
        ))
        session.commit()
    log_activity(current_user.id, "customer", new_customer.id, "create", changes=payload.model_dump())
    return new_customer




@router.put("/customers/{customer_id}", response_model=Customer)
async def update_customer(customer_id: int, payload: Customer, request: Request, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for idx, customer in enumerate(customers):
        if customer.id == customer_id:
            old_data = customer.model_dump()
            payload.id = customer_id
            payload.created_by = customer.created_by
            payload.created_at = customer.created_at
            customers[idx] = payload
            upsert_document("customers", payload, customer_id)
            with Session(engine) as session:
                row = session.get(CustomerTable, customer_id)
                if row:
                    row.name = payload.name
                    row.phone = payload.phone
                    row.email = payload.email
                    row.address = payload.address
                    row.source = payload.source
                    row.tags_json = json.dumps(payload.tags or [])
                    row.notes = payload.notes
                    row.total_orders = payload.total_orders
                    row.total_spent = payload.total_spent
                    row.last_order_date = payload.last_order_date
                    session.add(row)
                    session.commit()
            log_activity(current_user.id, "customer", customer_id, "update", changes=payload.model_dump())
            await create_audit_log(current_user, "UPDATE", "customers", customer_id, old_data, payload.model_dump(), request)
            return payload
    raise HTTPException(status_code=404, detail="Customer không tồn tại")




@router.delete("/customers/{customer_id}")
async def delete_customer(customer_id: int, request: Request, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for customer in customers:
        if customer.id == customer_id:
            old_data = customer.model_dump()
            customers.remove(customer)
            delete_document("customers", customer_id)
            with Session(engine) as session:
                row = session.get(CustomerTable, customer_id)
                if row:
                    session.delete(row)
                    session.commit()
            log_activity(current_user.id, "customer", customer_id, "delete")
            await create_audit_log(current_user, "DELETE", "customers", customer_id, old_data, None, request)
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Customer không tồn tại")




@router.post("/customers/auto-tag")
async def auto_tag_customers(current_user: User = Depends(get_current_user)):
    """
    Automatically tag customers based on their behavior
    - VIP: RFM score >= 12
    - repeater: total_orders > 1
    - inactive: last_order > 90 days
    - new: first order < 30 days ago
    """
    require_admin(current_user)
    compute_customer_metrics()
    today = date.today()
    updated_count = 0

    for customer in customers:
        if customer.total_orders == 0:
            continue

        # Calculate RFM
        recency_days = (today - customer.last_order_date).days if customer.last_order_date else 999
        frequency = customer.total_orders
        monetary = customer.total_spent / customer.total_orders if customer.total_orders else 0

        r_score = 5 if recency_days <= 30 else 4 if recency_days <= 60 else 3 if recency_days <= 120 else 2 if recency_days <= 180 else 1
        f_score = 5 if frequency >= 10 else 4 if frequency >= 6 else 3 if frequency >= 3 else 2 if frequency >= 2 else 1
        m_score = 5 if monetary >= 1_000_000 else 4 if monetary >= 500_000 else 3 if monetary >= 200_000 else 2 if monetary >= 100_000 else 1
        rfm_score = r_score + f_score + m_score

        new_tags = set(customer.tags or [])
        changed = False

        # VIP tagging
        if rfm_score >= 12:
            if "VIP" not in new_tags:
                new_tags.add("VIP")
                changed = True
        else:
            if "VIP" in new_tags:
                new_tags.remove("VIP")
                changed = True

        # Repeater tagging
        if frequency > 1:
            if "repeater" not in new_tags:
                new_tags.add("repeater")
                changed = True

        # Inactive tagging
        if recency_days > 90:
            if "inactive" not in new_tags:
                new_tags.add("inactive")
                changed = True
        else:
            if "inactive" in new_tags:
                new_tags.remove("inactive")
                changed = True

        # New customer tagging
        if customer.created_at and (datetime.utcnow() - customer.created_at).days < 30:
            if "new" not in new_tags:
                new_tags.add("new")
                changed = True
        else:
            if "new" in new_tags:
                new_tags.remove("new")
                changed = True

        # Update if changed
        if changed:
            customer.tags = list(new_tags)
            upsert_document("customers", customer, customer.id)
            with Session(engine) as session:
                row = session.get(CustomerTable, customer.id)
                if row:
                    row.tags_json = json.dumps(customer.tags)
                    session.add(row)
                    session.commit()
            updated_count += 1

    return {
        "updated_count": updated_count,
        "message": f"Auto-tagged {updated_count} customers"
    }




@router.get("/customers/lifecycle-analysis")
async def customer_lifecycle_analysis(current_user: User = Depends(get_current_user)):
    """
    Analyze customer lifecycle and suggest actions
    """
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

        # Segment customers
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




@router.get("/customers/cohort-analysis")
async def get_cohort_analysis(current_user: User = Depends(get_current_user)):
    """
    Cohort analysis: Track customer behavior grouped by signup month
    Shows retention and revenue patterns over time
    """
    from collections import defaultdict

    # Group customers by first purchase month
    cohorts = defaultdict(list)
    for customer in customers:
        cohort_month = customer.created_at.strftime("%Y-%m")
        cohorts[cohort_month].append(customer)

    # Calculate retention for each cohort
    cohort_data = []
    for cohort_month, cohort_customers in sorted(cohorts.items()):
        cohort_size = len(cohort_customers)
        cohort_start = datetime.strptime(cohort_month, "%Y-%m")

        # Calculate retention for each month after cohort start
        retention_by_month = {}
        revenue_by_month = {}

        for i in range(12):  # Track up to 12 months
            month_start = cohort_start + timedelta(days=30 * i)
            month_end = month_start + timedelta(days=30)

            # Count customers who made purchase in this month
            active_in_month = set()
            revenue_in_month = 0

            for order in orders:
                if order.customer_id in [c.id for c in cohort_customers]:
                    if month_start <= order.created_at < month_end:
                        active_in_month.add(order.customer_id)
                        revenue_in_month += order.total

            retention_rate = len(active_in_month) / cohort_size if cohort_size > 0 else 0
            avg_revenue = revenue_in_month / cohort_size if cohort_size > 0 else 0

            retention_by_month[f"month_{i}"] = round(retention_rate * 100, 1)
            revenue_by_month[f"month_{i}"] = round(avg_revenue, 0)

        # Calculate LTV for this cohort
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

    # Calculate overall metrics
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




@router.get("/activity", response_model=List[ActivityLog])
async def list_activity(
    limit: int = 100,
    entity_type: Optional[str] = None,
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """Lấy danh sách activity logs với filter tùy chọn"""
    result = activity_logs
    if entity_type:
        result = [log for log in result if log.entity_type == entity_type]
    if user_id:
        result = [log for log in result if log.user_id == user_id]
    if action:
        result = [log for log in result if log.action == action]
    return result[:limit]





@router.get("/activity/summary")
async def activity_summary(
    days: int = 7,
    current_user: User = Depends(get_current_user)
):
    """Thống kê activity trong N ngày gần nhất"""
    cutoff = datetime.utcnow() - timedelta(days=days)
    recent = [log for log in activity_logs if log.created_at >= cutoff]

    by_entity = {}
    by_user = {}
    by_action = {}

    for log in recent:
        by_entity[log.entity_type] = by_entity.get(log.entity_type, 0) + 1
        by_user[log.user_id] = by_user.get(log.user_id, 0) + 1
        by_action[log.action] = by_action.get(log.action, 0) + 1

    return {
        "total": len(recent),
        "by_entity_type": by_entity,
        "by_user": by_user,
        "by_action": by_action,
        "period_days": days,
    }



@router.get("/payments", response_model=List[Payment])
async def list_payments(order_id: Optional[int] = None, current_user: User = Depends(get_current_user)):
    if order_id:
        return [p for p in payments if p.order_id == order_id]
    return payments





@router.post("/payments", response_model=Payment)
async def create_payment(payload: PaymentCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    normalized_status = validate_payment_payload(payload)
    order = find_order(payload.order_id)
    new_payment = Payment(
        id=next_id(payments),
        order_id=payload.order_id,
        amount=payload.amount,
        method=payload.method,
        status=normalized_status,
        transaction_id=payload.transaction_id,
        paid_date=datetime.utcnow() if normalized_status == "paid" else None,
        notes=payload.notes,
        created_at=datetime.utcnow()
    )
    payments.append(new_payment)
    upsert_document("payments", new_payment)
    with Session(engine) as session:
        session.add(PaymentTable(
            id=new_payment.id,
            order_id=new_payment.order_id,
            amount=new_payment.amount,
            method=new_payment.method,
            status=new_payment.status,
            transaction_id=new_payment.transaction_id,
            paid_date=new_payment.paid_date,
            notes=new_payment.notes,
            created_at=new_payment.created_at,
        ))
        session.commit()

    # Update order payment status
    total_paid = sum(p.amount for p in payments if p.order_id == payload.order_id and p.status == "paid")
    totals = compute_order_totals(order)
    if total_paid >= totals["revenue"]:
        order.payment_status = "paid"
    elif total_paid > 0:
        order.payment_status = "partial"
    else:
        order.payment_status = "unpaid"
    save_order_sql(order)
    upsert_document("orders", order, order.id)

    log_activity(current_user.id, "payment", new_payment.id, "create", changes=new_payment.model_dump())
    return new_payment
