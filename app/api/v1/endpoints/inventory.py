from app.shared import *
from fastapi import APIRouter

router = APIRouter()

@router.post("/materials/import", response_model=BulkImportResponse)
@limiter.limit("10/minute")
async def import_materials(request: Request, payload: BulkImportRequest, current_user: User = Depends(get_current_user)):
    """Bulk import materials from Excel/CSV"""
    require_admin(current_user)
    imported = 0
    failed = 0
    errors = []

    for idx, item in enumerate(payload.items):
        try:
            required = ["code", "name", "type", "unit", "unit_price", "stock_quantity"]
            missing = [f for f in required if not item.get(f)]
            if missing:
                errors.append(f"Row {idx + 1}: Missing {', '.join(missing)}")
                failed += 1
                continue

            # Check for duplicate code
            if any(m.code == item["code"] for m in materials):
                errors.append(f"Row {idx + 1}: Code {item['code']} already exists")
                failed += 1
                continue

            material_data = {
                "code": item["code"],
                "name": item["name"],
                "type": item["type"],
                "unit": item["unit"],
                "unit_price": float(item["unit_price"]),
                "stock_quantity": float(item["stock_quantity"]),
                "low_threshold": float(item.get("low_threshold", 1.0)),
                "note": item.get("note"),
            }

            new_material = Material(id=next_id(materials), **material_data, created_by=current_user.id)
            materials.append(new_material)
            upsert_document("materials", new_material)
            save_material_sql(new_material)
            imported += 1
        except Exception as e:
            errors.append(f"Row {idx + 1}: {str(e)}")
            failed += 1

    log_activity(current_user.id, "material", None, "bulk_import", changes={"imported": imported, "failed": failed})
    return BulkImportResponse(imported=imported, failed=failed, errors=errors[:10])




# --- Material endpoints -----------------------------------------------------
@router.get("/materials")
async def list_materials(
    page: int = 1,
    page_size: int = 100,
    search: Optional[str] = None,
    type: Optional[str] = None,
    low_stock_only: bool = False,
    current_user: User = Depends(get_current_user)
):
    # Filter
    filtered = materials
    if search:
        search_lower = search.lower()
        filtered = [m for m in filtered if search_lower in m.name.lower() or search_lower in m.code.lower()]
    if type:
        filtered = [m for m in filtered if m.type == type]
    if low_stock_only:
        filtered = [m for m in filtered if m.stock_quantity <= m.low_threshold]

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




@router.post("/materials", response_model=Material)
async def create_material(payload: MaterialCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    if any(m.code.lower() == payload.code.lower() for m in materials):
        raise HTTPException(status_code=400, detail="Mã nguyên liệu đã tồn tại")
    new_material = Material(id=next_id(materials), **payload.model_dump(), created_by=current_user.id)
    materials.append(new_material)
    upsert_document("materials", new_material)
    save_material_sql(new_material)
    clear_product_cost_cache()  # Material affects product costs
    log_activity(current_user.id, "material", new_material.id, "create", changes=payload.model_dump())
    return new_material




@router.put("/materials/{material_id}", response_model=Material)
async def update_material(material_id: int, payload: Material, request: Request, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    existing = find_material(material_id)
    old_data = existing.model_dump()
    if payload.id != material_id:
        raise HTTPException(status_code=400, detail="Không được đổi id")
    if any(m.code.lower() == payload.code.lower() and m.id != material_id for m in materials):
        raise HTTPException(status_code=400, detail="Mã nguyên liệu đã tồn tại")
    for field, value in payload.model_dump(exclude={"created_by", "updated_by"}).items():
        setattr(existing, field, value)
    existing.updated_by = current_user.id
    upsert_document("materials", existing, material_id)
    save_material_sql(existing)
    clear_product_cost_cache()  # Material changes affect all products
    log_activity(current_user.id, "material", material_id, "update", changes=payload.model_dump())
    await create_audit_log(current_user, "UPDATE", "materials", material_id, old_data, payload.model_dump(), request)
    return existing




@router.delete("/materials/{material_id}")
async def delete_material(material_id: int, request: Request, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    material = find_material(material_id)
    old_data = material.model_dump()
    materials.remove(material)
    delete_document("materials", material_id)
    with Session(engine) as session:
        session.exec(delete(MaterialTable).where(MaterialTable.id == material_id))
        session.commit()
    log_activity(current_user.id, "material", material_id, "delete")
    await create_audit_log(current_user, "DELETE", "materials", material_id, old_data, None, request)
    return {"ok": True}




@router.put("/suppliers/{supplier_id}", response_model=Supplier)
async def update_supplier(supplier_id: int, payload: SupplierCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for idx, sup in enumerate(suppliers):
        if sup.id == supplier_id:
            updated = Supplier(id=supplier_id, **payload.model_dump(), created_at=sup.created_at)
            suppliers[idx] = updated
            upsert_document("suppliers", updated, supplier_id)
            with Session(engine) as session:
                session.merge(supplier_to_table(updated))
                session.commit()
            log_activity(current_user.id, "supplier", supplier_id, "update", changes=payload.model_dump())
            return updated
    raise HTTPException(status_code=404, detail="Supplier không tồn tại")




@router.delete("/suppliers/{supplier_id}")
async def delete_supplier(supplier_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for sup in suppliers:
        if sup.id == supplier_id:
            suppliers.remove(sup)
            delete_document("suppliers", supplier_id)
            with Session(engine) as session:
                row = session.get(SupplierTable, supplier_id)
                if row:
                    session.delete(row)
                    session.commit()
            log_activity(current_user.id, "supplier", supplier_id, "delete")
            return {"detail": "Đã xóa"}
    raise HTTPException(status_code=404, detail="Supplier không tồn tại")




@router.put("/purchase-orders/{po_id}", response_model=PurchaseOrder)
async def update_purchase_order(po_id: int, payload: PurchaseOrderCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    validate_purchase_order_payload(payload)
    for idx, po in enumerate(purchase_orders):
        if po.id == po_id:
            previous_status = po.status
            updated = PurchaseOrder(
                id=po_id,
                supplier_id=payload.supplier_id,
                status=payload.status,
                expected_date=payload.expected_date,
                note=payload.note,
                lines=payload.lines,
                total_amount=compute_po_total(payload.lines),
                created_by=po.created_by,
                created_at=po.created_at,
                received_at=po.received_at,
            )
            if previous_status != "received" and payload.status == "received":
                receive_purchase_order(updated, current_user)
            purchase_orders[idx] = updated
            upsert_document("purchase_orders", updated, po_id)
            with Session(engine) as session:
                session.merge(po_to_table(updated))
                session.commit()
            log_activity(current_user.id, "purchase_order", po_id, "update", changes=payload.model_dump())
            return updated
    raise HTTPException(status_code=404, detail="Purchase order không tồn tại")




@router.get("/purchase-orders/suggestions")
async def suggest_purchase_orders(current_user: User = Depends(get_current_user)):
    """
    Auto-suggest purchase orders for materials running low
    Based on: current stock, low threshold, weekly usage, lead time
    """
    suggestions = []

    for material in materials:
        # Check if below threshold
        if material.stock_quantity > material.low_threshold:
            continue

        # Calculate weekly usage from recent orders
        weekly_usage = 0
        for product in products:
            for usage in product.materials:
                if usage.material_id == material.id:
                    # Count units sold in last 30 days
                    recent_orders = [o for o in orders if (date.today() - o.date).days <= 30]
                    units_sold = sum(
                        line.quantity
                        for order in recent_orders
                        for line in order.order_lines
                        if line.product_id == product.id
                    )
                    weekly_usage += (units_sold * usage.quantity) / 4  # 4 weeks

        # Calculate weeks remaining
        weeks_remaining = material.stock_quantity / weekly_usage if weekly_usage > 0 else 999

        # Calculate suggested order quantity
        # Order enough for 4 weeks + safety stock (2 weeks)
        suggested_quantity = weekly_usage * 6 if weekly_usage > 0 else material.low_threshold * 3

        # Find preferred supplier (most recent purchase)
        recent_po = None
        for po in reversed(purchase_orders):
            for line in po.lines:
                if line.material_id == material.id:
                    recent_po = po
                    break
            if recent_po:
                break

        suggestions.append({
            "material_id": material.id,
            "material_code": material.code,
            "material_name": material.name,
            "current_stock": material.stock_quantity,
            "low_threshold": material.low_threshold,
            "weekly_usage": round(weekly_usage, 2),
            "weeks_remaining": round(weeks_remaining, 2),
            "suggested_quantity": round(suggested_quantity, 2),
            "unit_price": material.unit_price,
            "estimated_cost": round(suggested_quantity * material.unit_price, 2),
            "suggested_supplier_id": recent_po.supplier_id if recent_po else None,
            "urgency": "critical" if weeks_remaining < 1 else "high" if weeks_remaining < 2 else "medium"
        })

    # Sort by urgency
    urgency_order = {"critical": 0, "high": 1, "medium": 2}
    suggestions.sort(key=lambda x: (urgency_order[x["urgency"]], x["weeks_remaining"]))

    return suggestions




@router.post("/purchase-orders/auto-create")
async def auto_create_purchase_orders(
    material_ids: List[int],
    current_user: User = Depends(get_current_user)
):
    """
    Automatically create purchase orders for selected materials
    """
    require_admin(current_user)

    # Get suggestions
    suggestions_response = await suggest_purchase_orders(current_user)
    suggestions = {s["material_id"]: s for s in suggestions_response}

    # Group by supplier
    by_supplier = {}
    for material_id in material_ids:
        if material_id not in suggestions:
            continue

        suggestion = suggestions[material_id]
        supplier_id = suggestion["suggested_supplier_id"]

        # If no supplier, use first supplier or create generic
        if not supplier_id and suppliers:
            supplier_id = suppliers[0].id
        elif not supplier_id:
            continue

        if supplier_id not in by_supplier:
            by_supplier[supplier_id] = []

        by_supplier[supplier_id].append({
            "material_id": material_id,
            "quantity": suggestion["suggested_quantity"],
            "unit_price": suggestion["unit_price"],
            "batch_id": None,
            "expiry_date": None
        })

    # Create POs
    created_pos = []
    for supplier_id, lines in by_supplier.items():
        payload = PurchaseOrderCreate(
            supplier_id=supplier_id,
            status="draft",
            expected_date=date.today() + timedelta(days=7),  # 1 week lead time
            note="Auto-generated based on low stock alerts",
            lines=lines
        )

        po = await create_purchase_order(payload, current_user)
        created_pos.append(po)

    return {
        "created_count": len(created_pos),
        "purchase_orders": created_pos
    }






@router.get("/inventory/summary")
async def inventory_summary(current_user: User = Depends(get_current_user)):
    """
    Optimized endpoint for Inventory page - returns all necessary data in 1 call
    Replaces: /materials, /products, /suppliers, /purchase-orders
    """
    # Material statistics
    low_stock_count = sum(1 for m in materials if m.stock_quantity <= m.low_threshold)
    total_value = sum(m.stock_quantity * m.unit_price for m in materials)

    # Material types breakdown
    types_breakdown = {}
    for m in materials:
        types_breakdown[m.type] = types_breakdown.get(m.type, 0) + 1

    # Products with max units calculation
    material_map = {m.id: m for m in materials}
    enhanced_products = []
    for p in products:
        if not p.materials:
            max_units = 0
        else:
            min_units = float('inf')
            for usage in p.materials:
                mat = material_map.get(usage.material_id)
                if mat:
                    max_for_mat = (mat.stock_quantity or 0) / (usage.quantity or 1)
                    min_units = min(min_units, max_for_mat)
            max_units = int(min_units) if min_units != float('inf') else 0

        product_dict = p.model_dump()
        product_dict['max_units_from_stock'] = max_units
        enhanced_products.append(product_dict)

    return {
        "materials": materials,
        "products": enhanced_products,
        "suppliers": suppliers,
        "purchase_orders": purchase_orders,
        "statistics": {
            "total_materials": len(materials),
            "low_stock_count": low_stock_count,
            "total_inventory_value": round(total_value, 2),
            "types_breakdown": types_breakdown
        }
    }



@router.get("/stock-movements", response_model=List[StockMovement])
async def list_stock_movements(material_id: Optional[int] = None):
    if material_id:
        return [sm for sm in stock_movements if sm.material_id == material_id]
    return stock_movements





@router.post("/stock-movements", response_model=StockMovement)
async def create_stock_movement(payload: StockMovementCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    material = find_material(payload.material_id)

    new_movement = StockMovement(
        id=next_id(stock_movements),
        **payload.model_dump(exclude={'new_price'}),
        unit_price=payload.new_price,
        user_id=current_user.id,
        created_at=datetime.utcnow()
    )
    stock_movements.append(new_movement)
    upsert_document("stock_movements", new_movement)
    with Session(engine) as session:
        session.add(stock_movement_to_table(new_movement))
        session.commit()

    # Update material stock & optional new price
    if payload.new_price is not None and payload.new_price > 0:
        material.unit_price = payload.new_price

    material.stock_quantity += new_movement.quantity_change
    save_material_sql(material)
    upsert_document("materials", material, material.id)

    log_activity(current_user.id, "stock_movement", new_movement.id, "create", changes=payload.model_dump())
    return new_movement
