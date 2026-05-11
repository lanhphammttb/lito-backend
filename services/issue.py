"""Issue services."""
from fastapi import HTTPException

# In-memory data store
issues = []


def set_data_stores(i):
    """Set data stores."""
    global issues
    issues = i


def find_issue(issue_id: int):
    """Find issue by ID from Database."""
    from sqlmodel import Session
    from config.database import engine
    from models.issue import IssueTable, Issue
    with Session(engine) as session:
        row = session.get(IssueTable, issue_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Issue {issue_id} không tồn tại")
        return Issue(**row.model_dump())
