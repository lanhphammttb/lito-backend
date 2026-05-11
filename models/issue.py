"""Issue models."""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field
from sqlmodel import SQLModel, Field as SQLField


class Issue(BaseModel):
    """Issue/problem tracking model."""
    id: int
    product_id: int
    type: str = "quality"  # quality, design, material, process
    description: Optional[str] = None
    evidence: Optional[str] = None
    hypothesis: Optional[str] = None
    next_action: Optional[str] = None
    priority: int = 1
    status: str = "open"  # open, in_progress, resolved
    assigned_to: Optional[int] = None
    impact_revenue: Optional[float] = None
    is_template: bool = False
    resolution_hours: Optional[float] = None
    resolved_at: Optional[datetime] = None
    comments_count: int = 0
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class IssueTable(SQLModel, table=True):
    """Issue database table."""
    __tablename__ = "issues"
    
    id: Optional[int] = SQLField(default=None, primary_key=True)
    product_id: int = SQLField(index=True)
    type: str = "quality"
    description: Optional[str] = None
    evidence: Optional[str] = None
    hypothesis: Optional[str] = None
    next_action: Optional[str] = None
    priority: int = 1
    status: str = "open"
    assigned_to: Optional[int] = None
    impact_revenue: Optional[float] = None
    is_template: bool = False
    resolution_hours: Optional[float] = None
    resolved_at: Optional[datetime] = None
    comments_count: int = 0
    created_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)


class IssueComment(BaseModel):
    """Issue comment model."""
    id: int
    issue_id: int
    user_id: int
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class IssueCommentTable(SQLModel, table=True):
    """Issue comment database table."""
    __tablename__ = "issue_comments"
    
    id: Optional[int] = SQLField(default=None, primary_key=True)
    issue_id: int = SQLField(index=True)
    user_id: int
    content: str
    created_at: datetime = SQLField(default_factory=datetime.utcnow)
