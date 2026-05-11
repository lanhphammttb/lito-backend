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
        if row.tags:
            try:
                # Handle both json string and comma-separated
                tags = json.loads(row.tags) if row.tags.startswith('[') else [t.strip() for t in row.tags.split(',') if t.strip()]
            except:
                tags = []
                
        return Customer(
            id=row.id, name=row.name, phone=row.phone, email=row.email,
            address=row.address, note=row.note, segment=row.segment,
            source=row.source, tags=tags, total_orders=row.total_orders,
            total_spent=row.total_spent, last_order_date=row.last_order_date,
            first_order_date=row.first_order_date, created_at=row.created_at,
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
                revenue = getattr(o, "revenue", 0) or 0
                
                cust.total_orders += 1
                cust.total_spent += revenue
                
                o_date = None
                if o.date:
                    from datetime import datetime, date
                    if isinstance(o.date, datetime):
                        o_date = o.date.date()
                    elif isinstance(o.date, date):
                        o_date = o.date
                    elif isinstance(o.date, str):
                        try:
                            o_date = date.fromisoformat(o.date[:10])
                        except Exception:
                            pass
                            
                if o_date:
                    if cust.last_order_date is None or o_date > cust.last_order_date:
                        cust.last_order_date = o_date
                    if cust.first_order_date is None or o_date < cust.first_order_date:
                        cust.first_order_date = o_date
            
            session.add(cust)
            
        session.commit()
