from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from slowapi import Limiter
from slowapi.util import get_remote_address

# --- Rate Limiter Setup ---
limiter = Limiter(key_func=get_remote_address)

# --- Password Hashing Setup ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

# --- OAuth2 & JWT Setup ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
