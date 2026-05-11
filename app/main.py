"""
Hala Handmade Business OS - FastAPI Application
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# Import shared module first - it has engine, limiter, all models
from app.shared import engine, limiter, SQLModel
from app.api.v1.api_router import api_router

# --- App setup ---
app = FastAPI(title="Handmade Business OS", version="0.1.0")

# Rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Create all tables on import
SQLModel.metadata.create_all(engine)

# Include all API routes (no prefix to keep original URL structure)
app.include_router(api_router)

@app.get("/")
def root():
    return {"message": "Hala Handmade Business OS API"}
