"""Product routes."""
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session

from config.database import engine, upsert_mongo, delete_mongo
from config.settings import settings
from models.user import User
from models.product import (
    Product, ProductTable, ProductVariant, ProductVariantTable,
    ProductBundle, ProductBundleTable, ProductImage, ProductImageTable,
    ProductReview, ProductReviewTable, MaterialUsage
)
from schemas.product import (
    ProductCreate, ProductVariantCreate, ProductBundleCreate,
    ProductImageCreate, ProductReviewCreate
)
from services.auth import get_current_user, get_current_user_optional, require_admin
from services.product import (
    compute_product_cost, get_product_cost_cached, clear_product_cost_cache,
    find_product
)
from services.activity import log_activity, create_audit_log
import json


def save_product_sql(product):
    """Upsert a product to SQL."""
    with Session(engine) as session:
        row = session.get(ProductTable, product.id)
        materials_json = json.dumps([m.model_dump(mode="json") if hasattr(m, "model_dump") else m.__dict__ for m in product.materials])
        if row:
            row.name = product.name
            row.base_price = product.base_price
            row.time_minutes = product.time_minutes
            row.wastage_percent = getattr(product, "wastage_percent", 0) or 0
            row.difficulty = product.difficulty
            row.notes = product.notes
            row.tags_json = json.dumps(product.tags or [])
            row.materials_json = materials_json
            row.categories_json = json.dumps(product.categories or [])
            row.seasons_json = json.dumps(product.seasons or [])
            row.priority = product.priority
            row.role = product.role
            row.lifecycle_status = product.lifecycle_status
            row.packaging_cost = product.packaging_cost
            row.marketing_cost = product.marketing_cost
            row.platform_fee_percent = product.platform_fee_percent
            row.cost_breakdown_json = json.dumps(product.cost_breakdown) if product.cost_breakdown else None
            row.finished_qty = getattr(product, "finished_qty", 0) or 0
            row.updated_at = product.updated_at
        else:
            row = ProductTable(
                id=product.id,
                name=product.name,
                base_price=product.base_price,
                time_minutes=product.time_minutes,
                wastage_percent=getattr(product, "wastage_percent", 0) or 0,
                difficulty=product.difficulty,
                notes=product.notes,
                tags_json=json.dumps(product.tags or []),
                materials_json=materials_json,
                categories_json=json.dumps(product.categories or []),
                seasons_json=json.dumps(product.seasons or []),
                priority=product.priority,
                role=product.role,
                lifecycle_status=product.lifecycle_status,
                packaging_cost=product.packaging_cost,
                marketing_cost=product.marketing_cost,
                platform_fee_percent=product.platform_fee_percent,
                cost_breakdown_json=json.dumps(product.cost_breakdown) if product.cost_breakdown else None,
                finished_qty=getattr(product, "finished_qty", 0) or 0,
                created_by=product.created_by,
                created_at=product.created_at,
                updated_at=product.updated_at,
            )
        session.add(row)
        session.commit()

router = APIRouter()
public_router = APIRouter()

# In-memory data stores (will be populated at startup)
products: List[Product] = []
product_variants: List[ProductVariant] = []
product_bundles: List[ProductBundle] = []
product_images: List[ProductImage] = []
product_reviews: List[ProductReview] = []


def _tone_from_tags(tags: Optional[List[str]]) -> str:
    tags = tags or []
    if "Warm" in tags:
        return "Warm"
    if "Cool" in tags:
        return "Cool"
    return "All"


def _public_images_for_product(product_id: int) -> List[ProductImage]:
    return sorted(
        [
            img
            for img in product_images
            if img.product_id == product_id and getattr(img, "is_public", True)
        ],
        key=lambda img: (not getattr(img, "is_primary", False), getattr(img, "display_order", 0)),
    )


def _fallback_image(product_id: int) -> str:
    return (
        "https://images.unsplash.com/photo-1584992236310-6edddc08acff"
        f"?q=80&w=600&auto=format&fit=crop&seed={product_id}"
    )


@router.get("")
async def list_products(
    skip: int = 0,
    limit: int = 100,
    category_id: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    user: Optional[User] = Depends(get_current_user_optional)
):
    """List all products with filtering."""
    result = products[:]

    if category_id:
        result = [p for p in result if category_id in (p.categories or [])]
    if status:
        result = [p for p in result if p.lifecycle_status == status]
    if search:
        search_lower = search.lower()
        result = [p for p in result if search_lower in p.name.lower() or search_lower in (p.notes or "").lower()]

    # Add computed cost for each product
    output = []
    for p in result[skip:skip + limit]:
        cost_data = get_product_cost_cached(p)
        output.append({
            **p.__dict__,
            "computed": cost_data,
            "images": [img for img in product_images if img.product_id == p.id],
            "variants": [v for v in product_variants if v.product_id == p.id],
        })

    return output


@router.get("/summary")
async def get_products_summary(user: Optional[User] = Depends(get_current_user_optional)):
    """Get product summary stats for dashboard widgets."""
    return {
        "total": len(products),
        "active": len([p for p in products if p.lifecycle_status in {"prototype", "experiment", "live"}]),
        "out_of_stock": 0,
    }


@public_router.get("/public/products")
async def public_list_products(
    category_id: Optional[int] = None,
    search: Optional[str] = None,
):
    """Public endpoint for landing page product listing."""
    filtered = [p for p in products if p.lifecycle_status == "live"]

    if search:
        search_lower = search.lower()
        filtered = [
            p for p in filtered
            if search_lower in p.name.lower() or search_lower in (p.notes or "").lower()
        ]
    if category_id:
        filtered = [p for p in filtered if category_id in (p.categories or [])]

    items = []
    for product in filtered:
        images = _public_images_for_product(product.id)
        primary = next((img for img in images if getattr(img, "is_primary", False)), images[0] if images else None)
        items.append({
            "id": product.id,
            "name": product.name,
            "base_price": product.base_price,
            "tags": product.tags or [],
            "image": primary.url if primary else _fallback_image(product.id),
            "tone": _tone_from_tags(product.tags),
        })

    return {
        "items": items,
        "total": len(items),
        "business_logo": getattr(settings, "business_logo", None),
    }


@public_router.get("/public/products/{product_id}")
async def public_get_product(product_id: int):
    """Public endpoint for landing page product detail."""
    product = next(
        (p for p in products if p.id == product_id and p.lifecycle_status == "live"),
        None,
    )
    if not product:
        raise HTTPException(status_code=404, detail="Sản phẩm không khả dụng")

    images = _public_images_for_product(product.id)
    image_urls = [img.url for img in images] or [_fallback_image(product.id)]

    return {
        "id": product.id,
        "name": product.name,
        "description": product.notes or "",
        "base_price": product.base_price,
        "tags": product.tags or [],
        "image": image_urls[0],
        "images": image_urls,
        "tone": _tone_from_tags(product.tags),
        "business_logo": getattr(settings, "business_logo", None),
    }


@router.get("/{product_id}")
async def get_product(
    product_id: int,
    user: Optional[User] = Depends(get_current_user_optional)
):
    """Get single product with full details."""
    product = find_product(product_id)
    cost_data = compute_product_cost(product)

    return {
        **product.__dict__,
        "computed": cost_data,
        "images": [img for img in product_images if img.product_id == product_id],
        "variants": [v for v in product_variants if v.product_id == product_id],
        "bundles": [b for b in product_bundles if b.bundle_product_id == product_id],
        "reviews": [r for r in product_reviews if r.product_id == product_id],
    }


@router.post("")
async def create_product(
    payload: ProductCreate,
    request: Request,
    user: User = Depends(get_current_user)
):
    """Create new product."""
    require_admin(user)
    new_id = max((p.id for p in products), default=0) + 1
    now = datetime.utcnow()

    product = Product(
        id=new_id,
        name=payload.name,
        base_price=payload.base_price,
        price=payload.base_price,
        time_minutes=payload.time_minutes or 0,
        wastage_percent=getattr(payload, "wastage_percent", 0) or 0,
        difficulty=payload.difficulty or 1,
        notes=payload.notes,
        tags=payload.tags or [],
        materials=[],
        categories=payload.categories or [],
        seasons=payload.seasons or [],
        priority=payload.priority or 1,
        role=payload.role or "core",
        lifecycle_status=payload.lifecycle_status or "idea",
        packaging_cost=payload.packaging_cost or 0,
        marketing_cost=payload.marketing_cost or 0,
        platform_fee_percent=payload.platform_fee_percent or 0,
        cost_breakdown=payload.cost_breakdown,
        created_at=now,
        updated_at=now,
    )

    # Add materials
    if payload.materials:
        for mat in payload.materials:
            usage = MaterialUsage(
                material_id=mat.material_id,
                quantity=mat.quantity,
                wastage_percent=getattr(mat, "wastage_percent", 0) or 0,
                usage_unit=getattr(mat, "usage_unit", None),
            )
            product.materials.append(usage)

    products.append(product)
    clear_product_cost_cache(new_id)

    save_product_sql(product)
    upsert_mongo("products", product.model_dump(mode="json") if hasattr(product, "model_dump") else product.__dict__)
    log_activity(user.id, "product", new_id, "create", {"name": product.name})
    await create_audit_log(user, "CREATE", "products", new_id, None, product.__dict__, request)
    return product


@router.put("/{product_id}")
async def update_product(
    product_id: int,
    payload: ProductCreate,
    request: Request,
    user: User = Depends(get_current_user)
):
    """Update existing product."""
    require_admin(user)
    product = find_product(product_id)
    before_data = product.__dict__.copy()

    product.name = payload.name
    product.base_price = payload.base_price
    product.price = payload.base_price
    product.time_minutes = payload.time_minutes or product.time_minutes
    product.wastage_percent = getattr(payload, "wastage_percent", 0) or 0
    product.difficulty = payload.difficulty or product.difficulty
    product.notes = payload.notes
    product.tags = payload.tags or []
    product.categories = payload.categories or []
    product.seasons = payload.seasons or []
    product.priority = payload.priority or product.priority
    product.role = payload.role or product.role
    product.lifecycle_status = payload.lifecycle_status or product.lifecycle_status
    product.packaging_cost = payload.packaging_cost or 0
    product.marketing_cost = payload.marketing_cost or 0
    product.platform_fee_percent = payload.platform_fee_percent or 0
    product.cost_breakdown = payload.cost_breakdown
    product.updated_at = datetime.utcnow()

    # Update materials
    if payload.materials is not None:
        product.materials = []
        for mat in payload.materials:
            usage = MaterialUsage(
                material_id=mat.material_id,
                quantity=mat.quantity,
                wastage_percent=getattr(mat, "wastage_percent", 0) or 0,
                usage_unit=getattr(mat, "usage_unit", None),
            )
            product.materials.append(usage)

    clear_product_cost_cache(product_id)

    save_product_sql(product)
    upsert_mongo("products", product.model_dump(mode="json") if hasattr(product, "model_dump") else product.__dict__)
    log_activity(user.id, "product", product_id, "update", {"name": product.name})
    await create_audit_log(user, "UPDATE", "products", product_id, before_data, product.__dict__, request)
    return product


@router.delete("/{product_id}")
async def delete_product(
    product_id: int,
    request: Request,
    user: User = Depends(get_current_user)
):
    """Delete product."""
    require_admin(user)
    product = find_product(product_id)
    before_data = product.__dict__.copy()

    products.remove(product)
    clear_product_cost_cache(product_id)

    with Session(engine) as session:
        row = session.get(ProductTable, product_id)
        if row:
            session.delete(row)
            session.commit()
    delete_mongo("products", "id", product_id)
    log_activity(user.id, "product", product_id, "delete", {"name": product.name})
    await create_audit_log(user, "DELETE", "products", product_id, before_data, None, request)
    return {"message": "Đã xóa sản phẩm"}


@router.post("/{product_id}/variants")
async def add_variant(
    product_id: int,
    payload: ProductVariantCreate,
    user: User = Depends(get_current_user)
):
    """Add product variant."""
    find_product(product_id)

    new_id = max((v.id for v in product_variants), default=0) + 1
    variant = ProductVariant(
        id=new_id,
        product_id=product_id,
        name=payload.name,
        sku=payload.sku,
        price_modifier=payload.price_modifier or 0,
        stock_quantity=payload.stock_quantity or 0,
        is_active=payload.is_active,
    )
    product_variants.append(variant)

    return variant


@router.post("/{product_id}/images")
async def add_image(
    product_id: int,
    payload: ProductImageCreate,
    user: User = Depends(get_current_user)
):
    """Add product image."""
    find_product(product_id)

    new_id = max((img.id for img in product_images), default=0) + 1
    image = ProductImage(
        id=new_id,
        product_id=product_id,
        url=payload.url,
        type=payload.type,
        is_primary=payload.is_primary or False,
        display_order=payload.display_order or 0,
    )
    product_images.append(image)

    return image


@router.post("/{product_id}/reviews")
async def add_review(
    product_id: int,
    payload: ProductReviewCreate,
    user: User = Depends(get_current_user)
):
    """Add product review."""
    find_product(product_id)

    new_id = max((r.id for r in product_reviews), default=0) + 1
    review = ProductReview(
        id=new_id,
        product_id=product_id,
        customer_id=payload.customer_id,
        customer_name=payload.customer_name,
        rating=payload.rating,
        content=payload.content,
        has_image=payload.has_image,
        images=payload.images,
        created_at=datetime.utcnow(),
    )
    product_reviews.append(review)

    return review


@router.get("/{product_id}/cost")
async def get_product_cost(
    product_id: int,
    user: Optional[User] = Depends(get_current_user_optional)
):
    """Get detailed cost breakdown for product."""
    product = find_product(product_id)
    return compute_product_cost(product)


@router.post("/{product_id}/adjust-finished")
async def adjust_finished_qty(
    product_id: int,
    payload: dict,
    user: User = Depends(get_current_user)
):
    """Adjust finished_qty for a product. payload: { quantity_change: int, note: str? }"""
    product = find_product(product_id)
    delta = int(payload.get("quantity_change", 0))
    if delta == 0:
        raise HTTPException(status_code=400, detail="Số lượng thay đổi không được bằng 0")
    product.finished_qty = max(0, getattr(product, "finished_qty", 0) + delta)
    from datetime import datetime
    product.updated_at = datetime.utcnow()
    save_product_sql(product)
    log_activity(user.id, "product", product_id, "adjust_finished", {
        "change": delta,
        "new_qty": product.finished_qty,
        "note": payload.get("note", "")
    })
    return {"ok": True, "product_id": product_id, "finished_qty": product.finished_qty}
