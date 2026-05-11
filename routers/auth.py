"""Authentication routes."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select

from config.database import engine
from schemas.auth import LoginRequest, TokenResponse
from services.auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    find_user_by_email,
)
from models.user import User, UserTable

router = APIRouter()


def _do_login(email: str, password: str) -> TokenResponse:
    """Internal login logic."""
    user = find_user_by_email(email)
    if not user:
        raise HTTPException(status_code=401, detail="Email không tồn tại")
    
    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Mật khẩu sai")
    
    # Update last login
    with Session(engine) as session:
        stmt = select(UserTable).where(UserTable.id == user.id)
        row = session.exec(stmt).first()
        if row:
            row.last_login_at = datetime.utcnow()
            session.add(row)
            session.commit()
    
    token = create_access_token({"sub": user.id, "role": user.role})
    return TokenResponse(access_token=token, token_type="bearer")


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    """Login with JSON body (email/password)."""
    return _do_login(payload.email, payload.password)


@router.post("/token", response_model=TokenResponse)
async def login_form(form: OAuth2PasswordRequestForm = Depends()):
    """Login with OAuth2 form (username/password) - for Swagger UI."""
    return _do_login(form.username, form.password)


@router.post("/register", response_model=TokenResponse)
async def register(payload: LoginRequest):
    """Register new user."""
    if find_user_by_email(payload.email):
        raise HTTPException(status_code=400, detail="Email đã tồn tại")
    
    with Session(engine) as session:
        new_user = UserTable(
            name=payload.email.split("@")[0],
            email=payload.email,
            password_hash=hash_password(payload.password),
            role="USER",
            is_owner=False,
            created_at=datetime.utcnow(),
        )
        session.add(new_user)
        session.commit()
        session.refresh(new_user)
        
        token = create_access_token({"sub": new_user.id, "role": new_user.role})
        return TokenResponse(access_token=token, token_type="bearer")


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    """Get current user info."""
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "is_owner": user.is_owner,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
    }


@router.put("/me")
async def update_me(
    payload: dict,
    user: User = Depends(get_current_user)
):
    """Update current user profile."""
    with Session(engine) as session:
        stmt = select(UserTable).where(UserTable.id == user.id)
        row = session.exec(stmt).first()
        if row:
            if "name" in payload:
                row.name = payload["name"]
            if "password" in payload and payload["password"]:
                row.password_hash = hash_password(payload["password"])
            session.add(row)
            session.commit()
    
    return {"message": "Cập nhật thành công"}


@router.post("/change-password")
async def change_password(
    payload: dict,
    user: User = Depends(get_current_user)
):
    """Change user password."""
    old_password = payload.get("old_password")
    new_password = payload.get("new_password")
    
    if not old_password or not new_password:
        raise HTTPException(status_code=400, detail="Thiếu mật khẩu cũ hoặc mới")
    
    if not verify_password(old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Mật khẩu cũ không đúng")
    
    with Session(engine) as session:
        stmt = select(UserTable).where(UserTable.id == user.id)
        row = session.exec(stmt).first()
        if row:
            row.password_hash = hash_password(new_password)
            session.add(row)
            session.commit()
    
    return {"message": "Đổi mật khẩu thành công"}
