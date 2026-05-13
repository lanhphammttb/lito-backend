"""Shared state for legacy compatibility endpoints.

The app still has a set of old root-level endpoints that depend on in-memory
lists populated at startup. Keeping that state here lets main.py focus on
startup while routers can own HTTP concerns.
"""

from datetime import datetime
from typing import List, Optional

from sqlmodel import Field, SQLModel

from models.experiment import Experiment as ExperimentModel
from models.goal import Goal as GoalModel
from models.issue import Issue as IssueModel


issues: List[IssueModel] = []
issue_comments: List[dict] = []
experiments: List[ExperimentModel] = []
goals: List[GoalModel] = []
seasons: List[dict] = []
users: List[dict] = []
audit_logs: List[dict] = []
marketplace_logs: List[dict] = []
sent_notifications: List[dict] = []


class NotificationLog(SQLModel, table=True):
    """Persisted notification send history."""

    __tablename__ = "notification_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    body: Optional[str] = None
    sent_by: Optional[str] = None
    sent_count: int = 1
    timestamp: datetime = Field(default_factory=datetime.utcnow)
