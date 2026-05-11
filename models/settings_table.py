"""Settings table model."""
from typing import Optional
from sqlmodel import SQLModel, Field as SQLField


class SettingsTable(SQLModel, table=True):
    """Settings database table."""
    __tablename__ = "settings"
    
    id: int = SQLField(default=1, primary_key=True)
    hourly_rate: float = 50000
    default_profit_margin: float = 0.5
    low_stock_threshold: float = 1.0
    profit_share_mode: str = "50-50"
    share_user_a: float = 50.0
    share_user_b: float = 50.0
    business_name: Optional[str] = "Hala Handmade"
    business_address: Optional[str] = None
    business_logo: Optional[str] = None
    capacity_hours_per_month: float = 160.0
    tax_rate: float = 0.0
    notification_emails: Optional[str] = None  # JSON array
    notify_low_stock: bool = True
    notify_forecast_low: bool = True
    backup_email: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: bool = True
    # Marketplace integrations
    shopee_partner_id: Optional[str] = None
    shopee_partner_key: Optional[str] = None
    shopee_shop_id: Optional[str] = None
    lazada_app_key: Optional[str] = None
    lazada_app_secret: Optional[str] = None
    lazada_access_token: Optional[str] = None
