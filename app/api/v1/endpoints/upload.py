import cloudinary
import cloudinary.uploader
import cloudinary.api
from fastapi import APIRouter, File, UploadFile, Depends, HTTPException
import os
from pydantic import BaseModel
from models.user import User
from services.auth import get_current_user, require_admin

router = APIRouter()

# Configure Cloudinary
cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
api_key = os.getenv("CLOUDINARY_API_KEY")
api_secret = os.getenv("CLOUDINARY_API_SECRET")

if all([cloud_name, api_key, api_secret]):
    cloudinary.config(
      cloud_name=cloud_name,
      api_key=api_key,
      api_secret=api_secret,
      secure=True
    )
else:
    cloudinary = None

class UploadResponse(BaseModel):
    url: str
    public_id: str

@router.post("/images", response_model=UploadResponse)
async def upload_image(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    require_admin(user)
    if cloudinary is None:
        raise HTTPException(
            status_code=503,
            detail="Cloudinary is not configured. Set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET.",
        )
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File provided is not an image.")
    
    try:
        contents = await file.read()
        # Upload context to Cloudinary
        result = cloudinary.uploader.upload(contents, folder="hala_handmade")
        return UploadResponse(url=result.get("secure_url"), public_id=result.get("public_id"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
