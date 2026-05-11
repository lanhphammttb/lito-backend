from app.shared import *
from fastapi import APIRouter

router = APIRouter()

@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user

@router.get("/users")
async def list_users(session: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    stmt = select(UserTable)
    rows = session.exec(stmt).all()
    return rows
