import os
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
    if cloudinary is None:
        raise HTTPException(
            status_code=503,
            detail='Cloudinary is not configured. Set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET.',
        )

    if not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail='File provided is not an image.')

    try:
        contents = await file.read()
        result = cloudinary.uploader.upload(contents, folder='hala_handmade')
        return UploadResponse(url=result.get('secure_url'), public_id=result.get('public_id'))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
