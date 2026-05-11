import os
from fastapi import APIRouter, File, UploadFile, HTTPException
from pydantic import BaseModel

try:
    import cloudinary
    import cloudinary.uploader
except ImportError:
    cloudinary = None

router = APIRouter()

# Configure Cloudinary
if cloudinary is not None:
    cloudinary.config(
      cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME', 'dntwvpygj'),
      api_key = os.getenv('CLOUDINARY_API_KEY', '861189712476276'),
      api_secret = os.getenv('CLOUDINARY_API_SECRET', 'FpTwg-YcAKiu2PaG4CseUP-BkjY'),
      secure = True
    )

class UploadResponse(BaseModel):
    url: str
    public_id: str

@router.post('/images', response_model=UploadResponse)
async def upload_image(file: UploadFile = File(...)):
    if cloudinary is None:
        raise HTTPException(status_code=503, detail='Cloudinary dependency is not installed.')

    if not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail='File provided is not an image.')

    try:
        contents = await file.read()
        result = cloudinary.uploader.upload(contents, folder='hala_handmade')
        return UploadResponse(url=result.get('secure_url'), public_id=result.get('public_id'))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
