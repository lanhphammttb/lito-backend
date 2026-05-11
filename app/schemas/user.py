from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from datetime import datetime

class UserBase(BaseModel):
    name: str
    email: EmailStr
    role: str = "ADMIN"
    is_owner: bool = False

class UserCreate(UserBase):
    password: str = Field(..., min_length=6, max_length=128)

class UserPublic(UserBase):
    id: int
    created_at: datetime
    last_login_at: Optional[datetime] = None

class User(UserPublic):
    password_hash: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
