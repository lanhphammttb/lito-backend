"""Idea schemas."""
from typing import Optional
from pydantic import BaseModel


class IdeaCreate(BaseModel):
    """Idea create schema."""
    title: Optional[str] = None
    name: Optional[str] = None          # frontend sends name, maps to title
    description: Optional[str] = None
    source: Optional[str] = None
    status: str = "Chưa thử"
    priority: int = 1
    estimated_time: Optional[int] = None
    estimated_price: Optional[float] = None

    def model_post_init(self, __context):
        if self.title is None and self.name:
            self.title = self.name
        elif self.title is None:
            self.title = "Ý tưởng mới"
