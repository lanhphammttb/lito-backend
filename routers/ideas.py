"""Ideas router."""
from typing import List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from models.user import User


class DummyModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Idea(DummyModel): pass
class IdeaCreate(DummyModel): pass


router = APIRouter()
current_user = User(id=1, email="admin@hala.vn", role="admin", name="Admin", password_hash="dummy")
from datetime import datetime
from sqlmodel import Session, select
from config.database import engine
from models.idea import IdeaTable

def set_data_stores(id_, p):
    pass


def next_id(collection) -> int:
    return max((item.id for item in collection), default=0) + 1


@router.get("/ideas")
async def list_ideas():
    with Session(engine) as session:
        return [r.model_dump() for r in session.exec(select(IdeaTable)).all()]


@router.post("/ideas")
async def create_idea(payload: IdeaCreate):
    with Session(engine) as session:
        row = IdeaTable(
            **payload.model_dump(),
            created_at=datetime.utcnow(),
            created_by=current_user.id,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
    return row.model_dump()


@router.put("/ideas/{idea_id}")
async def update_idea(idea_id: int, payload: Idea):
    if hasattr(payload, 'id') and payload.id != idea_id:
        raise HTTPException(status_code=400, detail="Không được đổi id")
    with Session(engine) as session:
        row = session.get(IdeaTable, idea_id)
        if not row:
            raise HTTPException(status_code=404, detail="Idea không tồn tại")
        
        update_data = payload.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if key != "id" and key != "created_by" and key != "created_at":
                setattr(row, key, value)
        row.updated_by = current_user.id
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.model_dump()


@router.delete("/ideas/{idea_id}")
async def delete_idea(idea_id: int):
    with Session(engine) as session:
        row = session.get(IdeaTable, idea_id)
        if not row:
            raise HTTPException(status_code=404, detail="Idea không tồn tại")
        session.delete(row)
        session.commit()
    return {"ok": True}
