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
def set_data_stores(gl, ord=None, exp=None):
    pass


def _compute_current_value(goal) -> float:
    """Compute current_value from real order data based on target_type and date range."""
    from sqlmodel import Session, select
    from models.order import OrderTable
    from models.expense import ExpenseTable
    import json
    
    try:
        start = date.fromisoformat(str(goal.start_date)) if getattr(goal, 'start_date', None) else None
        end = date.fromisoformat(str(goal.end_date)) if getattr(goal, 'end_date', None) else None
    except Exception:
        return float(getattr(goal, 'current_value', 0) or 0)

    target_type = getattr(goal, 'target_type', 'revenue')

    with Session(engine) as session:
        stmt_orders = select(OrderTable).where(OrderTable.status.notin_(('cancelled', 'canceled', 'returned', 'void')))
        if start:
            stmt_orders = stmt_orders.where(OrderTable.date >= start)
        if end:
            stmt_orders = stmt_orders.where(OrderTable.date <= end)
            
        relevant_orders = session.exec(stmt_orders).all()

        if target_type == 'revenue':
            total = sum((float(getattr(o, "revenue", 0) or 0)) for o in relevant_orders)
            return round(total, 2)
            
        elif target_type == 'profit':
            revenue = sum((float(getattr(o, "revenue", 0) or 0)) for o in relevant_orders)
            
            stmt_exp = select(ExpenseTable)
            if start:
                stmt_exp = stmt_exp.where(ExpenseTable.date >= start)
            if end:
                stmt_exp = stmt_exp.where(ExpenseTable.date <= end)
            
            expenses = session.exec(stmt_exp).all()
            expense_total = sum((float(getattr(e, "amount", 0) or 0)) for e in expenses)
            
            return round(revenue - expense_total, 2)
            
        elif target_type == 'orders':
            return float(len(relevant_orders))
            
        elif target_type == 'products':
            product_ids = set()
            from models.order import OrderLineTable
            for o in relevant_orders:
                if o.order_lines_json:
                    try:
                        lines = json.loads(o.order_lines_json)
                        for line in lines:
                            pid = line.get('product_id')
                            if pid: product_ids.add(pid)
                    except:
                        pass
                
                # Also check relational OrderLines
                lines = session.exec(select(OrderLineTable).where(OrderLineTable.order_id == o.id)).all()
                for line in lines:
                    if line.product_id: product_ids.add(line.product_id)
            return float(len(product_ids))
            
        elif target_type == 'customers':
            customer_ids = set()
            for o in relevant_orders:
                cid = getattr(o, 'customer_id', None)
                if cid:
                    customer_ids.add(cid)
            return float(len(customer_ids))

    return float(getattr(goal, 'current_value', 0) or 0)



@router.get("/goals")
async def list_goals():
    from sqlmodel import select
    result = []
    with Session(engine) as session:
        goals = session.exec(select(GoalTable)).all()
        for g in goals:
            d = g.model_dump() if hasattr(g, 'model_dump') else dict(g)
            try:
                d['current_value'] = _compute_current_value(g)
            except Exception as e:
                print(f"[goals] compute error for goal {getattr(g, 'id', '?')}: {e}")
                d['current_value'] = float(getattr(g, 'current_value', 0) or 0)
    
            if d.get('status') == 'active':
                target = float(getattr(g, 'target_value', 0) or 0)
                current = d['current_value']
                if target > 0 and current >= target:
                    d['status'] = 'achieved'
                    try:
                        g.status = 'achieved'
                        g.achieved_at = datetime.now()
                        session.add(g)
                        session.commit()
                    except Exception as e:
                        print(f"[goals] auto-achieve persist error: {e}")
    
            result.append(d)
    return result


@router.post("/goals")
async def create_goal(payload: GoalCreate, user: User = Depends(get_current_user)):
    data = payload.model_dump()
    with Session(engine) as session:
        row = GoalTable(
            title=data.get('title', ''),
            description=data.get('description', None),
            target_type=data.get('target_type', 'revenue'),
            target_value=float(data.get('target_value', 0) or 0),
            current_value=0.0,
            start_date=date.fromisoformat(str(data.get('start_date', date.today()))[:10]),
            end_date=date.fromisoformat(str(data.get('end_date', date.today()))[:10]),
            status=data.get('status', 'active'),
            created_by=user.id,
            created_at=datetime.utcnow(),
        )
        session.add(row)
        session.commit()
        session.refresh(row)

    d = row.model_dump()
    d['current_value'] = _compute_current_value(row)
    return d


@router.put("/goals/{goal_id}")
async def update_goal(goal_id: int, payload: GoalCreate, user: User = Depends(get_current_user)):
    with Session(engine) as session:
        row = session.get(GoalTable, goal_id)
        if not row:
            raise HTTPException(status_code=404, detail="Mục tiêu không tồn tại")
            
        update_data = payload.model_dump(exclude_unset=True)
        row.title = update_data.get('title', row.title)
        row.description = update_data.get('description', row.description)
        row.target_type = update_data.get('target_type', row.target_type)
        row.target_value = float(update_data.get('target_value', row.target_value) or 0)
        
        if 'start_date' in update_data:
            row.start_date = date.fromisoformat(str(update_data['start_date'])[:10])
        if 'end_date' in update_data:
            row.end_date = date.fromisoformat(str(update_data['end_date'])[:10])
            
        row.status = update_data.get('status', row.status)
        session.add(row)
        session.commit()
        session.refresh(row)

        d = row.model_dump()
        d['current_value'] = _compute_current_value(row)
        return d


@router.delete("/goals/{goal_id}")
async def delete_goal(goal_id: int, user: User = Depends(get_current_user)):
    with Session(engine) as session:
        row = session.get(GoalTable, goal_id)
        if not row:
            raise HTTPException(status_code=404, detail="Mục tiêu không tồn tại")
        session.delete(row)
        session.commit()
    return {"ok": True}
