"""Authentication routes."""
from fastapi import APIRouter, Depends, HTTPException, Body, Request
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select
import httpx

from config.database import engine
from config.settings import settings as app_settings, FRONTEND_URL
from models.settings_table import SettingsTable
from schemas.auth import LoginRequest, TokenResponse
from services.auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    find_user_by_email,
)
from models.user import User, UserTable
from utils.datetime import utcnow

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
            row.last_login_at = utcnow()
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
            created_at=utcnow(),
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


@router.get("/facebook")
async def facebook_oauth_start(request: Request):
    """Redirect user to Facebook OAuth consent screen."""
    app_id = getattr(app_settings, "facebook_app_id", None)
    if not app_id:
        return RedirectResponse(f"{FRONTEND_URL}/settings?facebook_error=Chưa+cấu+hình+Facebook+App+ID")
    redirect_uri = str(request.base_url).rstrip("/") + "/auth/facebook/callback"
    scope = "pages_show_list,pages_read_engagement,pages_read_user_content,instagram_basic,instagram_manage_insights"
    fb_url = (
        f"https://www.facebook.com/dialog/oauth"
        f"?client_id={app_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scope}"
        f"&response_type=code"
    )
    return RedirectResponse(fb_url)


@router.get("/facebook/callback")
async def facebook_oauth_callback(request: Request, code: str = None, error: str = None):
    """Handle Facebook OAuth callback, save page token to settings."""
    if error or not code:
        return RedirectResponse(f"{FRONTEND_URL}/settings?facebook_error={error or 'cancelled'}")

    app_id = getattr(app_settings, "facebook_app_id", None)
    app_secret = getattr(app_settings, "facebook_app_secret", None)
    if not app_id or not app_secret:
        return RedirectResponse(f"{FRONTEND_URL}/settings?facebook_error=Missing+app+credentials")

    redirect_uri = str(request.base_url).rstrip("/") + "/auth/facebook/callback"

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Exchange code for short-lived user token
        token_resp = await client.get(
            "https://graph.facebook.com/v25.0/oauth/access_token",
            params={"client_id": app_id, "redirect_uri": redirect_uri,
                    "client_secret": app_secret, "code": code}
        )
        token_data = token_resp.json()
        user_token = token_data.get("access_token")
        if not user_token:
            msg = token_data.get("error", {}).get("message", "Token exchange failed")
            return RedirectResponse(f"{FRONTEND_URL}/settings?facebook_error={msg}")

        # Exchange for long-lived user token (valid ~60 days)
        ll_resp = await client.get(
            "https://graph.facebook.com/v25.0/oauth/access_token",
            params={"grant_type": "fb_exchange_token", "client_id": app_id,
                    "client_secret": app_secret, "fb_exchange_token": user_token}
        )
        ll_token = ll_resp.json().get("access_token", user_token)

        # Get pages managed by the user (page tokens are permanent/non-expiring)
        accounts_resp = await client.get(
            "https://graph.facebook.com/v25.0/me/accounts",
            params={"access_token": ll_token, "fields": "id,name,access_token"}
        )
        pages = accounts_resp.json().get("data", [])
        if not pages:
            return RedirectResponse(f"{FRONTEND_URL}/settings?facebook_error=No+pages+found")

        # Prefer page matching saved page_id; else take first
        saved_page_id = getattr(app_settings, "facebook_page_id", None)
        page = next((p for p in pages if p["id"] == saved_page_id), pages[0])

        # Auto-detect Instagram business account
        ig_resp = await client.get(
            f"https://graph.facebook.com/v25.0/{page['id']}",
            params={"fields": "instagram_business_account", "access_token": page["access_token"]}
        )
        ig_id = ig_resp.json().get("instagram_business_account", {}).get("id")

    # Persist to DB + in-memory settings
    update_data = {
        "facebook_page_id": page["id"],
        "facebook_page_name": page.get("name", ""),
        "facebook_page_access_token": page["access_token"],
    }
    if ig_id:
        update_data["instagram_business_account_id"] = ig_id

    for key, value in update_data.items():
        setattr(app_settings, key, value)

    with Session(engine) as session:
        row = session.exec(select(SettingsTable).where(SettingsTable.id == 1)).first()
        if not row:
            row = SettingsTable(id=1)
        for key, value in update_data.items():
            if hasattr(row, key):
                setattr(row, key, value)
        session.add(row)
        session.commit()

    page_name = page.get("name", "")
    return RedirectResponse(f"{FRONTEND_URL}/settings?facebook_connected=true&page_name={page_name}")


@router.delete("/facebook")
async def facebook_disconnect(user=Depends(get_current_user)):
    """Remove Facebook / Instagram connection."""
    from services.auth import require_admin
    require_admin(user)
    fields = ["facebook_page_id", "facebook_page_name", "facebook_page_access_token",
              "instagram_business_account_id"]
    for f in fields:
        setattr(app_settings, f, None)
    with Session(engine) as session:
        row = session.exec(select(SettingsTable).where(SettingsTable.id == 1)).first()
        if row:
            for f in fields:
                if hasattr(row, f):
                    setattr(row, f, None)
            session.add(row)
            session.commit()
    return {"ok": True}
