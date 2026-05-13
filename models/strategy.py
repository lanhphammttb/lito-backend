"""Strategy planning persistence models."""

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class StrategyItemTable(SQLModel, table=True):
    """Generic persisted strategy item: OKR, SWOT entry, or market insight."""

    __tablename__ = "strategy_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str = Field(index=True)
    data_json: str = "{}"
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
