import cloudinary
import cloudinary.uploader
import cloudinary.api
from fastapi import APIRouter, File, UploadFile, Depends, HTTPException
from fastapi.responses import JSONResponse
import os
from pydantic import BaseModel

router = APIRouter()

# Configure Cloudinary
cloudinary.config(
  cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "dntwvpygj"),
  api_key = os.getenv("CLOUDINARY_API_KEY", "861189712476276"),
  api_secret = os.getenv("CLOUDINARY_API_SECRET", "FpTwg-YcAKiu2PaG4CseUP-BkjY"),
  secure = True
)

class UploadResponse(BaseModel):
    url: str
    public_id: str

@router.post("/images", response_model=UploadResponse)
async def upload_image(file: UploadFile = File(...)):
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File provided is not an image.")
    
    try:
        contents = await file.read()
        # Upload context to Cloudinary
        result = cloudinary.uploader.upload(contents, folder="hala_handmade")
        return UploadResponse(url=result.get("secure_url"), public_id=result.get("public_id"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
