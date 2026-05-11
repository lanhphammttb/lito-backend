"""Issues router."""
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Response
from sqlmodel import Session, delete as sql_delete
from pydantic import BaseModel, ConfigDict
from models.user import User
from models.issue import IssueTable
from config.database import engine
from services.issue import find_issue


class DummyModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Issue(DummyModel): pass
class IssueCreate(DummyModel): pass
class IssueComment(DummyModel): pass


class IssueCommentCreate(BaseModel):
    content: str


class IssueFromTemplateRequest(BaseModel):
    template_id: int
    product_id: int
    description: Optional[str] = None
    priority: Optional[int] = None


router = APIRouter()
current_user = User(id=1, email="admin@hala.vn", role="admin", name="Admin", password_hash="dummy")

issues: List = []
issue_comments: List = []
users: List = []
products: List = []


def set_data_stores(is_, ic, u, p):
    global issues, issue_comments, users, products
    issues = is_; issue_comments = ic; users = u; products = p


def next_id(collection) -> int:
    return max((item.id for item in collection), default=0) + 1


def save_issue_sql(issue) -> None:
    try:
        with Session(engine) as session:
            existing = session.get(IssueTable, issue.id)
            if existing:
                for field in ["product_id", "type", "description", "evidence", "hypothesis",
                              "next_action", "priority", "status", "assigned_to", "impact_revenue",
                              "is_template", "resolution_hours", "resolved_at", "comments_count",
                              "created_by", "created_at"]:
                    if hasattr(issue, field):
                        setattr(existing, field, getattr(issue, field))
                session.add(existing)
            else:
                row = IssueTable(
                    id=issue.id,
                    product_id=issue.product_id,
                    type=getattr(issue, "type", "quality"),
                    description=getattr(issue, "description", None),
                    evidence=getattr(issue, "evidence", None),
                    hypothesis=getattr(issue, "hypothesis", None),
                    next_action=getattr(issue, "next_action", None),
                    priority=getattr(issue, "priority", 1),
                    status=getattr(issue, "status", "open"),
                    assigned_to=getattr(issue, "assigned_to", None),
                    impact_revenue=getattr(issue, "impact_revenue", None),
                    is_template=getattr(issue, "is_template", False),
                    resolution_hours=getattr(issue, "resolution_hours", None),
                    resolved_at=getattr(issue, "resolved_at", None),
                    comments_count=getattr(issue, "comments_count", 0),
                    created_by=getattr(issue, "created_by", None),
                    created_at=getattr(issue, "created_at", datetime.utcnow()),
                )
                session.add(row)
            session.commit()
    except Exception as e:
        print(f"[save_issue_sql] Warning: {e}")


@router.get("/issues")
async def list_issues(
    product_id: Optional[int] = None,
    status: Optional[str] = None,
    priority: Optional[int] = None,
    assignee_id: Optional[int] = None,
    q: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    response: Response = None,
):
    def with_counts(src):
        for i in src:
            i.comments_count = len([c for c in issue_comments if c.issue_id == i.id])
        return src

    filtered = issues[:]
    if product_id:
        filtered = [i for i in filtered if i.product_id == product_id]
    if status:
        filtered = [i for i in filtered if i.status == status]
    if priority is not None:
        filtered = [i for i in filtered if i.priority == priority]
    if assignee_id is not None:
        filtered = [i for i in filtered if i.assigned_to == assignee_id]
    if q:
        q_lower = q.lower()
        filtered = [i for i in filtered if q_lower in (i.description or "").lower() or q_lower in (i.type or "").lower()]
    total = len(filtered)
    if response is not None:
        response.headers["X-Total-Count"] = str(total)
    result = with_counts(filtered)[offset: offset + limit]
    return [i.model_dump() if hasattr(i, 'model_dump') else i for i in result]


@router.get("/issues/{issue_id}/comments")
async def list_issue_comments(issue_id: int):
    find_issue(issue_id)
    return [c for c in issue_comments if c.issue_id == issue_id]


@router.post("/issues/{issue_id}/comments")
async def create_issue_comment(issue_id: int, payload: IssueCommentCreate):
    find_issue(issue_id)
    new_comment = IssueComment(
        id=next_id(issue_comments),
        issue_id=issue_id,
        user_id=current_user.id,
        content=payload.content,
        created_at=datetime.utcnow(),
    )
    issue_comments.append(new_comment)
    for i in issues:
        if i.id == issue_id:
            i.comments_count = len([c for c in issue_comments if c.issue_id == issue_id])
            save_issue_sql(i)
            break
    return new_comment


@router.post("/issues")
async def create_issue(payload: IssueCreate):
    new_issue = Issue(
        **payload.model_dump(),
        id=next_id(issues),
        created_at=datetime.utcnow(),
        created_by=current_user.id,
    )
    issues.append(new_issue)
    save_issue_sql(new_issue)
    return new_issue


@router.put("/issues/{issue_id}")
async def update_issue(issue_id: int, payload: Issue):
    for idx, issue in enumerate(issues):
        if issue.id == issue_id:
            payload.id = issue_id
            payload.created_at = issue.created_at
            payload.created_by = issue.created_by
            if getattr(payload, 'status', None) == "resolved" and getattr(payload, 'resolved_at', None) is None:
                payload.resolved_at = datetime.utcnow()
                payload.resolution_hours = (
                    (payload.resolved_at - payload.created_at).total_seconds() / 3600
                    if payload.created_at else None
                )
            issues[idx] = payload
            save_issue_sql(payload)
            return payload
    raise HTTPException(status_code=404, detail="Issue không tồn tại")


@router.post("/issues/from-template")
async def create_issue_from_template(payload: IssueFromTemplateRequest):
    template = find_issue(payload.template_id)
    if not template.is_template:
        raise HTTPException(status_code=400, detail="Issue này không phải template")
    new_issue = Issue(
        id=next_id(issues),
        product_id=payload.product_id,
        type=template.type,
        description=payload.description or template.description,
        evidence=template.evidence,
        hypothesis=template.hypothesis,
        next_action=template.next_action,
        priority=payload.priority or template.priority,
        status="open",
        impact_revenue=template.impact_revenue,
        is_template=False,
        created_by=current_user.id,
        created_at=datetime.utcnow(),
    )
    issues.append(new_issue)
    save_issue_sql(new_issue)
    return new_issue


@router.delete("/issues/{issue_id}")
async def delete_issue(issue_id: int):
    for issue in issues:
        if issue.id == issue_id:
            issues.remove(issue)
            with Session(engine) as session:
                session.exec(sql_delete(IssueTable).where(IssueTable.id == issue_id))
                session.commit()
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Issue không tồn tại")
