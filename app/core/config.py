import os
from dotenv import load_dotenv

load_dotenv()

# Basic Setup
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET or len(JWT_SECRET) < 32:
    print("WARNING: JWT_SECRET is missing or too short. Real app should exit here!")
    # For ease of running initially without proper env, we might fall back or just warn
    # In a strict setup: raise ValueError("JWT_SECRET must be at least 32 characters long")

JWT_ALGO = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 24h default

# Database Setup
DATABASE_URL = os.getenv("DATABASE_URL")
MONGO_URL = os.getenv("MONGO_URL")

# Admin defaults
ADMIN_DEFAULT_PASSWORD = os.getenv("ADMIN_DEFAULT_PASSWORD")
OWNER_A_PASSWORD = os.getenv("OWNER_A_PASSWORD")
OWNER_B_PASSWORD = os.getenv("OWNER_B_PASSWORD")

# Image Upload (Optional Cloudinary setup if needed later)
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL")
