"""Strategy routes for OKRs, SWOT entries, and market insights."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, select

from config.database import engine
from models.strategy import StrategyItemTable
from models.user import User
from services.auth import get_current_user
from utils.datetime import utcnow


class StrategyPayload(BaseModel):
    """Flexible strategy payload while the frontend schema is still evolving."""

    model_config = ConfigDict(extra="allow")


router = APIRouter()

KIND_OKR = "okr"
KIND_SWOT = "swot"
KIND_INSIGHT = "market_insight"


def _dump_data(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _load_item(row: StrategyItemTable) -> dict:
    try:
        data = json.loads(row.data_json or "{}")
    except json.JSONDecodeError:
        data = {}
    data.update(
        {
            "id": row.id,
            "kind": row.kind,
            "created_by": row.created_by,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    )
    return data


def _create_item(kind: str, payload: dict, user: User) -> dict:
    now = utcnow()
    data = {k: v for k, v in payload.items() if k not in {"id", "kind", "created_by", "created_at", "updated_at"}}
    if kind == KIND_OKR:
        data.setdefault("status", "active")
        data.setdefault("key_results", [])
    elif kind == KIND_SWOT:
        data.setdefault("type", "strength")
        data.setdefault("action_items", [])
    elif kind == KIND_INSIGHT:
        data.setdefault("priority", "medium")

    with Session(engine) as session:
        row = StrategyItemTable(
            kind=kind,
            data_json=_dump_data(data),
            created_by=user.id,
            created_at=now,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _load_item(row)


def _update_item(item_id: int, kind: str, payload: dict) -> dict:
    forbidden = {"id", "kind", "created_by", "created_at"}
    with Session(engine) as session:
        row = session.get(StrategyItemTable, item_id)
        if not row or row.kind != kind:
            raise HTTPException(status_code=404, detail="Strategy item not found")
        data = _load_item(row)
        for field in ("id", "kind", "created_by", "created_at", "updated_at"):
            data.pop(field, None)
        for key, value in payload.items():
            if key not in forbidden:
                data[key] = value
        row.data_json = _dump_data(data)
        row.updated_at = utcnow()
        session.add(row)
        session.commit()
        session.refresh(row)
        return _load_item(row)


def _list_items(kind: str) -> list[dict]:
    with Session(engine) as session:
        rows = session.exec(
            select(StrategyItemTable)
            .where(StrategyItemTable.kind == kind)
            .order_by(StrategyItemTable.created_at.desc())
        ).all()
        return [_load_item(row) for row in rows]


def _okr_progress(okr: dict) -> dict:
    key_results = okr.get("key_results") or []
    total_progress = 0
    normalized_results = []
    for result in key_results:
        kr = dict(result)
        target = float(kr.get("target") or 0)
        current = float(kr.get("current") or 0)
        progress = (current / target * 100) if target > 0 else 0
        kr["progress"] = min(100, progress)
        total_progress += kr["progress"]
        normalized_results.append(kr)
    okr["key_results"] = normalized_results
    okr["overall_progress"] = round(total_progress / len(normalized_results), 1) if normalized_results else 0
    return okr


@router.get("/strategy/okrs")
async def get_okrs(
    quarter: Optional[str] = None,
    status: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    items = [_okr_progress(item) for item in _list_items(KIND_OKR)]
    if quarter:
        items = [item for item in items if item.get("quarter") == quarter]
    if status:
        items = [item for item in items if item.get("status") == status]

    return {
        "okrs": items,
        "summary": {
            "total": len(items),
            "active": len([item for item in items if item.get("status") == "active"]),
            "achieved": len([item for item in items if item.get("status") == "achieved"]),
            "at_risk": len([item for item in items if item.get("status") == "at_risk"]),
        },
    }


@router.post("/strategy/okrs")
async def create_okr(payload: StrategyPayload, user: User = Depends(get_current_user)):
    return _create_item(KIND_OKR, payload.model_dump(), user)


@router.put("/strategy/okrs/{okr_id}")
async def update_okr(okr_id: int, payload: dict, user: User = Depends(get_current_user)):
    return _update_item(okr_id, KIND_OKR, payload)


@router.get("/strategy/swot")
async def get_swot_analysis(
    category: Optional[str] = None,
    type: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    items = _list_items(KIND_SWOT)
    if category:
        items = [item for item in items if item.get("category") == category]
    if type:
        items = [item for item in items if item.get("type") == type]

    matrix = {
        "strengths": [item for item in items if item.get("type") == "strength"],
        "weaknesses": [item for item in items if item.get("type") == "weakness"],
        "opportunities": [item for item in items if item.get("type") == "opportunity"],
        "threats": [item for item in items if item.get("type") == "threat"],
    }
    return {
        "matrix": matrix,
        "summary": {
            "total": len(items),
            "strengths": len(matrix["strengths"]),
            "weaknesses": len(matrix["weaknesses"]),
            "opportunities": len(matrix["opportunities"]),
            "threats": len(matrix["threats"]),
        },
    }


@router.post("/strategy/swot")
async def create_swot(payload: StrategyPayload, user: User = Depends(get_current_user)):
    return _create_item(KIND_SWOT, payload.model_dump(), user)


@router.get("/strategy/market-insights")
async def get_market_insights(
    type: Optional[str] = None,
    priority: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    items = _list_items(KIND_INSIGHT)
    if type:
        items = [item for item in items if item.get("type") == type]
    if priority:
        items = [item for item in items if item.get("priority") == priority]

    return {
        "insights": items,
        "summary": {
            "total": len(items),
            "high_priority": len([item for item in items if item.get("priority") == "high"]),
            "competitors": len([item for item in items if item.get("type") == "competitor"]),
            "trends": len([item for item in items if item.get("type") == "trend"]),
        },
    }


@router.post("/strategy/market-insights")
async def create_market_insight(payload: StrategyPayload, user: User = Depends(get_current_user)):
    return _create_item(KIND_INSIGHT, payload.model_dump(), user)
