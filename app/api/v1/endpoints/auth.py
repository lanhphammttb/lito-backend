from app.shared import *
from fastapi import APIRouter

router = APIRouter()

@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, session: Session = Depends(get_db)):
    stmt = select(UserTable).where(UserTable.email == req.email)
    user = session.exec(stmt).first()
    
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email hoặc mật khẩu không đúng",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    user.last_login_at = datetime.utcnow()
    session.add(user)
    session.commit()
    
    token = create_access_token({"sub": str(user.id), "role": user.role})
    
    return {"access_token": token, "token_type": "bearer"}
