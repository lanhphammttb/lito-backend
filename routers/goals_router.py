"""Goals router."""
from typing import List
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session
from config.database import engine
from models.user import User
from models.goal import GoalTable
from services.auth import get_current_user
from services.order import compute_order_totals


class DummyModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Goal(DummyModel): pass
class GoalCreate(DummyModel): pass


router = APIRouter()
goals: List = []
_orders: List = []
_expenses: List = []


def set_data_stores(gl, ord=None, exp=None):
    global goals, _orders, _expenses
    goals = gl
    if ord is not None:
        _orders = ord
    if exp is not None:
        _expenses = exp


def next_id(collection) -> int:
    return max((item.id for item in collection), default=0) + 1


def _compute_current_value(goal) -> float:
    """Compute current_value from real order data based on target_type and date range."""
    try:
        start = date.fromisoformat(str(goal.start_date)) if getattr(goal, 'start_date', None) else None
        end = date.fromisoformat(str(goal.end_date)) if getattr(goal, 'end_date', None) else None
    except Exception:
        return float(getattr(goal, 'current_value', 0) or 0)

    target_type = getattr(goal, 'target_type', 'revenue')

    def _parse_order_date(order_obj):
        candidates = [
            getattr(order_obj, 'date', None),
            getattr(order_obj, 'order_date', None),
            getattr(order_obj, 'created_at', None),
        ]
        for raw in candidates:
            if not raw:
                continue
            try:
                if isinstance(raw, datetime):
                    return raw.date()  # datetime is subclass of date — must convert explicitly
                if isinstance(raw, date):
                    return raw
                return date.fromisoformat(str(raw)[:10])
            except Exception:
                continue
        return None

    relevant = []
    for o in _orders:
        o_date = _parse_order_date(o)
        if not o_date:
            continue
        if start and o_date < start:
            continue
        if end and o_date > end:
            continue
        status = str(getattr(o, 'status', '') or '').strip().lower()
        if status in ('cancelled', 'canceled', 'returned', 'void'):
            continue
        relevant.append(o)

    if target_type == 'revenue':
        total = 0.0
        for o in relevant:
            try:
                total += compute_order_totals(o)["revenue"]
            except Exception:
                for line in (getattr(o, 'order_lines', None) or []):
                    if isinstance(line, dict):
                        total += line.get('unit_price', 0) * line.get('quantity', 0)
                    else:
                        total += getattr(line, 'unit_price', 0) * getattr(line, 'quantity', 0)
        return round(total, 2)
    elif target_type == 'profit':
        revenue = 0.0
        for o in relevant:
            try:
                revenue += compute_order_totals(o)["revenue"]
            except Exception:
                revenue += sum(
                    getattr(line, 'unit_price', 0) * getattr(line, 'quantity', 0)
                    for line in (getattr(o, 'order_lines', None) or [])
                )

        expense_total = 0.0
        for exp in _expenses:
            exp_date = getattr(exp, 'date', None)
            try:
                exp_date = exp_date if isinstance(exp_date, date) else date.fromisoformat(str(exp_date)[:10])
            except Exception:
                continue
            if start and exp_date < start:
                continue
            if end and exp_date > end:
                continue
            expense_total += float(getattr(exp, 'amount', 0) or 0)

        return round(revenue - expense_total, 2)
    elif target_type == 'orders':
        return float(len(relevant))
    elif target_type == 'products':
        product_ids = set()
        for o in relevant:
            for line in (getattr(o, 'order_lines', None) or []):
                pid = getattr(line, 'product_id', None) or (line.get('product_id') if isinstance(line, dict) else None)
                if pid:
                    product_ids.add(pid)
        return float(len(product_ids))
    elif target_type == 'customers':
        customer_ids = set()
        for o in relevant:
            cid = getattr(o, 'customer_id', None)
            if cid:
                customer_ids.add(cid)
        return float(len(customer_ids))

    return float(getattr(goal, 'current_value', 0) or 0)



@router.get("/goals")
async def list_goals():
    result = []
    for g in goals:
        d = g.model_dump() if hasattr(g, 'model_dump') else dict(g)
        try:
            d['current_value'] = _compute_current_value(g)
        except Exception as e:
            print(f"[goals] compute error for goal {getattr(g, 'id', '?')}: {e}")
            d['current_value'] = float(getattr(g, 'current_value', 0) or 0)

        # Auto-mark achieved when goal is active and current >= target
        if d.get('status') == 'active':
            target = float(getattr(g, 'target_value', 0) or 0)
            current = d['current_value']
            if target > 0 and current >= target:
                d['status'] = 'achieved'
                # Persist to DB and in-memory
                try:
                    g.status = 'achieved'
                    with Session(engine) as session:
                        row = session.get(GoalTable, g.id)
                        if row:
                            row.status = 'achieved'
                            row.achieved_at = datetime.now()
                            session.add(row)
                            session.commit()
                except Exception as e:
                    print(f"[goals] auto-achieve persist error: {e}")

        result.append(d)
    return result


@router.post("/goals")
async def create_goal(payload: GoalCreate, user: User = Depends(get_current_user)):
    data = payload.model_dump()
    new_goal = Goal(
        id=next_id(goals),
        **data,
        created_by=user.id,
        created_at=datetime.utcnow(),
    )
    goals.append(new_goal)

    with Session(engine) as session:
        row = GoalTable(
            title=getattr(new_goal, 'title', ''),
            description=getattr(new_goal, 'description', None),
            target_type=getattr(new_goal, 'target_type', 'revenue'),
            target_value=float(getattr(new_goal, 'target_value', 0) or 0),
            current_value=0.0,
            start_date=date.fromisoformat(str(getattr(new_goal, 'start_date', date.today()))[:10]),
            end_date=date.fromisoformat(str(getattr(new_goal, 'end_date', date.today()))[:10]),
            status=getattr(new_goal, 'status', 'active'),
            created_by=user.id,
            created_at=datetime.utcnow(),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        new_goal.id = row.id

    d = new_goal.model_dump()
    d['current_value'] = _compute_current_value(new_goal)
    return d


@router.put("/goals/{goal_id}")
async def update_goal(goal_id: int, payload: GoalCreate, user: User = Depends(get_current_user)):
    for idx, goal in enumerate(goals):
        if goal.id == goal_id:
            updated = Goal(
                id=goal_id,
                **payload.model_dump(),
                created_by=getattr(goal, 'created_by', user.id),
                created_at=getattr(goal, 'created_at', datetime.utcnow()),
                achieved_at=getattr(goal, 'achieved_at', None),
            )
            goals[idx] = updated

            with Session(engine) as session:
                row = session.get(GoalTable, goal_id)
                if row:
                    row.title = getattr(updated, 'title', row.title)
                    row.description = getattr(updated, 'description', None)
                    row.target_type = getattr(updated, 'target_type', 'revenue')
                    row.target_value = float(getattr(updated, 'target_value', 0) or 0)
                    row.start_date = date.fromisoformat(str(getattr(updated, 'start_date', date.today()))[:10])
                    row.end_date = date.fromisoformat(str(getattr(updated, 'end_date', date.today()))[:10])
                    row.status = getattr(updated, 'status', 'active')
                    session.add(row)
                    session.commit()

            d = updated.model_dump()
            d['current_value'] = _compute_current_value(updated)
            return d
    raise HTTPException(status_code=404, detail="Mục tiêu không tồn tại")


@router.delete("/goals/{goal_id}")
async def delete_goal(goal_id: int, user: User = Depends(get_current_user)):
    for goal in goals:
        if goal.id == goal_id:
            goals.remove(goal)
            with Session(engine) as session:
                row = session.get(GoalTable, goal_id)
                if row:
                    session.delete(row)
                    session.commit()
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Mục tiêu không tồn tại")
