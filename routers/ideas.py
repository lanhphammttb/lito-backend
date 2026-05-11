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
ideas: List = []
products: List = []


def set_data_stores(id_, p):
    global ideas, products
    ideas = id_; products = p


def next_id(collection) -> int:
    return max((item.id for item in collection), default=0) + 1


@router.get("/ideas")
async def list_ideas():
    return [i.model_dump() if hasattr(i, 'model_dump') else i for i in ideas]


@router.post("/ideas")
async def create_idea(payload: IdeaCreate):
    new_idea = Idea(id=next_id(ideas), **payload.model_dump(), created_by=current_user.id)
    ideas.append(new_idea)
    return new_idea


@router.put("/ideas/{idea_id}")
async def update_idea(idea_id: int, payload: Idea):
    if hasattr(payload, 'id') and payload.id != idea_id:
        raise HTTPException(status_code=400, detail="Không được đổi id")
    for idx, idea in enumerate(ideas):
        if idea.id == idea_id:
            payload.created_by = idea.created_by or getattr(payload, 'created_by', None)
            payload.updated_by = current_user.id
            ideas[idx] = payload
            return payload
    raise HTTPException(status_code=404, detail="Idea không tồn tại")


@router.delete("/ideas/{idea_id}")
async def delete_idea(idea_id: int):
    for idea in ideas:
        if idea.id == idea_id:
            ideas.remove(idea)
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Idea không tồn tại")
