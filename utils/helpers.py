"""Helper utilities."""
import uuid
import random
import string
from datetime import date, datetime
from typing import List, Optional, TypeVar

T = TypeVar('T')


def paginate(items: List[T], skip: int = 0, limit: int = 100) -> List[T]:
    """Paginate a list of items."""
    return items[skip:skip + limit]


def generate_code(prefix: str = "", length: int = 8) -> str:
    """Generate a unique code with optional prefix."""
    chars = string.ascii_uppercase + string.digits
    random_part = ''.join(random.choices(chars, k=length))
    return f"{prefix}{random_part}" if prefix else random_part


def generate_uuid() -> str:
    """Generate a UUID string."""
    return str(uuid.uuid4())


def format_currency(amount: float, currency: str = "VND") -> str:
    """Format amount as currency string."""
    if currency == "VND":
        return f"{amount:,.0f}₫"
    return f"{amount:,.2f} {currency}"


def parse_date(date_str: str) -> Optional[date]:
    """Parse date string to date object."""
    if not date_str:
        return None
    formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def parse_datetime(dt_str: str) -> Optional[datetime]:
    """Parse datetime string to datetime object."""
    if not dt_str:
        return None
    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%SZ",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    return None


def clean_string(s: Optional[str]) -> Optional[str]:
    """Clean and normalize string."""
    if not s:
        return None
    return s.strip()


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    import re
    text = text.lower()
    text = re.sub(r'[àáạảãâầấậẩẫăằắặẳẵ]', 'a', text)
    text = re.sub(r'[èéẹẻẽêềếệểễ]', 'e', text)
    text = re.sub(r'[ìíịỉĩ]', 'i', text)
    text = re.sub(r'[òóọỏõôồốộổỗơờớợởỡ]', 'o', text)
    text = re.sub(r'[ùúụủũưừứựửữ]', 'u', text)
    text = re.sub(r'[ỳýỵỷỹ]', 'y', text)
    text = re.sub(r'[đ]', 'd', text)
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text.strip('-')


def calculate_percentage_change(old_value: float, new_value: float) -> float:
    """Calculate percentage change between two values."""
    if old_value == 0:
        return 100.0 if new_value > 0 else 0.0
    return ((new_value - old_value) / old_value) * 100
