"""Category routes."""
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from config.database import engine
from models.user import User
from models.category import Category, CategoryTable
from schemas.category import CategoryCreate
from services.auth import get_current_user
from services.activity import log_activity

router = APIRouter()

from sqlmodel import select

categories: List[Category] = []


@router.get("")
async def list_categories(
    skip: int = 0,
    limit: int = 100,
    parent_id: Optional[int] = None,
    user: User = Depends(get_current_user)
):
    """List all categories from DB."""
    with Session(engine) as session:
        statement = select(CategoryTable)
        if parent_id is not None:
            statement = statement.where(CategoryTable.parent_id == parent_id)
        
        statement = statement.order_by(CategoryTable.display_order.asc())
        results = session.exec(statement.offset(skip).limit(limit)).all()
        return [r.model_dump() for r in results]


@router.get("/tree")
async def get_category_tree(user: User = Depends(get_current_user)):
    """Get categories as tree structure from DB."""
    with Session(engine) as session:
        all_categories = session.exec(select(CategoryTable).order_by(CategoryTable.display_order.asc())).all()
        
        def build_tree(parent_id=None):
            children = [c for c in all_categories if c.parent_id == parent_id]
            return [
                {
                    **c.model_dump(),
                    "children": build_tree(c.id)
                }
                for c in children
            ]
        
        return build_tree(None)


@router.get("/{category_id}")
async def get_category(
    category_id: int,
    user: User = Depends(get_current_user)
):
    """Get single category from DB."""
    with Session(engine) as session:
        row = session.get(CategoryTable, category_id)
        if not row:
            raise HTTPException(status_code=404, detail="Category không tồn tại")
        return row.model_dump()


@router.post("")
async def create_category(
    payload: CategoryCreate,
    user: User = Depends(get_current_user)
):
    """Create new category in DB."""
    with Session(engine) as session:
        if payload.parent_id:
            parent = session.get(CategoryTable, payload.parent_id)
            if not parent:
                raise HTTPException(status_code=400, detail="Parent category không tồn tại")
        
        row = CategoryTable(
            name=payload.name,
            description=payload.description,
            parent_id=payload.parent_id,
            display_order=getattr(payload, 'sort_order', None) or 0,
            created_at=datetime.utcnow(),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        
        log_activity(user.id, "category", row.id, "create", {"name": row.name})
        return row.model_dump()


@router.put("/{category_id}")
async def update_category(
    category_id: int,
    payload: CategoryCreate,
    user: User = Depends(get_current_user)
):
    """Update category in DB."""
    if payload.parent_id == category_id:
        raise HTTPException(status_code=400, detail="Category không thể là parent của chính nó")

    with Session(engine) as session:
        row = session.get(CategoryTable, category_id)
        if not row:
            raise HTTPException(status_code=404, detail="Category không tồn tại")
            
        if payload.parent_id:
            parent = session.get(CategoryTable, payload.parent_id)
            if not parent:
                raise HTTPException(status_code=400, detail="Parent category không tồn tại")
                
        row.name = payload.name
        row.slug = payload.slug
        row.description = payload.description
        row.parent_id = payload.parent_id
        row.image_url = payload.image_url
        row.display_order = payload.sort_order or row.display_order
        
        session.add(row)
        session.commit()
        session.refresh(row)
        
        log_activity(user.id, "category", category_id, "update", {"name": row.name})
        return row.model_dump()


@router.delete("/{category_id}")
async def delete_category(
    category_id: int,
    user: User = Depends(get_current_user)
):
    """Delete category from DB."""
    with Session(engine) as session:
        row = session.get(CategoryTable, category_id)
        if not row:
            raise HTTPException(status_code=404, detail="Category không tồn tại")
            
        children = session.exec(select(CategoryTable).where(CategoryTable.parent_id == category_id)).all()
        if children:
            raise HTTPException(status_code=400, detail="Không thể xóa category có sub-categories")
            
        session.delete(row)
        session.commit()
        
    log_activity(user.id, "category", category_id, "delete", {})
    return {"message": "Đã xóa category"}
