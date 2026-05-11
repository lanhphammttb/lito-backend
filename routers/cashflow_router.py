"""Cash flow aggregation router — combines income and outflows from all sources."""
from typing import List, Optional
from datetime import date, datetime
from fastapi import APIRouter, Depends

from models.user import User
from services.auth import get_current_user

router = APIRouter()

# Injected by main.py
_payments: List = []
_expenses: List = []
_purchase_orders: List = []


def set_data_stores(payments, expenses, purchase_orders=None):
    global _payments, _expenses, _purchase_orders
    _payments = payments
    _expenses = expenses
    if purchase_orders is not None:
        _purchase_orders = purchase_orders


def _parse_date(v) -> Optional[date]:
    if isinstance(v, date):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        try:
            return date.fromisoformat(v[:10])
        except Exception:
            return None
    return None


@router.get("/transactions")
async def list_transactions(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    user: User = Depends(get_current_user),
):
    """Return all cash-flow transactions (income + outflow) within date range, newest first."""
    result = []

    # Income: customer payments
    for p in _payments:
        paid_date = _parse_date(getattr(p, "paid_date", None) or getattr(p, "created_at", None))
        if not paid_date:
            continue
        status = getattr(p, "status", "")
        if status in ("cancelled", "refunded", "failed"):
            continue
        if start_date and paid_date < start_date:
            continue
        if end_date and paid_date > end_date:
            continue
        result.append({
            "id": f"pay_{getattr(p, 'id', '')}",
            "date": str(paid_date),
            "type": "income",
            "category": "payment",
            "category_label": "Thu tiền đơn hàng",
            "amount": float(getattr(p, "amount", 0) or 0),
            "method": getattr(p, "method", "cash"),
            "note": f"Đơn #{getattr(p, 'order_id', '')}",
            "reference_id": getattr(p, "order_id", None),
        })

    # Outflow: operating expenses
    for e in _expenses:
        exp_date = _parse_date(getattr(e, "date", None))
        if not exp_date:
            continue
        if start_date and exp_date < start_date:
            continue
        if end_date and exp_date > end_date:
            continue
        cat = getattr(e, "category", "other")
        labels = {
            "rent": "Thuê mặt bằng", "utilities": "Điện/nước", "tools": "Dụng cụ",
            "personnel": "Nhân công", "marketing": "Quảng cáo", "packaging": "Bao bì",
            "other": "Chi phí khác",
        }
        result.append({
            "id": f"exp_{getattr(e, 'id', '')}",
            "date": str(exp_date),
            "type": "outflow",
            "category": cat,
            "category_label": labels.get(cat, cat),
            "amount": float(getattr(e, "amount", 0) or 0),
            "method": "cash",
            "note": getattr(e, "note", "") or "",
            "reference_id": None,
        })

    result.sort(key=lambda x: x["date"], reverse=True)
    return result


@router.get("/summary")
async def cashflow_summary(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    user: User = Depends(get_current_user),
):
    """Summary: total income, total outflow, net, breakdowns by category."""
    transactions = await list_transactions(start_date=start_date, end_date=end_date, user=user)

    total_in = sum(t["amount"] for t in transactions if t["type"] == "income")
    total_out = sum(t["amount"] for t in transactions if t["type"] == "outflow")
    net = round(total_in - total_out, 2)

    # Breakdown by category for outflows
    out_by_cat: dict = {}
    for t in transactions:
        if t["type"] == "outflow":
            key = t["category"]
            out_by_cat[key] = out_by_cat.get(key, {"label": t["category_label"], "amount": 0.0})
            out_by_cat[key]["amount"] = round(out_by_cat[key]["amount"] + t["amount"], 2)

    # Monthly breakdown (last 6 months in range)
    monthly: dict = {}
    for t in transactions:
        month = t["date"][:7]  # YYYY-MM
        if month not in monthly:
            monthly[month] = {"month": month, "income": 0.0, "outflow": 0.0}
        if t["type"] == "income":
            monthly[month]["income"] = round(monthly[month]["income"] + t["amount"], 2)
        else:
            monthly[month]["outflow"] = round(monthly[month]["outflow"] + t["amount"], 2)

    monthly_list = sorted(monthly.values(), key=lambda x: x["month"])
    for m in monthly_list:
        m["net"] = round(m["income"] - m["outflow"], 2)

    return {
        "total_in": round(total_in, 2),
        "total_out": round(total_out, 2),
        "net": net,
        "transaction_count": len(transactions),
        "out_by_category": [
            {"category": k, **v} for k, v in sorted(out_by_cat.items(), key=lambda x: -x[1]["amount"])
        ],
        "monthly": monthly_list,
    }
