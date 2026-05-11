from fastapi import Depends, HTTPException
from sqlmodel import Session, select
from jwt import decode, PyJWTError

from app.core.config import JWT_SECRET, JWT_ALGO
from app.core.security import oauth2_scheme
from app.core.database import get_db
from app.models.user import UserTable
from app.schemas.user import User

def get_current_user(token: str = Depends(oauth2_scheme), session: Session = Depends(get_db)) -> User:
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        payload = decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
            
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
        raise HTTPException(status_code=401, detail="User not found")
    except PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
