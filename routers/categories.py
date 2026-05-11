"""Category routes."""
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from config.database import engine
from models.user import User
from models.category import Category, CategoryTable
from schemas.category import CategoryCreate
from services.auth import get_current_user, get_current_user_optional
from services.activity import log_activity

router = APIRouter()

# In-memory data store
categories: List[Category] = []


@router.get("")
async def list_categories(
    skip: int = 0,
    limit: int = 100,
    parent_id: Optional[int] = None,
    user: Optional[User] = Depends(get_current_user_optional)
):
    """List all categories."""
    result = categories[:]
    
    if parent_id is not None:
        result = [c for c in result if c.parent_id == parent_id]
    
    return result[skip:skip + limit]


@router.get("/tree")
async def get_category_tree(user: Optional[User] = Depends(get_current_user_optional)):
    """Get categories as tree structure."""
    
    def build_tree(parent_id=None):
        children = [c for c in categories if c.parent_id == parent_id]
        return [
            {
                **c.__dict__,
                "children": build_tree(c.id)
            }
            for c in children
        ]
    
    return build_tree(None)


@router.get("/{category_id}")
async def get_category(
    category_id: int,
    user: Optional[User] = Depends(get_current_user_optional)
):
    """Get single category."""
    category = next((c for c in categories if c.id == category_id), None)
    if not category:
        raise HTTPException(status_code=404, detail="Category không tồn tại")
    return category


@router.post("")
async def create_category(
    payload: CategoryCreate,
    user: User = Depends(get_current_user)
):
    """Create new category."""
    # Check parent exists if specified
    if payload.parent_id:
        parent = next((c for c in categories if c.id == payload.parent_id), None)
        if not parent:
            raise HTTPException(status_code=400, detail="Parent category không tồn tại")
    
    new_id = max((c.id for c in categories), default=0) + 1
    
    category = Category(
        id=new_id,
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        parent_id=payload.parent_id,
        image_url=payload.image_url,
        sort_order=payload.sort_order or 0,
        created_at=datetime.utcnow(),
    )
    categories.append(category)
    
    # Save to SQL
    with Session(engine) as session:
        session.add(CategoryTable(
            name=category.name,
            slug=category.slug,
            description=category.description,
            parent_id=category.parent_id,
            image_url=category.image_url,
            sort_order=category.sort_order,
            created_at=category.created_at,
        ))
        session.commit()
    
    log_activity(user.id, "category", new_id, "create", {"name": category.name})
    
    return category


@router.put("/{category_id}")
async def update_category(
    category_id: int,
    payload: CategoryCreate,
    user: User = Depends(get_current_user)
):
    """Update category."""
    category = next((c for c in categories if c.id == category_id), None)
    if not category:
        raise HTTPException(status_code=404, detail="Category không tồn tại")
    
    # Prevent circular reference
    if payload.parent_id == category_id:
        raise HTTPException(status_code=400, detail="Category không thể là parent của chính nó")
    
    if payload.parent_id:
        parent = next((c for c in categories if c.id == payload.parent_id), None)
        if not parent:
            raise HTTPException(status_code=400, detail="Parent category không tồn tại")
    
    category.name = payload.name
    category.slug = payload.slug
    category.description = payload.description
    category.parent_id = payload.parent_id
    category.image_url = payload.image_url
    category.sort_order = payload.sort_order or category.sort_order
    
    # Update in SQL
    with Session(engine) as session:
        row = session.get(CategoryTable, category_id)
        if row:
            row.name = category.name
            row.slug = category.slug
            row.description = category.description
            row.parent_id = category.parent_id
            row.image_url = category.image_url
            row.sort_order = category.sort_order
            session.add(row)
            session.commit()
    
    log_activity(user.id, "category", category_id, "update", {"name": category.name})
    
    return category


@router.delete("/{category_id}")
async def delete_category(
    category_id: int,
    user: User = Depends(get_current_user)
):
    """Delete category."""
    category = next((c for c in categories if c.id == category_id), None)
    if not category:
        raise HTTPException(status_code=404, detail="Category không tồn tại")
    
    # Check for children
    children = [c for c in categories if c.parent_id == category_id]
    if children:
        raise HTTPException(status_code=400, detail="Không thể xóa category có sub-categories")
    
    categories.remove(category)
    
    # Delete from SQL
    with Session(engine) as session:
        row = session.get(CategoryTable, category_id)
        if row:
            session.delete(row)
            session.commit()
    
    log_activity(user.id, "category", category_id, "delete", {})
    
    return {"message": "Đã xóa category"}
