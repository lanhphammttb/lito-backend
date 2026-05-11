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
experiments: List = []


def set_data_stores(ex):
    global experiments
    experiments = ex


def next_id(collection) -> int:
    return max((item.id for item in collection), default=0) + 1


@router.get("/experiments")
async def list_experiments():
    return [i.model_dump() if hasattr(i, 'model_dump') else i for i in experiments]


@router.post("/experiments")
async def create_experiment(payload: ExperimentCreate):
    new_exp = Experiment(
        id=next_id(experiments),
        **payload.model_dump(),
        created_by=current_user.id,
        created_at=datetime.utcnow(),
    )
    experiments.append(new_exp)
    return new_exp


@router.put("/experiments/{exp_id}")
async def update_experiment(exp_id: int, payload: ExperimentUpdate):
    for idx, exp in enumerate(experiments):
        if exp.id == exp_id:
            data = exp.model_dump()
            for field, value in payload.model_dump(exclude_none=True).items():
                data[field] = value
            updated = Experiment(**data)
            experiments[idx] = updated
            return updated
    raise HTTPException(status_code=404, detail="Experiment không tồn tại")


@router.delete("/experiments/{exp_id}")
async def delete_experiment(exp_id: int):
    for exp in experiments:
        if exp.id == exp_id:
            experiments.remove(exp)
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Experiment không tồn tại")
