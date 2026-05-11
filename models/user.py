"""User models."""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from sqlmodel import SQLModel, Field as SQLField
from utils.datetime import utcnow


class User(BaseModel):
    """User domain model."""
    id: int
    name: str
    email: str
    password_hash: str
    role: str = "ADMIN"
    is_owner: bool = False
    created_at: datetime = utcnow()
    last_login_at: Optional[datetime] = None


class UserTable(SQLModel, table=True):
    """User database table."""
    __tablename__ = "users"
    
    id: Optional[int] = SQLField(default=None, primary_key=True)
    name: str
    email: str = SQLField(unique=True, index=True)
    password_hash: str
    role: str = "ADMIN"
    is_owner: bool = False
    created_at: datetime = SQLField(default_factory=utcnow)
    last_login_at: Optional[datetime] = None


class UserPublic(BaseModel):
    """Public user response (without password)."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: str
    is_owner: bool
    created_at: datetime
    last_login_at: Optional[datetime]

