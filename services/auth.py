"""Authentication services."""
from typing import Optional
from datetime import timedelta
from fastapi import Depends, HTTPException, Header, WebSocket
from fastapi.security import OAuth2PasswordBearer
from fastapi.security.utils import get_authorization_scheme_param
import jwt
from passlib.context import CryptContext
from sqlmodel import Session, select

from config.settings import JWT_SECRET, JWT_ALGO
from config.database import engine
from models.user import User, UserTable
from utils.datetime import utcnow

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def hash_password(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_minutes: int = 60 * 24 * 7) -> str:
    """Create JWT access token."""
    to_encode = data.copy()
    if "sub" in to_encode:
        to_encode["sub"] = str(to_encode["sub"])
    expire = utcnow() + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGO)


def find_user_by_email(email: str) -> Optional[User]:
    """Find user by email."""
    with Session(engine) as session:
        stmt = select(UserTable).where(UserTable.email == email)
        row = session.exec(stmt).first()
        if row:
            return User(
                id=row.id,
                name=row.name,
                email=row.email,
                password_hash=row.password_hash,
                role=row.role,
                is_owner=row.is_owner,
                created_at=row.created_at,
                last_login_at=row.last_login_at,
            )
    return None


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """Get current user from JWT token."""
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        user_id = payload.get("sub")
        if not user_id:
            raise credentials_exception
        
        with Session(engine) as session:
            stmt = select(UserTable).where(UserTable.id == int(user_id))
            row = session.exec(stmt).first()
            if row:
                return User(
                    id=row.id,
                    name=row.name,
                    email=row.email,
                    password_hash=row.password_hash,
                    role=row.role,
                    is_owner=row.is_owner,
                    created_at=row.created_at,
                    last_login_at=row.last_login_at,
                )
        raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception


def get_user_from_token(token: str) -> User:
    """Resolve a user from a raw bearer token string."""
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not token:
        raise credentials_exception

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        user_id = payload.get("sub")
        if not user_id:
            raise credentials_exception

        with Session(engine) as session:
            stmt = select(UserTable).where(UserTable.id == int(user_id))
            row = session.exec(stmt).first()
            if row:
                return User(
                    id=row.id,
                    name=row.name,
                    email=row.email,
                    password_hash=row.password_hash,
                    role=row.role,
                    is_owner=row.is_owner,
                    created_at=row.created_at,
                    last_login_at=row.last_login_at,
                )
        raise credentials_exception
    except jwt.PyJWTError as exc:
        raise credentials_exception from exc


async def get_current_user_optional(
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Depends(oauth2_scheme)
) -> Optional[User]:
    """Get current user, returns None if not authenticated."""
    raw_token = token
    if not raw_token and not authorization:
        return None
    if not raw_token:
        scheme, raw_token = get_authorization_scheme_param(authorization)
        if scheme.lower() != "bearer" or not raw_token:
            return None
    try:
        return await get_current_user(raw_token)
    except HTTPException:
        return None


async def get_current_user_ws(websocket: WebSocket) -> User:
    """Authenticate websocket connections using bearer token or token query param."""
    auth_header = websocket.headers.get("Authorization", "")
    scheme, token = get_authorization_scheme_param(auth_header)
    if scheme.lower() != "bearer" or not token:
        token = websocket.query_params.get("token", "")
    if not token:
        raise HTTPException(status_code=401, detail="Missing websocket token")
    return get_user_from_token(token)


def require_admin(user: User):
    """Require user to be admin."""
    if user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Chỉ ADMIN mới được thao tác này")
