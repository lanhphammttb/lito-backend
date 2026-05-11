"""Application settings and configuration."""
import os
from dotenv import load_dotenv
from typing import List, Optional
from pydantic import BaseModel, ConfigDict

# Load environment variables from .env file
import os; load_dotenv(os.path.join(os.path.dirname(__file__), '../.env'))

# Environment variables
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGO = "HS256"
USE_MONGO = os.getenv("USE_MONGO", "false").lower() == "true"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./hala.db")
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]

_INVALID_JWT_SECRETS = {
    "",
    "changeme",
    "devsecret",
    "your-secret-key-change-in-production",
}

if not JWT_SECRET or JWT_SECRET.strip() in _INVALID_JWT_SECRETS:
    raise RuntimeError(
        "JWT_SECRET must be set to a non-placeholder value in backend/.env or environment."
    )


class Settings(BaseModel):
    """Business settings model."""
    model_config = ConfigDict(extra="ignore")

    hourly_rate: float = 50000
    default_profit_margin: float = 0.5
    low_stock_threshold: float = 1.0
    profit_share_mode: str = "50-50"
    share_user_a: float = 50.0
    share_user_b: float = 50.0
    business_name: Optional[str] = "Hala Handmade"
    shop_name: Optional[str] = "Hala Handmade"
    currency: str = "VND"
    business_address: Optional[str] = None
    business_logo: Optional[str] = None
    capacity_hours_per_month: float = 160.0
    tax_rate: float = 0.0
    notification_emails: Optional[List[str]] = None
    notify_low_stock: bool = True
    notify_forecast_low: bool = True
    backup_email: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: bool = True
    # Shopee integration
    shopee_partner_id: Optional[str] = None
    shopee_partner_key: Optional[str] = None
    shopee_shop_id: Optional[str] = None
    # Lazada integration
    lazada_app_key: Optional[str] = None
    lazada_app_secret: Optional[str] = None
    lazada_access_token: Optional[str] = None

    def public_dump(self) -> dict:
        """Return a settings payload that is safe to expose to authenticated clients."""
        return self.model_dump(exclude=_SECRET_FIELDS)

    def admin_dump(self) -> dict:
        """Return the full settings payload for admin users."""
        return self.model_dump()


# Global settings instance
settings = Settings()

_SECRET_FIELDS = {
    "smtp_password",
    "shopee_partner_key",
    "lazada_app_secret",
    "lazada_access_token",
}


# Constants
ORDER_STATUS_ALLOWED = {"pending", "confirmed", "processing", "shipped", "delivered", "completed", "cancelled"}
PURCHASE_ORDER_STATUS_ALLOWED = {"draft", "approved", "received", "cancelled"}
PAYMENT_METHOD_ALLOWED = {"cash", "bank_transfer", "momo", "vnpay", "cod", "credit_card", "other"}
PAYMENT_STATUS_ALLOWED = {"pending", "paid", "failed", "refunded", "partial"}
