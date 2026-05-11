"""Bulk import schemas."""
from typing import List
from pydantic import BaseModel


class BulkImportRequest(BaseModel):
    """Bulk import request."""
    items: List[dict]


class BulkImportResponse(BaseModel):
    """Bulk import response."""
    imported: int
    failed: int
    errors: List[str] = []
