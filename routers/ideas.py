"""Ideas router."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, select

from config.database import engine
from models.idea import IdeaTable
from models.user import User
from services.auth import get_current_user


class IdeaCreate(BaseModel):
    model_config = ConfigDict(extra="allow")


class IdeaUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")


router = APIRouter()


@router.get("/ideas")
async def list_ideas(user: User = Depends(get_current_user)):
    with Session(engine) as session:
        return [r.model_dump() for r in session.exec(select(IdeaTable)).all()]


@router.post("/ideas")
async def create_idea(payload: IdeaCreate, user: User = Depends(get_current_user)):
    data = payload.model_dump()
    if not data.get("name"):
        raise HTTPException(status_code=422, detail="name là bắt buộc")
    with Session(engine) as session:
        row = IdeaTable(**data, created_at=datetime.utcnow(), created_by=user.id)
        session.add(row)
        session.commit()
        session.refresh(row)
    return row.model_dump()


@router.put("/ideas/{idea_id}")
async def update_idea(idea_id: int, payload: IdeaUpdate, user: User = Depends(get_current_user)):
    with Session(engine) as session:
        row = session.get(IdeaTable, idea_id)
        if not row:
            raise HTTPException(status_code=404, detail="Idea không tồn tại")
        for key, value in payload.model_dump(exclude_unset=True).items():
            if key not in ("id", "created_by", "created_at"):
                setattr(row, key, value)
        row.updated_by = user.id
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.model_dump()


@router.delete("/ideas/{idea_id}")
async def delete_idea(idea_id: int, user: User = Depends(get_current_user)):
    with Session(engine) as session:
        row = session.get(IdeaTable, idea_id)
        if not row:
            raise HTTPException(status_code=404, detail="Idea không tồn tại")
        session.delete(row)
        session.commit()
    return {"ok": True}
