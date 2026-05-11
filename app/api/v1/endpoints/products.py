from app.shared import *
from fastapi import APIRouter

router = APIRouter()

@router.get("/products")
async def list_products(
    page: int = 1,
    page_size: int = 50,
    search: Optional[str] = None,
    category_id: Optional[int] = None,
    lifecycle_status: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    # Filter products
    filtered = products
    if search:
        search_lower = search.lower()
        filtered = [p for p in filtered if search_lower in p.name.lower() or search_lower in (p.notes or "").lower()]
    if category_id:
        filtered = [p for p in filtered if category_id in p.categories]
    if lifecycle_status:
        filtered = [p for p in filtered if p.lifecycle_status == lifecycle_status]

    # Calculate pagination
    total = len(filtered)
    total_pages = (total + page_size - 1) // page_size
    start = (page - 1) * page_size
    end = start + page_size
    page_items = filtered[start:end]

    # Compute metrics for page items only
    computed = []
    for product in page_items:
        metrics = get_product_cost_cached(product)
        product.demand_score = metrics.get("demand_score", product.demand_score)
        metrics_feas = metrics.pop("feasibility_score", None)
        product.feasibility_score = metrics_feas or product.feasibility_score
        base_dump = product.model_dump(exclude={"feasibility_score", "demand_score"})
        for k in ["packaging_cost", "marketing_cost", "platform_fee_percent"]:
            metrics.pop(k, None)
        computed.append(
            ProductComputed(
                **base_dump,
                **metrics,
                demand_score=product.demand_score,
                feasibility_score=product.feasibility_score,
            )
        )

    return {
        "items": computed,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }




@router.get("/products/summary")
async def products_summary(
    lifecycle_status: Optional[str] = None,
    category_id: Optional[int] = None,
    current_user: User = Depends(get_current_user)
):
    """
    Optimized endpoint for Products page - returns all necessary data in 1 call
    Replaces multiple API calls: /products, /materials, /seasons, /categories, /users
    """
    # Filter products
    filtered = products
    if lifecycle_status:
        filtered = [p for p in filtered if p.lifecycle_status == lifecycle_status]
    if category_id:
        filtered = [p for p in filtered if category_id in p.categories]

    # Compute metrics for all products
    computed = []
    for product in filtered:
        metrics = get_product_cost_cached(product)
        product.demand_score = metrics.get("demand_score", product.demand_score)
        metrics_feas = metrics.pop("feasibility_score", None)
        product.feasibility_score = metrics_feas or product.feasibility_score
        base_dump = product.model_dump(exclude={"feasibility_score", "demand_score"})
        for k in ["packaging_cost", "marketing_cost", "platform_fee_percent"]:
            metrics.pop(k, None)
        computed.append(
            ProductComputed(
                **base_dump,
                **metrics,
                demand_score=product.demand_score,
                feasibility_score=product.feasibility_score,
            )
        )

    # Statistics by lifecycle
    by_lifecycle = {}
    for p in products:
        status = p.lifecycle_status
        by_lifecycle[status] = by_lifecycle.get(status, 0) + 1

    # Calculate average feasibility
    feasibility_scores = [p.feasibility_score for p in computed if p.feasibility_score]
    avg_feasibility = sum(feasibility_scores) / len(feasibility_scores) if feasibility_scores else 0

    # Count low stock products (products that can't be made due to material shortage)
    low_stock_products = []
    for p in computed:
        if p.max_units_from_stock is not None and p.max_units_from_stock <= 0:
            low_stock_products.append(p.id)

    # Get unique users for assignment
    user_ids = set()
    for p in products:
        if p.created_by:
            user_ids.add(p.created_by)
        if p.updated_by:
            user_ids.add(p.updated_by)
    users_list = [u for u in users if u.id in user_ids] if user_ids else users[:10]

    return {
        "products": computed,
        "materials": materials,
        "seasons": seasons,
        "categories": categories,
        "users": users_list,
        "statistics": {
            "total": len(products),
            "by_lifecycle": by_lifecycle,
            "avg_feasibility": round(avg_feasibility, 1),
            "low_stock_count": len(low_stock_products),
            "low_stock_product_ids": low_stock_products
        }
    }




@router.post("/products", response_model=ProductComputed)
@limiter.limit("30/minute")  # Giới hạn tạo sản phẩm
async def create_product(request: Request, payload: ProductBase, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    new_product = Product(id=next_id(products), **payload.model_dump(), created_by=current_user.id)
    products.append(new_product)
    upsert_document("products", new_product)
    save_product_sql(new_product)
    lifecycle_event = LifecycleEvent(
        id=next_id(lifecycle_events),
        product_id=new_product.id,
        status=new_product.lifecycle_status,
        changed_by=current_user.id,
        changed_at=datetime.utcnow(),
    )
    lifecycle_events.append(lifecycle_event)
    save_lifecycle_sql(lifecycle_event)
    clear_product_cost_cache()  # Clear cache after creating product
    metrics = compute_product_cost(new_product)
    new_product.demand_score = metrics.get("demand_score", new_product.demand_score)
    new_product.feasibility_score = metrics.get("feasibility_score", new_product.feasibility_score)
    log_activity(current_user.id, "product", new_product.id, "create", changes=payload.model_dump())
    # Remove fields that are already in new_product to avoid duplicate keyword arguments
    for k in ["packaging_cost", "marketing_cost", "platform_fee_percent", "demand_score", "feasibility_score"]:
        metrics.pop(k, None)
    return ProductComputed(**new_product.model_dump(), **metrics)




@router.put("/products/{product_id}", response_model=ProductComputed)
async def update_product(product_id: int, payload: ProductBase, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    product = find_product(product_id)
    if payload.base_price != product.base_price:
        price_change = PriceChange(
            id=next_id(price_changes),
            product_id=product_id,
            old_price=product.base_price,
            new_price=payload.base_price,
            changed_by=current_user.id,
            changed_at=datetime.utcnow(),
        )
        price_changes.append(price_change)
        save_price_change_sql(price_change)
    if payload.lifecycle_status != product.lifecycle_status:
        lifecycle_event = LifecycleEvent(
            id=next_id(lifecycle_events),
            product_id=product_id,
            status=payload.lifecycle_status,
            note=None,
            changed_by=current_user.id,
            changed_at=datetime.utcnow(),
        )
        lifecycle_events.append(lifecycle_event)
        save_lifecycle_sql(lifecycle_event)
    payload_data = payload.model_dump(exclude={"created_by", "updated_by"})
    for field in payload_data.keys():
        setattr(product, field, getattr(payload, field))
    product.updated_by = current_user.id
    upsert_document("products", product, product_id)
    save_product_sql(product)
    clear_product_cost_cache(product_id)  # Clear cache for updated product
    metrics = compute_product_cost(product)
    product.demand_score = metrics.get("demand_score", product.demand_score)
    product.feasibility_score = metrics.get("feasibility_score", product.feasibility_score)
    log_activity(current_user.id, "product", product_id, "update", changes=payload.model_dump())
    for k in ["packaging_cost", "marketing_cost", "platform_fee_percent"]:
        metrics.pop(k, None)
    return ProductComputed(**product.model_dump(), **metrics)




@router.post("/products/import", response_model=BulkImportResponse)
@limiter.limit("10/minute")  # Limit bulk imports
async def import_products(request: Request, payload: BulkImportRequest, current_user: User = Depends(get_current_user)):
    """Bulk import products from Excel/CSV"""
    require_admin(current_user)
    imported = 0
    failed = 0
    errors = []

    for idx, item in enumerate(payload.items):
        try:
            # Validate required fields
            if not item.get("name"):
                errors.append(f"Row {idx + 1}: Missing name")
                failed += 1
                continue

            # Create product with defaults
            product_data = {
                "name": item["name"],
                "base_price": float(item.get("base_price", 0)),
                "difficulty": int(item.get("difficulty", 3)),
                "time_minutes": int(item.get("time_minutes", 60)),
                "notes": item.get("notes"),
                "tags": item.get("tags", "").split(",") if isinstance(item.get("tags"), str) else item.get("tags", []),
                "materials": [],
                "priority": 1,
                "role": "core",
                "lifecycle_status": "idea",
                "packaging_cost": 0,
                "marketing_cost": 0,
                "platform_fee_percent": 0,
            }

            new_product = Product(id=next_id(products), **product_data, created_by=current_user.id)
            products.append(new_product)
            upsert_document("products", new_product)
            save_product_sql(new_product)
            imported += 1
        except Exception as e:
            errors.append(f"Row {idx + 1}: {str(e)}")
            failed += 1

    log_activity(current_user.id, "product", None, "bulk_import", changes={"imported": imported, "failed": failed})
    return BulkImportResponse(imported=imported, failed=failed, errors=errors[:10])




@router.delete("/products/{product_id}")
async def delete_product(product_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    product = find_product(product_id)
    products.remove(product)
    delete_document("products", product_id)
    with Session(engine) as session:
        session.exec(delete(ProductTable).where(ProductTable.id == product_id))
        session.commit()
    clear_product_cost_cache(product_id)  # Clear cache after deleting product
    log_activity(current_user.id, "product", product_id, "delete")
    return {"ok": True}




@router.get("/products/{product_id}/history")
async def product_history(product_id: int, current_user: User = Depends(get_current_user)):
    history_price = [pc for pc in price_changes if pc.product_id == product_id]
    history_lifecycle = [ev for ev in lifecycle_events if ev.product_id == product_id]
    return {
        "price_changes": history_price,
        "lifecycle": history_lifecycle,
    }


# --- Public Endpoints for Landing Page ---------------------------------------
@router.get("/public/products/{product_id}")
async def public_get_product(product_id: int):
    """
    Public endpoint for Landing Page to fetch product details (including all images array).
    """
    product = next((p for p in products if p.id == product_id and p.lifecycle_status == "live"), None)
    if not product:
        raise HTTPException(status_code=404, detail="Sản phẩm không khả dụng")

    p_images = [img for img in product_images if img.product_id == product.id and getattr(img, "is_public", True)]
    sorted_images = sorted(p_images, key=lambda x: (not x.is_primary, x.display_order))

    # Defaults
    if not sorted_images:
        images_urls = [f"https://images.unsplash.com/photo-1584992236310-6edddc08acff?q=80&w=600&auto=format&fit=crop&seed={product.id}"]
    else:
        images_urls = [img.url for img in sorted_images]

    # Use first one as main image
    primary_image = images_urls[0]

    import app.shared as shared

    return {
        "id": product.id,
        "name": product.name,
        "description": product.notes or "",
        "base_price": product.base_price,
        "tags": product.tags or [],
        "image": primary_image,  # for backward config
        "images": images_urls,   # full list of images
        "tone": "Warm" if "Warm" in product.tags else ("Cool" if "Cool" in product.tags else "All"),
        "business_logo": shared.settings.business_logo if hasattr(shared.settings, "business_logo") else None
    }

@router.get("/public/products")
async def public_list_products(
    category_id: Optional[int] = None,
    search: Optional[str] = None
):
    """
    Public endpoint for the Landing Page to fetch products without authentication.
    Only returns products with 'live' lifecycle_status.
    """
    # Filter products that are "live"
    filtered = [p for p in products if p.lifecycle_status == "live"]

    if search:
        search_lower = search.lower()
        filtered = [p for p in filtered if search_lower in p.name.lower() or search_lower in (p.notes or "").lower()]
    if category_id:
        filtered = [p for p in filtered if category_id in p.categories]

    computed = []
    for product in filtered:
        # Get product image
        p_images = [img for img in product_images if img.product_id == product.id and getattr(img, "is_public", True)]
        primary_img = next((img for img in p_images if img.is_primary), p_images[0] if p_images else None)
        image_url = primary_img.url if primary_img else f"https://images.unsplash.com/photo-1584992236310-6edddc08acff?q=80&w=600&auto=format&fit=crop&seed={product.id}"

        # Avoid heavy computations for public facing API, just return basic info
        computed.append({
            "id": product.id,
            "name": product.name,
            "base_price": product.base_price,
            "tags": product.tags,
            "image": image_url,
            "tone": "Warm" if "Warm" in product.tags else ("Cool" if "Cool" in product.tags else "All")
        })

    import app.shared as shared
    return {
        "items": computed,
        "total": len(computed),
        "business_logo": shared.settings.business_logo if hasattr(shared.settings, "business_logo") else None
    }# --- Categories -------------------------------------------------------------
@router.get("/categories", response_model=List[Category])
async def list_categories():
    return categories




@router.post("/categories", response_model=Category)
async def create_category(payload: CategoryCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    if payload.parent_id:
        if not any(c.id == payload.parent_id for c in categories):
            raise HTTPException(status_code=404, detail="Danh mục cha không tồn tại")
    cat = Category(id=next_id(categories), **payload.model_dump(), created_at=datetime.utcnow())
    categories.append(cat)
    upsert_document("categories", cat)
    log_activity(current_user.id, "category", cat.id, "create", changes=payload.model_dump())
    return cat




@router.delete("/categories/{category_id}")
async def delete_category(category_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for c in categories:
        if c.id == category_id:
            categories.remove(c)
            delete_document("categories", category_id)
            log_activity(current_user.id, "category", category_id, "delete")
            return {"detail": "Đã xóa"}
    raise HTTPException(status_code=404, detail="Danh mục không tồn tại")



@router.get("/issue-templates", response_model=List[Issue])
async def list_issue_templates(current_user: User = Depends(get_current_user)):
    return [i for i in issues if i.is_template]

@router.get("/issues", response_model=List[Issue])
async def list_issues(
    product_id: Optional[int] = None,
    status: Optional[str] = None,
    priority: Optional[int] = None,
    assignee_id: Optional[int] = None,
    q: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    response: Response = None,
    current_user: User = Depends(get_current_user),
):
    def with_counts(src: List[Issue]) -> List[Issue]:
        for i in src:
            i.comments_count = len([c for c in issue_comments if c.issue_id == i.id])
        return src

    filtered = issues
    if product_id:
        filtered = [i for i in filtered if i.product_id == product_id]
    if status:
        filtered = [i for i in filtered if i.status == status]
    if priority is not None:
        filtered = [i for i in filtered if i.priority == priority]
    if assignee_id is not None:
        filtered = [i for i in filtered if i.assigned_to == assignee_id]
    if q:
        q_lower = q.lower()
        filtered = [i for i in filtered if q_lower in (i.description or "").lower() or q_lower in (i.type or "").lower()]
    total = len(filtered)
    if response is not None:
        response.headers["X-Total-Count"] = str(total)
    return with_counts(list(filtered))[offset : offset + limit]





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





@router.post("/issues", response_model=Issue)
async def create_issue(payload: IssueCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    find_product(payload.product_id)
    if payload.assigned_to and not any(u.id == payload.assigned_to for u in users):
        raise HTTPException(status_code=404, detail="Người được giao không tồn tại")
    new_issue = Issue(
        **payload.model_dump(),
        id=next_id(issues),
        created_at=datetime.utcnow(),
        created_by=current_user.id,
    )
    issues.append(new_issue)
    upsert_document("issues", new_issue)
    save_issue_sql(new_issue)
    log_activity(current_user.id, "issue", new_issue.id, "create", changes=payload.model_dump())
    return new_issue





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



@router.get("/demand", response_model=List[DemandSignal])
async def list_demand(product_id: Optional[int] = None, current_user: User = Depends(get_current_user)):
    if product_id:
        return [d for d in demand_signals if d.product_id == product_id]
    return demand_signals





@router.post("/demand", response_model=DemandSignal)
async def add_demand(payload: DemandSignalCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    find_product(payload.product_id)
    new_signal = DemandSignal(
        id=next_id(demand_signals),
        product_id=payload.product_id,
        views=payload.views,
        inquiries=payload.inquiries,
        saves=payload.saves,
        week_of=payload.week_of,
        created_by=current_user.id,
    )
    demand_signals.append(new_signal)
    upsert_document("demand_signals", new_signal)
    save_demand_sql(new_signal)
    log_activity(current_user.id, "demand", new_signal.id, "create", changes=new_signal.model_dump())

    # Update product demand_score simple calc
    product = find_product(new_signal.product_id)
    weekly = [d for d in demand_signals if d.product_id == product.id]
    avg_views = sum(d.views for d in weekly) / len(weekly)
    avg_inquiries = sum(d.inquiries for d in weekly) / len(weekly)
    avg_saves = sum(d.saves for d in weekly) / len(weekly)
    demand_score = min(100, avg_views * 0.01 + avg_inquiries * 2 + avg_saves * 1.5)
    product.demand_score = demand_score
    upsert_document("products", product, product.id)
    save_product_sql(product)
    return new_signal



@router.get("/bundles", response_model=List[ProductBundle])
async def list_bundles(parent_product_id: Optional[int] = None, current_user: User = Depends(get_current_user)):
    if parent_product_id:
        return [b for b in product_bundles if b.parent_product_id == parent_product_id]
    return product_bundles





@router.post("/bundles", response_model=ProductBundle)
async def create_bundle(payload: ProductBundleCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    validate_product_exists(payload.parent_product_id)
    validate_product_exists(payload.child_product_id)
    new_bundle = ProductBundle(id=next_id(product_bundles), **payload.model_dump(), created_at=datetime.utcnow())
    product_bundles.append(new_bundle)
    upsert_document("product_bundles", new_bundle)
    log_activity(current_user.id, "bundle", new_bundle.id, "create", changes=payload.model_dump())
    return new_bundle





@router.delete("/bundles/{bundle_id}")
async def delete_bundle(bundle_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for b in product_bundles:
        if b.id == bundle_id:
            product_bundles.remove(b)
            delete_document("product_bundles", bundle_id)
            log_activity(current_user.id, "bundle", bundle_id, "delete")
            return {"detail": "Đã xóa"}
    raise HTTPException(status_code=404, detail="Bundle không tồn tại")



@router.get("/product-images", response_model=List[ProductImage])
async def list_product_images(product_id: Optional[int] = None, current_user: User = Depends(get_current_user)):
    if product_id:
        return sorted([img for img in product_images if img.product_id == product_id], key=lambda x: x.display_order)
    return sorted(product_images, key=lambda x: (x.product_id, x.display_order))





@router.post("/product-images", response_model=ProductImage)
async def create_product_image(payload: ProductImageCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    validate_product_exists(payload.product_id)

    if payload.is_primary:
        for p_img in product_images:
            if p_img.product_id == payload.product_id:
                p_img.is_primary = False
                upsert_document("product_images", p_img)

    img = ProductImage(id=next_id(product_images), **payload.model_dump(), created_at=datetime.utcnow())
    product_images.append(img)
    upsert_document("product_images", img)
    log_activity(current_user.id, "product_image", img.id, "create", changes=payload.model_dump())
    return img

@router.put("/product-images/{image_id}/set-primary")
async def set_primary_product_image(image_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    target_img = next((img for img in product_images if img.id == image_id), None)
    if not target_img:
        raise HTTPException(status_code=404, detail="Ảnh không tồn tại")

    for p_img in product_images:
        if p_img.product_id == target_img.product_id:
            if p_img.id == image_id:
                p_img.is_primary = True
                p_img.is_public = True # Must be public if primary
            else:
                p_img.is_primary = False
            upsert_document("product_images", p_img)

    return {"detail": "Đã đặt làm ảnh chính landing page"}

@router.put("/product-images/{image_id}/toggle-public")
async def toggle_public_product_image(image_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    target_img = next((img for img in product_images if img.id == image_id), None)
    if not target_img:
        raise HTTPException(status_code=404, detail="Ảnh không tồn tại")

    target_img.is_public = not target_img.is_public
    # If hidden, it cannot be primary anymore
    if not target_img.is_public and target_img.is_primary:
        target_img.is_primary = False

    upsert_document("product_images", target_img)

    return {"detail": "Đã cập nhật trạng thái hiển thị", "is_public": target_img.is_public}



@router.delete("/product-images/{image_id}")
async def delete_product_image(image_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for img in product_images:
        if img.id == image_id:
            product_images.remove(img)
            delete_document("product_images", image_id)
            log_activity(current_user.id, "product_image", image_id, "delete")
            return {"detail": "Đã xóa"}
    raise HTTPException(status_code=404, detail="Ảnh không tồn tại")



@router.get("/reviews", response_model=List[ProductReview])
async def list_reviews(product_id: Optional[int] = None, current_user: User = Depends(get_current_user)):
    if product_id:
        return [r for r in product_reviews if r.product_id == product_id]
    return product_reviews





@router.post("/reviews", response_model=ProductReview)
async def create_review(payload: ProductReviewCreate):
    validate_product_exists(payload.product_id)
    review = ProductReview(id=next_id(product_reviews), **payload.model_dump(), created_at=datetime.utcnow())
    product_reviews.append(review)
    upsert_document("product_reviews", review)
    log_activity(0, "review", review.id, "create", changes=payload.model_dump())
    return review





@router.delete("/reviews/{review_id}")
async def delete_review(review_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for r in product_reviews:
        if r.id == review_id:
            product_reviews.remove(r)
            delete_document("product_reviews", review_id)
            log_activity(current_user.id, "review", review_id, "delete")
            return {"detail": "Đã xóa"}
    raise HTTPException(status_code=404, detail="Review không tồn tại")
