"""Season routes."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from config.database import engine
from legacy_state import seasons
from models.season import SeasonTable
from models.user import User
from services.auth import get_current_user

router = APIRouter()


def _parse_date(value) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        return date.fromisoformat(value[:10])
    raise HTTPException(status_code=400, detail="Ngày mùa / dịp không hợp lệ")


def _season_payload(row: SeasonTable) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "start_date": str(row.from_date) if row.from_date else None,
        "end_date": str(row.to_date) if row.to_date else None,
        "from_date": str(row.from_date) if row.from_date else None,
        "to_date": str(row.to_date) if row.to_date else None,
    }


def _replace_memory_season(payload: dict) -> None:
    existing_index = next((idx for idx, item in enumerate(seasons) if item["id"] == payload["id"]), None)
    if existing_index is None:
        seasons.append(payload)
    else:
        seasons[existing_index] = payload


@router.get("")
async def list_seasons(user: User = Depends(get_current_user)):
    """List seasons."""
    with Session(engine) as session:
        rows = session.exec(select(SeasonTable).order_by(SeasonTable.from_date)).all()
    return [_season_payload(row) for row in rows]


@router.post("")
async def create_season(payload: dict, user: User = Depends(get_current_user)):
    """Create season."""
    with Session(engine) as session:
        row = SeasonTable(
            name=payload["name"],
            from_date=_parse_date(payload.get("from_date") or payload.get("start_date")),
            to_date=_parse_date(payload.get("to_date") or payload.get("end_date")),
            description=payload.get("description"),
            created_by=user.id,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
    result = _season_payload(row)
    _replace_memory_season(result)
    return result


@router.put("/{season_id}")
async def update_season(season_id: int, payload: dict, user: User = Depends(get_current_user)):
    """Update season."""
    with Session(engine) as session:
        row = session.get(SeasonTable, season_id)
        if not row:
            raise HTTPException(status_code=404, detail="Không tìm thấy mùa / dịp")
        row.name = payload.get("name", row.name)
        from_date = payload.get("from_date") or payload.get("start_date")
        to_date = payload.get("to_date") or payload.get("end_date")
        if from_date:
            row.from_date = _parse_date(from_date)
        if to_date:
            row.to_date = _parse_date(to_date)
        if "description" in payload:
            row.description = payload["description"]
        session.add(row)
        session.commit()
        session.refresh(row)
    result = _season_payload(row)
    _replace_memory_season(result)
    return result


@router.delete("/{season_id}")
async def delete_season(season_id: int, user: User = Depends(get_current_user)):
    """Delete season."""
    seasons[:] = [s for s in seasons if s["id"] != season_id]
    with Session(engine) as session:
        row = session.get(SeasonTable, season_id)
        if row:
            session.delete(row)
            session.commit()
    return {"success": True}
