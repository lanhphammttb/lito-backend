"""Auth schemas."""
from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    """Login request payload."""
    email: str
    password: str


class TokenResponse(BaseModel):
    """Token response."""
    access_token: str
    token_type: str = "bearer"
