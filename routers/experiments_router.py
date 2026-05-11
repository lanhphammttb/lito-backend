"""Experiments router."""
from typing import List
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from models.user import User


class DummyModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Experiment(DummyModel): pass
class ExperimentCreate(DummyModel): pass
class ExperimentUpdate(DummyModel): pass


router = APIRouter()
current_user = User(id=1, email="admin@hala.vn", role="admin", name="Admin", password_hash="dummy")
from datetime import datetime
from sqlmodel import Session, select
from config.database import engine
from models.experiment import ExperimentTable

def set_data_stores(ex):
    pass


def next_id(collection) -> int:
    return max((item.id for item in collection), default=0) + 1


@router.get("/experiments")
async def list_experiments():
    with Session(engine) as session:
        return [r.model_dump() for r in session.exec(select(ExperimentTable)).all()]


@router.post("/experiments")
async def create_experiment(payload: ExperimentCreate):
    with Session(engine) as session:
        row = ExperimentTable(
            **payload.model_dump(),
            created_by=current_user.id,
            created_at=datetime.utcnow(),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
    return row.model_dump()


@router.put("/experiments/{exp_id}")
async def update_experiment(exp_id: int, payload: ExperimentUpdate):
    with Session(engine) as session:
        row = session.get(ExperimentTable, exp_id)
        if not row:
            raise HTTPException(status_code=404, detail="Experiment không tồn tại")
        
        for field, value in payload.model_dump(exclude_none=True).items():
            if field != "id" and field != "created_by" and field != "created_at":
                setattr(row, field, value)
                
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.model_dump()


@router.delete("/experiments/{exp_id}")
async def delete_experiment(exp_id: int):
    with Session(engine) as session:
        row = session.get(ExperimentTable, exp_id)
        if not row:
            raise HTTPException(status_code=404, detail="Experiment không tồn tại")
        session.delete(row)
        session.commit()
    return {"ok": True}
