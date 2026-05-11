"""Customer services."""
from datetime import date
from fastapi import HTTPException
from sqlmodel import Session

from config.database import engine
from services.order import compute_order_totals

# In-memory data stores
customers = []
orders = []


def set_data_stores(c, o):
    """Set data stores."""
    global customers, orders
    customers = c
    orders = o


def find_customer(customer_id: int):
    """Find customer by ID."""
    for cust in customers:
        if cust.id == customer_id:
            return cust
    raise HTTPException(status_code=404, detail=f"Customer {customer_id} không tồn tại")


def compute_customer_metrics():
    """Compute metrics for all customers."""
    from models.customer import CustomerTable
    
    for cust in customers:
        cust.total_orders = 0
        cust.total_spent = 0
        cust.last_order_date = None
        cust.first_order_date = None
    
    for order in orders:
        if not order.customer_id:
            continue
        totals = compute_order_totals(order)
        cust = next((c for c in customers if c.id == order.customer_id), None)
        if not cust:
            continue
        cust.total_orders += 1
        cust.total_spent += totals["revenue"]
        if cust.last_order_date is None or order.date > cust.last_order_date:
            cust.last_order_date = order.date
        if cust.first_order_date is None or order.date < cust.first_order_date:
            cust.first_order_date = order.date
    
    # Persist to database
    with Session(engine) as session:
        for cust in customers:
            row = session.get(CustomerTable, cust.id)
            if row:
                row.total_orders = cust.total_orders
                row.total_spent = cust.total_spent
                row.last_order_date = cust.last_order_date
                row.first_order_date = cust.first_order_date
                session.add(row)
        session.commit()
