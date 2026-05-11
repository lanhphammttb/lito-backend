"""Issue schemas."""
from typing import Optional
from pydantic import BaseModel


class IssueCreate(BaseModel):
    """Issue create schema."""
    product_id: int
    type: str = "quality"
    description: Optional[str] = None
    evidence: Optional[str] = None
    hypothesis: Optional[str] = None
    next_action: Optional[str] = None
    priority: int = 1
    assigned_to: Optional[int] = None
    impact_revenue: Optional[float] = None
    is_template: bool = False


class IssueCommentCreate(BaseModel):
    """Issue comment create schema."""
    content: str


class IssueFromTemplateRequest(BaseModel):
    """Create issue from template request."""
    template_id: int
    product_id: int
    description: Optional[str] = None
    priority: Optional[int] = None
