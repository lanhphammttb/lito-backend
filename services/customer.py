"""Customer services."""
from datetime import date
import json
from fastapi import HTTPException
from sqlmodel import Session

from config.database import engine
from services.order import compute_order_totals

# In-memory data stores
customers = []
orders = []


def order_revenue(order):
    lines = json.loads(order.order_lines_json or "[]")
    return sum(float(line.get("unit_price", 0)) * float(line.get("quantity", 0)) for line in lines) + (order.shipping_fee or 0) - (order.discount or 0)


def customer_segment(customer):
    tags = json.loads(customer.tags_json or "[]")
    if "VIP" in tags:
        return "VIP"
    return "repeater" if customer.total_orders > 1 else "new"


def set_data_stores(c, o):
    """Set data stores."""
    global customers, orders
    customers = c
    orders = o


def find_customer(customer_id: int):
    """Find customer by ID from Database."""
    from sqlmodel import Session
    from config.database import engine
    from models.customer import CustomerTable, Customer
    with Session(engine) as session:
        row = session.get(CustomerTable, customer_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Customer {customer_id} không tồn tại")
        
        tags = []
        import json
        if row.tags_json:
            try:
                # Handle both json string and comma-separated
                tags = json.loads(row.tags_json)
            except:
                tags = []
                
        return Customer(
            id=row.id, name=row.name, phone=row.phone, email=row.email,
            address=row.address, notes=row.notes,
            source=row.source, tags=tags, total_orders=row.total_orders,
            total_spent=row.total_spent, last_order_date=row.last_order_date,
            first_order_date=row.first_order_date, created_at=row.created_at,
            created_by=row.created_by,
        )


def compute_customer_metrics():
    """Compute metrics for all customers from Database."""
    from models.customer import CustomerTable
    from models.order import OrderTable
    from sqlmodel import Session, select
    
    with Session(engine) as session:
        customers_list = session.exec(select(CustomerTable)).all()
        
        for cust in customers_list:
            orders_list = session.exec(select(OrderTable).where(OrderTable.customer_id == cust.id)).all()
            
            cust.total_orders = 0
            cust.total_spent = 0
            cust.last_order_date = None
            cust.first_order_date = None
            
            for o in orders_list:
                if o.status == "cancelled":
                    continue
                revenue = order_revenue(o)
                
                cust.total_orders += 1
                cust.total_spent += revenue
                
                o_date = None
                if o.order_date:
                    from datetime import datetime, date
                    if isinstance(o.order_date, datetime):
                        o_date = o.order_date.date()
                    elif isinstance(o.order_date, date):
                        o_date = o.order_date
                    elif isinstance(o.order_date, str):
                        try:
                            o_date = date.fromisoformat(o.order_date[:10])
                        except Exception:
                            pass
                            
                if o_date:
                    if cust.last_order_date is None or o_date > cust.last_order_date:
                        cust.last_order_date = o_date
                    if cust.first_order_date is None or o_date < cust.first_order_date:
                        cust.first_order_date = o_date
            
            session.add(cust)
            
        session.commit()
