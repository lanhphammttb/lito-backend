import os
import base64
from fastapi import APIRouter, File, UploadFile, HTTPException, Depends
from pydantic import BaseModel
from models.user import User
from services.auth import get_current_user, require_admin

try:
    import cloudinary
    import cloudinary.uploader
except ImportError:
    cloudinary = None

router = APIRouter()

# Configure Cloudinary
if cloudinary is not None:
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")
    if not all([cloud_name, api_key, api_secret]):
        cloudinary = None
    else:
        cloudinary.config(
          cloud_name=cloud_name,
          api_key=api_key,
          api_secret=api_secret,
          secure=True
        )

class UploadResponse(BaseModel):
    url: str
    public_id: str

@router.post('/images', response_model=UploadResponse)
async def upload_image(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    require_admin(user)
    if file.content_type not in {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}:
        raise HTTPException(status_code=400, detail='File provided is not an image.')

    contents = await file.read(5 * 1024 * 1024 + 1)
    if not contents or len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail='Ảnh phải có dung lượng từ 1 byte đến 5 MB')
    if cloudinary is None:
        # The image URL is saved with the product in SQL, including on serverless.
        # No ephemeral disk files or separate storage configuration are required.
        if len(contents) > 2 * 1024 * 1024:
            raise HTTPException(status_code=413, detail='Ảnh tối đa 2 MB khi chưa cấu hình Cloudinary')
        return UploadResponse(url=f'data:{file.content_type};base64,{base64.b64encode(contents).decode()}', public_id='')

    try:
        result = cloudinary.uploader.upload(contents, folder='hala_handmade')
        return UploadResponse(url=result.get('secure_url'), public_id=result.get('public_id'))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
