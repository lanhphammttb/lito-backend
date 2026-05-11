"""Validation utilities."""
import re
from typing import Any, List, Optional
from datetime import date
from fastapi import HTTPException


def validate_email(email: str) -> bool:
    """Validate email format."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def validate_phone(phone: str) -> bool:
    """Validate Vietnamese phone format."""
    # Remove spaces and dashes
    cleaned = re.sub(r'[\s\-]', '', phone)
    # Vietnamese phone: starts with 0 or +84, 10-11 digits
    pattern = r'^(\+84|0)\d{9,10}$'
    return bool(re.match(pattern, cleaned))


def validate_required(value: Any, field_name: str):
    """Validate required field is not empty."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise HTTPException(status_code=400, detail=f"{field_name} là bắt buộc")


def validate_positive(value: float, field_name: str, allow_zero: bool = False):
    """Validate positive number."""
    if value is None:
        return
    if allow_zero:
        if value < 0:
            raise HTTPException(status_code=400, detail=f"{field_name} phải >= 0")
    else:
        if value <= 0:
            raise HTTPException(status_code=400, detail=f"{field_name} phải > 0")


def validate_enum(value: str, allowed_values: List[str], field_name: str):
    """Validate value is in allowed list."""
    if value and value not in allowed_values:
        allowed_str = ", ".join(allowed_values)
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} phải là một trong: {allowed_str}"
        )


def validate_date_range(
    start_date: Optional[date],
    end_date: Optional[date],
    field_name: str = "Ngày"
):
    """Validate date range."""
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} bắt đầu không được sau ngày kết thúc"
        )


def validate_length(
    value: str,
    field_name: str,
    min_length: int = 0,
    max_length: int = None
):
    """Validate string length."""
    if value is None:
        return
    if len(value) < min_length:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} phải có ít nhất {min_length} ký tự"
        )
    if max_length and len(value) > max_length:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} không được quá {max_length} ký tự"
        )


def validate_url(url: str) -> bool:
    """Validate URL format."""
    pattern = r'^https?://[^\s/$.?#].[^\s]*$'
    return bool(re.match(pattern, url, re.IGNORECASE))
