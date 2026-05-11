"""Settings routes."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from config.database import engine
from config.settings import settings as app_settings
from models.user import User
from models.settings_table import SettingsTable
from services.auth import get_current_user, require_admin
from services.product import clear_product_cost_cache

router = APIRouter()


@router.get("")
async def get_settings(user: User = Depends(get_current_user)):
    """Get application settings."""
    if user.role == "ADMIN":
        return app_settings.admin_dump()
    return app_settings.public_dump()


@router.put("")
async def update_settings(
    payload: dict,
    user: User = Depends(get_current_user)
):
    """Update application settings."""
    require_admin(user)

    # Update ALL fields in in-memory settings
    for key, value in payload.items():
        if value is None:
            continue
        if hasattr(app_settings, key):
            field_type = type(getattr(app_settings, key))
            try:
                if field_type == float:
                    setattr(app_settings, key, float(value))
                elif field_type == int:
                    setattr(app_settings, key, int(value))
                elif field_type == bool:
                    setattr(app_settings, key, bool(value))
                else:
                    setattr(app_settings, key, value)
            except (ValueError, TypeError):
                setattr(app_settings, key, value)

    # Persist to DB
    with Session(engine) as session:
        row = session.exec(select(SettingsTable).where(SettingsTable.id == 1)).first()
        if not row:
            row = SettingsTable(id=1)
        for key, value in payload.items():
            if hasattr(row, key):
                setattr(row, key, value)
        session.add(row)
        session.commit()

    if "hourly_rate" in payload:
        clear_product_cost_cache()

    return app_settings.admin_dump() if user.role == "ADMIN" else app_settings.public_dump()


@router.patch("")
async def patch_settings(
    payload: dict,
    user: User = Depends(get_current_user)
):
    """Patch alias for settings update."""
    return await update_settings(payload, user)


@router.get("/{key}")
async def get_setting(key: str, user: User = Depends(get_current_user)):
    """Get specific setting value."""
    if user.role != "ADMIN" and key not in app_settings.public_dump():
        raise HTTPException(status_code=403, detail=f"Setting {key} requires admin access")
    with Session(engine) as session:
        row = session.exec(select(SettingsTable).where(SettingsTable.id == 1)).first()
        if row and hasattr(row, key):
            if user.role != "ADMIN" and key not in app_settings.public_dump():
                raise HTTPException(status_code=403, detail=f"Setting {key} requires admin access")
            return {"key": key, "value": getattr(row, key)}
    
    # Check in-memory settings
    if hasattr(app_settings, key):
        return {"key": key, "value": getattr(app_settings, key)}
    
    raise HTTPException(status_code=404, detail=f"Setting {key} không tồn tại")


@router.put("/{key}")
async def set_setting(
    key: str,
    payload: dict,
    user: User = Depends(get_current_user)
):
    """Set specific setting value."""
    require_admin(user)
    
    value = payload.get("value")
    if value is None:
        raise HTTPException(status_code=400, detail="Thiếu giá trị")
    
    # Update in-memory if applicable
    if hasattr(app_settings, key):
        setattr(app_settings, key, value)
    
    # Persist to database (single settings row)
    with Session(engine) as session:
        row = session.exec(select(SettingsTable).where(SettingsTable.id == 1)).first()
        if not row:
            row = SettingsTable(id=1)
        if hasattr(row, key):
            setattr(row, key, value)
        else:
            raise HTTPException(status_code=404, detail=f"Setting {key} không tồn tại")
        session.add(row)
        session.commit()

    if key == "hourly_rate":
        clear_product_cost_cache()

    return {"message": f"Đã cập nhật {key}"}
