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
    from sqlmodel import select, or_, func
    with Session(engine) as session:
        statement = select(IssueTable)
        if product_id:
            statement = statement.where(IssueTable.product_id == product_id)
        if status:
            statement = statement.where(IssueTable.status == status)
        if priority is not None:
            statement = statement.where(IssueTable.priority == priority)
        if assignee_id is not None:
            statement = statement.where(IssueTable.assigned_to == assignee_id)
        if q:
            q_lower = f"%{q.lower()}%"
            statement = statement.where(
                or_(
                    func.lower(IssueTable.description).like(q_lower),
                    func.lower(IssueTable.type).like(q_lower)
                )
            )
            
        total = len(session.exec(statement).all())
        if response is not None:
            response.headers["X-Total-Count"] = str(total)
            
        results = session.exec(statement.offset(offset).limit(limit)).all()
        return [r.model_dump() for r in results]


@router.get("/issues/{issue_id}/comments")
async def list_issue_comments(issue_id: int):
    find_issue(issue_id)
    from sqlmodel import select
    from models.issue import IssueCommentTable
    with Session(engine) as session:
        return [r.model_dump() for r in session.exec(select(IssueCommentTable).where(IssueCommentTable.issue_id == issue_id)).all()]


@router.post("/issues/{issue_id}/comments")
async def create_issue_comment(issue_id: int, payload: IssueCommentCreate):
    issue = find_issue(issue_id)
    from models.issue import IssueCommentTable
    
    with Session(engine) as session:
        new_comment = IssueCommentTable(
            issue_id=issue_id,
            user_id=current_user.id,
            content=payload.content,
            created_at=datetime.utcnow(),
        )
        session.add(new_comment)
        session.commit()
        session.refresh(new_comment)
        
        # update count
        row = session.get(IssueTable, issue_id)
        if row:
            from sqlmodel import select, func
            count = session.exec(select(func.count(IssueCommentTable.id)).where(IssueCommentTable.issue_id == issue_id)).one()
            row.comments_count = count
            session.add(row)
            session.commit()
            
    return new_comment.model_dump()


@router.post("/issues")
async def create_issue(payload: IssueCreate):
    with Session(engine) as session:
        row = IssueTable(
            **payload.model_dump(),
            created_at=datetime.utcnow(),
            created_by=current_user.id,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
    return row.model_dump()


@router.put("/issues/{issue_id}")
async def update_issue(issue_id: int, payload: Issue):
    with Session(engine) as session:
        row = session.get(IssueTable, issue_id)
        if not row:
            raise HTTPException(status_code=404, detail="Issue không tồn tại")
            
        update_data = payload.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(row, key, value)
            
        if getattr(row, 'status', None) == "resolved" and getattr(row, 'resolved_at', None) is None:
            row.resolved_at = datetime.utcnow()
            row.resolution_hours = (
                (row.resolved_at - row.created_at).total_seconds() / 3600
                if row.created_at else None
            )
            
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.model_dump()


@router.post("/issues/from-template")
async def create_issue_from_template(payload: IssueFromTemplateRequest):
    template = find_issue(payload.template_id)
    if not template.is_template:
        raise HTTPException(status_code=400, detail="Issue này không phải template")
        
    with Session(engine) as session:
        row = IssueTable(
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
        session.add(row)
        session.commit()
        session.refresh(row)
    return row.model_dump()


@router.delete("/issues/{issue_id}")
async def delete_issue(issue_id: int):
    with Session(engine) as session:
        row = session.get(IssueTable, issue_id)
        if not row:
            raise HTTPException(status_code=404, detail="Issue không tồn tại")
        session.delete(row)
        session.commit()
    return {"ok": True}
