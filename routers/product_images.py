from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from config.database import engine
from models.user import User
from models.product import ProductImageTable
from services.auth import get_current_user, require_admin

router = APIRouter()

@router.put('/{image_id}/set-primary')
async def set_primary_product_image(image_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    with Session(engine) as session:
        target_img = session.exec(select(ProductImageTable).where(ProductImageTable.id == image_id)).first()
        if not target_img:
            raise HTTPException(status_code=404, detail='Ảnh không tồn tại')

        # Reset all others for this product
        stmt = select(ProductImageTable).where(ProductImageTable.product_id == target_img.product_id)
        for p_img in session.exec(stmt).all():
            if p_img.id == image_id:
                p_img.is_primary = True
                p_img.is_public = True
            else:
                p_img.is_primary = False
            session.add(p_img)
            
        session.commit()
    return {'detail': 'Đã đặt làm ảnh chính'}

@router.put('/{image_id}/toggle-public')
async def toggle_public_product_image(image_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    with Session(engine) as session:
        target_img = session.exec(select(ProductImageTable).where(ProductImageTable.id == image_id)).first()
        if not target_img:
            raise HTTPException(status_code=404, detail='Ảnh không tồn tại')

        target_img.is_public = not target_img.is_public
        if not target_img.is_public and target_img.is_primary:
            target_img.is_primary = False

        session.add(target_img)
        session.commit()
        return {'detail': 'Đã cập nhật trạng thái hiển thị', 'is_public': target_img.is_public}

@router.delete('/{image_id}')
async def delete_product_image(image_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    with Session(engine) as session:
        target_img = session.exec(select(ProductImageTable).where(ProductImageTable.id == image_id)).first()
        if not target_img:
            raise HTTPException(status_code=404, detail='Ảnh không tồn tại')
            
        session.delete(target_img)
        session.commit()
        return {'detail': 'Đã xóa ảnh'}
