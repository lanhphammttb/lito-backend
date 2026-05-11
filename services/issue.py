"""Issue services."""
from fastapi import HTTPException

# In-memory data store
issues = []


def set_data_stores(i):
    """Set data stores."""
    global issues
    issues = i


def find_issue(issue_id: int):
    """Find issue by ID."""
    for issue in issues:
        if issue.id == issue_id:
            return issue
    raise HTTPException(status_code=404, detail=f"Issue {issue_id} không tồn tại")
