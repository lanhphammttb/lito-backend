"""Legacy product-related root routes."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from config.database import engine
from models.content import DemandSignal, DemandSignalTable
from models.product import (
    ProductBundle,
    ProductBundleTable,
    ProductImage,
    ProductImageTable,
    ProductReview,
    ProductReviewTable,
    ProductVariant,
    ProductVariantTable,
)
from models.user import User
from routers.content import demand_signals
from routers.products import (
    product_bundles,
    product_images,
    product_reviews,
    product_variants,
    save_bundle_sql,
    save_image_sql,
    save_review_sql,
    save_variant_sql,
)
from services.auth import get_current_user
from utils.datetime import utcnow

router = APIRouter()


def _parse_date(value, fallback: date) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        return date.fromisoformat(value[:10])
    return fallback


def _variant_from_row(row: ProductVariantTable) -> ProductVariant:
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


@router.get("/demand")
async def list_demand_signals(product_id: int = None, user: User = Depends(get_current_user)):
    """Get demand signals."""
    with Session(engine) as session:
        stmt = select(DemandSignalTable).order_by(DemandSignalTable.week_of.desc())
        if product_id:
            stmt = stmt.where(DemandSignalTable.product_id == product_id)
        rows = session.exec(stmt).all()
    return [
        {
            "id": row.id,
            "product_id": row.product_id,
            "week_of": str(row.week_of),
            "views": row.views,
            "inquiries": row.inquiries,
            "saves": row.saves,
        }
        for row in rows
    ]


@router.post("/demand")
async def create_demand_signal(payload: dict, user: User = Depends(get_current_user)):
    """Create demand signal."""
    row = DemandSignalTable(
        product_id=int(payload.get("product_id")),
        week_of=_parse_date(payload.get("week_of"), date.today()),
        views=int(payload.get("views", 0) or 0),
        inquiries=int(payload.get("inquiries", 0) or 0),
        saves=int(payload.get("saves", 0) or 0),
        created_by=user.id,
        created_at=utcnow(),
    )
    with Session(engine) as session:
        session.add(row)
        session.commit()
        session.refresh(row)
    signal = DemandSignal(
        id=row.id,
        product_id=row.product_id,
        week_of=row.week_of,
        views=row.views,
        inquiries=row.inquiries,
        saves=row.saves,
        created_by=row.created_by,
        created_at=row.created_at,
    )
    demand_signals.append(signal)
    return {"id": signal.id, "product_id": signal.product_id}


@router.get("/bundles")
async def list_bundles(parent_product_id: int = None, user: User = Depends(get_current_user)):
    """List product bundles."""
    with Session(engine) as session:
        stmt = select(ProductBundleTable)
        if parent_product_id:
            stmt = stmt.where(ProductBundleTable.parent_product_id == parent_product_id)
        rows = session.exec(stmt).all()
    return [
        {
            "id": row.id,
            "parent_product_id": row.parent_product_id,
            "child_product_id": row.child_product_id,
            "quantity": row.quantity,
            "discount_percent": row.discount_percent,
        }
        for row in rows
    ]


@router.post("/bundles")
async def create_bundle(payload: dict, user: User = Depends(get_current_user)):
    """Create product bundle."""
    bundle = ProductBundle(
        id=0, parent_product_id=payload.get("parent_product_id", payload.get("bundle_product_id")),
        child_product_id=payload.get("child_product_id"), quantity=payload.get("quantity", 1),
    )
    persisted_bundle = save_bundle_sql(bundle)
    product_bundles.append(persisted_bundle)
    return {"id": persisted_bundle.id}


@router.get("/reviews")
async def list_reviews(product_id: int = None, user: User = Depends(get_current_user)):
    """List product reviews."""
    with Session(engine) as session:
        stmt = select(ProductReviewTable).order_by(ProductReviewTable.created_at.desc())
        if product_id:
            stmt = stmt.where(ProductReviewTable.product_id == product_id)
        rows = session.exec(stmt).all()
    return [
        {
            "id": row.id,
            "product_id": row.product_id,
            "rating": row.rating,
            "content": row.content,
            "customer_name": row.customer_name,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.post("/reviews")
async def create_review(payload: dict, user: User = Depends(get_current_user)):
    """Create product review."""
    review = ProductReview(
        id=0, product_id=payload.get("product_id"), rating=payload.get("rating", 5),
        content=payload.get("content", payload.get("comment")), customer_name=payload.get("customer_name", "Khách hàng"),
        created_at=utcnow(),
    )
    persisted_review = save_review_sql(review)
    product_reviews.append(persisted_review)
    return {"id": persisted_review.id}


@router.get("/images")
async def list_product_images(product_id: int = None, user: User = Depends(get_current_user)):
    """List product images."""
    with Session(engine) as session:
        stmt = select(ProductImageTable).order_by(ProductImageTable.display_order)
        if product_id:
            stmt = stmt.where(ProductImageTable.product_id == product_id)
        rows = session.exec(stmt).all()
    return [
        {
            "id": row.id,
            "product_id": row.product_id,
            "url": row.url,
            "type": row.type,
            "display_order": row.display_order,
            "is_primary": row.is_primary,
            "is_public": row.is_public,
        }
        for row in rows
    ]


@router.post("/images")
async def create_product_image(payload: dict, user: User = Depends(get_current_user)):
    """Create product image."""
    image = ProductImage(
        id=0, product_id=payload.get("product_id"), url=payload.get("url"),
        is_primary=payload.get("is_primary", False),
    )
    persisted_image = save_image_sql(image)
    product_images.append(persisted_image)
    return {"id": persisted_image.id}


@router.get("/{product_id}/history")
async def get_product_history(product_id: int, user: User = Depends(get_current_user)):
    """Get product history."""
    return {"price_changes": [], "lifecycle": []}


@router.get("/variants")
async def list_variants(product_id: int = None, user: User = Depends(get_current_user)):
    """List product variants."""
    with Session(engine) as session:
        stmt = select(ProductVariantTable)
        if product_id:
            stmt = stmt.where(ProductVariantTable.product_id == product_id)
        rows = session.exec(stmt).all()
    return [
        {
            "id": row.id,
            "product_id": row.product_id,
            "name": row.name,
            "sku": row.sku,
            "price_modifier": row.price_modifier,
            "stock_quantity": row.stock_quantity,
            "is_active": row.is_active,
        }
        for row in rows
    ]


@router.post("/variants")
async def create_variant(payload: dict, user: User = Depends(get_current_user)):
    """Create product variant."""
    variant = ProductVariant(
        id=0, product_id=payload.get("product_id"), name=payload.get("name"),
        sku=payload.get("sku"), price_modifier=payload.get("price_modifier", payload.get("price_adjustment", 0)),
        stock_quantity=payload.get("stock_quantity", 0),
        is_active=payload.get("is_active", True),
    )
    persisted_variant = save_variant_sql(variant)
    product_variants.append(persisted_variant)
    return {"id": persisted_variant.id}


@router.put("/variants/{variant_id}")
async def update_variant(variant_id: int, payload: dict, user: User = Depends(get_current_user)):
    """Update variant."""
    with Session(engine) as session:
        row = session.get(ProductVariantTable, variant_id)
    if not row:
        raise HTTPException(status_code=404, detail="Variant không tồn tại")
    variant = _variant_from_row(row)
    field_aliases = {"price_adjustment": "price_modifier"}
    for key in ["name", "sku", "price_modifier", "price_adjustment", "stock_quantity", "is_active"]:
        if key in payload:
            setattr(variant, field_aliases.get(key, key), payload[key])
    persisted_variant = save_variant_sql(variant)
    existing_index = next((idx for idx, item in enumerate(product_variants) if item.id == variant_id), None)
    if existing_index is None:
        product_variants.append(persisted_variant)
    else:
        product_variants[existing_index] = persisted_variant
    return {"id": variant.id}


@router.delete("/variants/{variant_id}")
async def delete_variant(variant_id: int, user: User = Depends(get_current_user)):
    """Delete variant."""
    product_variants[:] = [v for v in product_variants if v.id != variant_id]
    with Session(engine) as session:
        row = session.get(ProductVariantTable, variant_id)
        if row:
            session.delete(row)
            session.commit()
    return {"success": True}
