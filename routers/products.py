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
from services.auth import get_current_user, require_admin
from services.product import (
    compute_product_cost, get_product_cost_cached, clear_product_cost_cache,
    find_product
)
from services.activity import log_activity, create_audit_log
from utils.datetime import utcnow
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


def save_variant_sql(variant: ProductVariant) -> ProductVariant:
    """Persist a product variant and return the normalized model."""
    with Session(engine) as session:
        row = session.get(ProductVariantTable, variant.id) if getattr(variant, "id", None) else None
        if row:
            row.product_id = variant.product_id
            row.name = variant.name
            row.sku = variant.sku
            row.price_modifier = variant.price_modifier
            row.stock_quantity = variant.stock_quantity
            row.is_active = variant.is_active
        else:
            row = ProductVariantTable(
                product_id=variant.product_id,
                name=variant.name,
                sku=variant.sku,
                price_modifier=variant.price_modifier,
                stock_quantity=variant.stock_quantity,
                is_active=variant.is_active,
            )
        session.add(row)
        session.commit()
        session.refresh(row)
        return ProductVariant(
            id=row.id,
            product_id=row.product_id,
            name=row.name,
            sku=row.sku,
            price_modifier=row.price_modifier,
            stock_quantity=row.stock_quantity,
            is_active=row.is_active,
            created_at=row.created_at,
        )


def save_image_sql(image: ProductImage) -> ProductImage:
    """Persist a product image and return the normalized model."""
    with Session(engine) as session:
        row = session.get(ProductImageTable, image.id) if getattr(image, "id", None) else None
        if row:
            row.product_id = image.product_id
            row.url = image.url
            row.type = image.type
            row.display_order = image.display_order
            row.is_primary = image.is_primary
            row.is_public = image.is_public
        else:
            row = ProductImageTable(
                product_id=image.product_id,
                url=image.url,
                type=image.type,
                display_order=image.display_order,
                is_primary=image.is_primary,
                is_public=image.is_public,
            )
        session.add(row)
        session.commit()
        session.refresh(row)
        return ProductImage(
            id=row.id,
            product_id=row.product_id,
            url=row.url,
            type=row.type,
            display_order=row.display_order,
            is_primary=row.is_primary,
            is_public=row.is_public,
            created_at=row.created_at,
        )


def save_review_sql(review: ProductReview) -> ProductReview:
    """Persist a product review and return the normalized model."""
    with Session(engine) as session:
        row = session.get(ProductReviewTable, review.id) if getattr(review, "id", None) else None
        if row:
            row.product_id = review.product_id
            row.customer_id = review.customer_id
            row.customer_name = review.customer_name
            row.rating = review.rating
            row.content = review.content
            row.has_image = review.has_image
            row.images_json = json.dumps(review.images or [])
        else:
            row = ProductReviewTable(
                product_id=review.product_id,
                customer_id=review.customer_id,
                customer_name=review.customer_name,
                rating=review.rating,
                content=review.content,
                has_image=review.has_image,
                images_json=json.dumps(review.images or []),
            )
        session.add(row)
        session.commit()
        session.refresh(row)
        return ProductReview(
            id=row.id,
            product_id=row.product_id,
            customer_id=row.customer_id,
            customer_name=row.customer_name,
            rating=row.rating,
            content=row.content,
            has_image=row.has_image,
            images=json.loads(row.images_json) if row.images_json else [],
            created_at=row.created_at,
        )


def save_bundle_sql(bundle: ProductBundle) -> ProductBundle:
    """Persist a product bundle and return the normalized model."""
    with Session(engine) as session:
        row = session.get(ProductBundleTable, bundle.id) if getattr(bundle, "id", None) else None
        if row:
            row.parent_product_id = bundle.parent_product_id
            row.child_product_id = bundle.child_product_id
            row.quantity = bundle.quantity
            row.discount_percent = bundle.discount_percent
        else:
            row = ProductBundleTable(
                parent_product_id=bundle.parent_product_id,
                child_product_id=bundle.child_product_id,
                quantity=bundle.quantity,
                discount_percent=bundle.discount_percent,
            )
        session.add(row)
        session.commit()
        session.refresh(row)
        return ProductBundle(
            id=row.id,
            parent_product_id=row.parent_product_id,
            child_product_id=row.child_product_id,
            quantity=row.quantity,
            discount_percent=row.discount_percent,
            created_at=row.created_at,
        )

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
    from sqlmodel import select
    with Session(engine) as session:
        images = session.exec(
            select(ProductImageTable)
            .where(ProductImageTable.product_id == product_id)
            .where(ProductImageTable.is_public == True)
        ).all()
        return sorted(images, key=lambda img: (not getattr(img, "is_primary", False), getattr(img, "display_order", 0)))


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
    user: User = Depends(get_current_user)
):
    """List all products with filtering from Database."""
    from sqlmodel import select
    with Session(engine) as session:
        statement = select(ProductTable)
        if status:
            statement = statement.where(ProductTable.lifecycle_status == status)
        if search:
            search_pattern = f"%{search}%"
            statement = statement.where(ProductTable.name.like(search_pattern))
            
        # Retrieve slightly more than limit if we need to filter by JSON categories
        statement = statement.offset(skip).limit(limit * 2 if category_id else limit)
        results = session.exec(statement).all()

        output = []
        for row in results:
            if len(output) >= limit:
                break
                
            p = find_product(row.id)
            
            if category_id and category_id not in p.categories:
                continue
                
            cost_data = get_product_cost_cached(p)
            images = session.exec(select(ProductImageTable).where(ProductImageTable.product_id == p.id)).all()
            variants = session.exec(select(ProductVariantTable).where(ProductVariantTable.product_id == p.id)).all()
            
            output.append({
                **p.model_dump(),
                "computed": cost_data,
                "images": [img.model_dump() for img in images],
                "variants": [v.model_dump() for v in variants],
            })

        return output


@router.get("/summary")
async def get_products_summary(user: User = Depends(get_current_user)):
    """Get product summary stats for dashboard widgets."""
    from sqlmodel import select
    with Session(engine) as session:
        all_products = session.exec(select(ProductTable)).all()
        return {
            "total": len(all_products),
            "active": sum(1 for p in all_products if p.lifecycle_status in {"prototype", "experiment", "live"}),
            "out_of_stock": 0,
        }


@public_router.get("/public/products")
async def public_list_products(
    category_id: Optional[int] = None,
    search: Optional[str] = None,
):
    """Public endpoint for landing page product listing directly from DB."""
    from sqlmodel import select
    with Session(engine) as session:
        statement = select(ProductTable).where(ProductTable.lifecycle_status == "live")
        if search:
            search_pattern = f"%{search}%"
            statement = statement.where(ProductTable.name.like(search_pattern))
            
        results = session.exec(statement).all()
        
        filtered = []
        for row in results:
            p = find_product(row.id)
            if category_id and category_id not in p.categories:
                continue
            filtered.append(p)

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
    """Public endpoint for landing page product detail from DB."""
    try:
        product = find_product(product_id)
        if product.lifecycle_status != "live":
            raise HTTPException(status_code=404, detail="Sản phẩm không khả dụng")
    except HTTPException:
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
    user: User = Depends(get_current_user)
):
    """Get single product with full details from DB."""
    product = find_product(product_id)
    cost_data = compute_product_cost(product)
    
    from sqlmodel import select
    with Session(engine) as session:
        images = session.exec(select(ProductImageTable).where(ProductImageTable.product_id == product_id)).all()
        variants = session.exec(select(ProductVariantTable).where(ProductVariantTable.product_id == product_id)).all()
        bundles = session.exec(select(ProductBundleTable).where(ProductBundleTable.parent_product_id == product_id)).all()
        reviews = session.exec(select(ProductReviewTable).where(ProductReviewTable.product_id == product_id)).all()

        return {
            **product.model_dump(),
            "computed": cost_data,
            "images": [img.model_dump() for img in images],
            "variants": [v.model_dump() for v in variants],
            "bundles": [b.model_dump() for b in bundles],
            "reviews": [r.model_dump() for r in reviews],
        }


@router.post("")
async def create_product(
    payload: ProductCreate,
    request: Request,
    user: User = Depends(get_current_user)
):
    """Create new product."""
    require_admin(user)
    
    from sqlmodel import Session, select
    with Session(engine) as session:
        max_id_val = session.exec(select(ProductTable.id).order_by(ProductTable.id.desc())).first()
        new_id = (max_id_val or 0) + 1

    now = utcnow()

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
    product.updated_at = utcnow()

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
    before_data = product.model_dump() if hasattr(product, "model_dump") else product.__dict__.copy()

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

    variant = ProductVariant(
        id=0,
        product_id=product_id,
        name=payload.name,
        sku=payload.sku,
        price_modifier=payload.price_modifier or 0,
        stock_quantity=payload.stock_quantity or 0,
        is_active=payload.is_active,
    )
    persisted_variant = save_variant_sql(variant)

    return persisted_variant


@router.post("/{product_id}/images")
async def add_image(
    product_id: int,
    payload: ProductImageCreate,
    user: User = Depends(get_current_user)
):
    """Add product image."""
    find_product(product_id)

    image = ProductImage(
        id=0,
        product_id=product_id,
        url=payload.url,
        type=payload.type,
        is_primary=payload.is_primary or False,
        display_order=payload.display_order or 0,
    )
    persisted_image = save_image_sql(image)

    return persisted_image


@router.post("/{product_id}/reviews")
async def add_review(
    product_id: int,
    payload: ProductReviewCreate,
    user: User = Depends(get_current_user)
):
    """Add product review."""
    find_product(product_id)

    review = ProductReview(
        id=0,
        product_id=product_id,
        customer_id=payload.customer_id,
        customer_name=payload.customer_name,
        rating=payload.rating,
        content=payload.content,
        has_image=payload.has_image,
        images=payload.images,
        created_at=utcnow(),
    )
    persisted_review = save_review_sql(review)

    return persisted_review


@router.get("/{product_id}/cost")
async def get_product_cost(
    product_id: int,
    user: User = Depends(get_current_user)
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
    product.updated_at = utcnow()
    save_product_sql(product)
    log_activity(user.id, "product", product_id, "adjust_finished", {
        "change": delta,
        "new_qty": product.finished_qty,
        "note": payload.get("note", "")
    })
    return {"ok": True, "product_id": product_id, "finished_qty": product.finished_qty}
