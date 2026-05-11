"""Strategy router - OKRs, SWOT, Market Insights."""
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict


class DummyModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class OKR(DummyModel): pass
class OKRCreate(DummyModel): pass
class SWOTAnalysis(DummyModel): pass
class SWOTCreate(DummyModel): pass
class MarketInsight(DummyModel): pass
class MarketInsightCreate(DummyModel): pass


router = APIRouter()
okrs_db: List[OKR] = []
swot_db: List[SWOTAnalysis] = []
market_insights_db: List[MarketInsight] = []

current_user_id = 1


@router.get("/strategy/okrs")
async def get_okrs(quarter: Optional[str] = None, status: Optional[str] = None):
    filtered = okrs_db
    if quarter:
        filtered = [o for o in filtered if getattr(o, 'quarter', None) == quarter]
    if status:
        filtered = [o for o in filtered if getattr(o, 'status', None) == status]

    okrs_with_progress = []
    for okr in filtered:
        key_results = getattr(okr, 'key_results', []) or []
        total_progress = 0
        for kr in key_results:
            kr_progress = (kr.get("current", 0) / kr.get("target", 1)) * 100 if kr.get("target", 0) > 0 else 0
            kr["progress"] = min(100, kr_progress)
            total_progress += kr["progress"]
        okr_dict = okr.model_dump()
        okr_dict["overall_progress"] = round(total_progress / len(key_results), 1) if key_results else 0
        okrs_with_progress.append(okr_dict)

    return {
        "okrs": okrs_with_progress,
        "summary": {
            "total": len(okrs_with_progress),
            "active": len([o for o in filtered if getattr(o, 'status', '') == "active"]),
            "achieved": len([o for o in filtered if getattr(o, 'status', '') == "achieved"]),
            "at_risk": len([o for o in filtered if getattr(o, 'status', '') == "at_risk"])
        }
    }


@router.post("/strategy/okrs")
async def create_okr(payload: OKRCreate):
    new_okr = OKR(id=len(okrs_db) + 1, **payload.model_dump())
    okrs_db.append(new_okr)
    return new_okr


@router.put("/strategy/okrs/{okr_id}")
async def update_okr(okr_id: int, payload: dict):
    okr = next((o for o in okrs_db if o.id == okr_id), None)
    if not okr:
        raise HTTPException(status_code=404, detail="OKR not found")
    for key, value in payload.items():
        if hasattr(okr, key):
            setattr(okr, key, value)
    okr.updated_at = datetime.utcnow()
    return okr


@router.get("/strategy/swot")
async def get_swot_analysis(category: Optional[str] = None, type: Optional[str] = None):
    filtered = swot_db
    if category:
        filtered = [s for s in filtered if getattr(s, 'category', '') == category]
    if type:
        filtered = [s for s in filtered if getattr(s, 'type', '') == type]

    swot_matrix = {
        "strengths": [s for s in filtered if getattr(s, 'type', '') == "strength"],
        "weaknesses": [s for s in filtered if getattr(s, 'type', '') == "weakness"],
        "opportunities": [s for s in filtered if getattr(s, 'type', '') == "opportunity"],
        "threats": [s for s in filtered if getattr(s, 'type', '') == "threat"]
    }

    return {
        "matrix": swot_matrix,
        "summary": {
            "total": len(filtered),
            "strengths": len(swot_matrix["strengths"]),
            "weaknesses": len(swot_matrix["weaknesses"]),
            "opportunities": len(swot_matrix["opportunities"]),
            "threats": len(swot_matrix["threats"])
        }
    }


@router.post("/strategy/swot")
async def create_swot(payload: SWOTCreate):
    new_swot = SWOTAnalysis(id=len(swot_db) + 1, created_by=current_user_id, **payload.model_dump())
    swot_db.append(new_swot)
    return new_swot


@router.get("/strategy/market-insights")
async def get_market_insights(type: Optional[str] = None, priority: Optional[str] = None):
    filtered = market_insights_db
    if type:
        filtered = [i for i in filtered if getattr(i, 'type', '') == type]
    if priority:
        filtered = [i for i in filtered if getattr(i, 'priority', '') == priority]

    return {
        "insights": filtered,
        "summary": {
            "total": len(filtered),
            "high_priority": len([i for i in filtered if getattr(i, 'priority', '') == "high"]),
            "competitors": len([i for i in filtered if getattr(i, 'type', '') == "competitor"]),
            "trends": len([i for i in filtered if getattr(i, 'type', '') == "trend"])
        }
    }


@router.post("/strategy/market-insights")
async def create_market_insight(payload: MarketInsightCreate):
    new_insight = MarketInsight(id=len(market_insights_db) + 1, **payload.model_dump())
    market_insights_db.append(new_insight)
    return new_insight
