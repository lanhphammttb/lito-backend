"""
Hala Handmade Business OS - Main Application
Refactored modular FastAPI application with all necessary endpoints.
"""
import os
import json
from contextlib import asynccontextmanager
from datetime import datetime, date, timedelta
from typing import List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlmodel import Session, SQLModel, select

# Configuration
from config.settings import settings
from config.database import engine

# Routers
from routers.auth import router as auth_router
from routers.products import router as products_router, public_router as public_products_router, products, product_variants, product_bundles, product_images, product_reviews
from routers.materials import router as materials_router, materials, stock_movements
from routers.orders import router as orders_router, orders, order_returns, payments, shipping_updates, set_related_stores as set_order_related
from routers.customers import router as customers_router, customers, set_customer_orders
from routers.content import router as content_router, content_plans, demand_signals
from routers.inventory import router as inventory_router, suppliers, purchase_orders, set_data_stores as set_inventory_stores
from routers.legacy_analytics import router as analytics_router, set_data_stores as set_analytics_stores
from routers.ideas import router as ideas_router, set_data_stores as set_ideas_stores
from routers.goals_router import router as goals_router, set_data_stores as set_goals_stores
from routers.experiments_router import router as experiments_router, set_data_stores as set_experiments_stores
from routers.issues_router import router as issues_router, set_data_stores as set_issues_stores
from routers.strategy_router import router as strategy_router
from routers.growth_analytics_router import router as growth_analytics_router, set_data_stores as set_growth_stores
from routers.dashboard import router as dashboard_router, set_data_stores as set_dashboard_stores
from routers.settings import router as settings_router
from routers.upload import router as upload_router
from routers.product_images import router as product_images_router
from routers.activity import router as activity_router, activity_logs
from routers.tasks import router as tasks_router, tasks
from routers.categories import router as categories_router, categories
from routers.production import router as production_router, production_jobs
from routers.expenses import router as expenses_router, expenses, load_expenses
from routers.cashflow_router import router as cashflow_router, set_data_stores as set_cashflow_stores
from models.expense import ExpenseTable

# Services
from services.notification import ws_manager
from services import fcm as fcm_service
from services.auth import get_current_user, get_current_user_optional, hash_password
from services.material import get_low_stock_alerts
from services.order import compute_order_totals
import services.product as product_service
import services.order as order_service
import services.material as material_service
import services.customer as customer_service
import services.inventory as inventory_service
import services.issue as issue_service
import services.activity as activity_service

# Models
from models.user import User
from models import (
    UserTable, ProductTable, ProductVariantTable, ProductBundleTable,
    ProductImageTable, ProductReviewTable, MaterialTable, StockMovementTable,
    OrderTable, OrderReturnTable, PaymentTable, CustomerTable,
    ContentPlanTable, DemandSignalTable, SupplierTable, PurchaseOrderTable,
    CategoryTable, SeasonTable, TaskTable, IssueTable, IssueCommentTable,
    IdeaTable, ExperimentTable, GoalTable, ActivityLogTable, AuditLogTable,
    PromoCodeTable, SettingsTable, PushSubscriptionTable, MarketplaceSyncLogTable, FcmTokenTable,
    ProductionJobTable,
    Product, Material, Customer, Category, Task,
)
from models.content import ContentPlan, DemandSignal
from models.product import ProductVariant, ProductBundle, ProductImage, ProductReview
from models.material import StockMovement, MaterialBatchTable, MaterialBatch, MaterialPriceEntryTable
from models.order import OrderReturn
from models.inventory import Supplier, PurchaseOrder, PurchaseOrderLine
from models.issue import Issue as IssueModel
from models.idea import Idea as IdeaModel
from models.activity import ActivityLog
from models.experiment import Experiment as ExperimentModel
from models.goal import Goal as GoalModel
from models.content import DemandSignal as DemandSignalModel
from models.production import ProductionJob, ProductionMaterial


# ===================== In-memory data stores for additional entities =====================
issues: List[IssueModel] = []
issue_comments: List[dict] = []
ideas: List[IdeaModel] = []
experiments: List[ExperimentModel] = []
goals: List[GoalModel] = []
seasons: List[dict] = []
users: List[dict] = []
audit_logs: List[dict] = []
marketplace_logs: List[dict] = []
sent_notifications: List[dict] = []


from sqlmodel import Field as _SQLField

class _NotificationLog(SQLModel, table=True):
    __tablename__ = "notification_logs"
    id: Optional[int] = _SQLField(default=None, primary_key=True)
    title: str
    body: Optional[str] = None
    sent_by: Optional[str] = None
    sent_count: int = 1
    timestamp: datetime = _SQLField(default_factory=datetime.utcnow)


# ===================== Database Setup =====================
def create_db_and_tables():
    """Create all database tables."""
    SQLModel.metadata.create_all(engine)


def run_schema_migrations():
    """Add new columns to existing tables that may predate them."""
    from sqlalchemy import text
    migrations = [
        "ALTER TABLE suppliers ADD COLUMN note TEXT",
        "ALTER TABLE suppliers ADD COLUMN rating REAL",
        "ALTER TABLE materials ADD COLUMN supplier_id INTEGER",
        "ALTER TABLE materials ADD COLUMN base_unit TEXT",
        "ALTER TABLE materials ADD COLUMN on_hand_qty REAL DEFAULT 0",
        "ALTER TABLE materials ADD COLUMN reserved_qty REAL DEFAULT 0",
        "ALTER TABLE materials ADD COLUMN available_qty REAL DEFAULT 0",
        "ALTER TABLE products ADD COLUMN wastage_percent REAL DEFAULT 0",
        "ALTER TABLE products ADD COLUMN finished_qty INTEGER DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN updated_at TIMESTAMP",
        "ALTER TABLE production_jobs ALTER COLUMN order_id DROP NOT NULL",
        # Sync on_hand_qty from stock_quantity for rows where on_hand_qty was defaulted to 0
        "UPDATE materials SET on_hand_qty = stock_quantity WHERE on_hand_qty = 0 AND stock_quantity > 0",
        "UPDATE materials SET available_qty = stock_quantity - reserved_qty WHERE on_hand_qty > 0",
        "ALTER TABLE materials ADD COLUMN unit_type TEXT DEFAULT 'continuous'",
        "ALTER TABLE suppliers ADD COLUMN lead_time_days INTEGER",
        "ALTER TABLE purchase_orders ADD COLUMN paid_amount REAL DEFAULT 0",
        "ALTER TABLE purchase_orders ADD COLUMN payment_status TEXT DEFAULT 'unpaid'",
        "ALTER TABLE purchase_orders ALTER COLUMN supplier_id DROP NOT NULL",
    ]
    with Session(engine) as session:
        for sql in migrations:
            try:
                session.exec(text(sql))
                session.commit()
            except Exception:
                session.rollback()

    # Fix seeded goals that have future dates — move them to the current month
    import calendar as _cal
    _today = date.today()
    _ms = date(_today.year, _today.month, 1)
    _me = date(_today.year, _today.month, _cal.monthrange(_today.year, _today.month)[1])
    with Session(engine) as session:
        try:
            session.exec(text(
                f"UPDATE goals SET start_date = '{_ms}', end_date = '{_me}' "
                f"WHERE start_date > '{_today}'"
            ))
            session.commit()
        except Exception:
            session.rollback()


def seed_default_users():
    """Create default admin users if they don't exist."""
    default_users = [
        {"email": "admin@hala.vn", "password": "admin", "name": "Admin", "role": "ADMIN", "is_owner": True},
        {"email": "owner_a@example.com", "password": "admin", "name": "Owner A", "role": "ADMIN", "is_owner": True},
    ]

    with Session(engine) as session:
        for user_data in default_users:
            existing = session.exec(select(UserTable).where(UserTable.email == user_data["email"])).first()
            if not existing:
                new_user = UserTable(
                    name=user_data["name"],
                    email=user_data["email"],
                    password_hash=hash_password(user_data["password"]),
                    role=user_data["role"],
                    is_owner=user_data["is_owner"],
                    created_at=datetime.utcnow(),
                )
                session.add(new_user)
                print(f"  📧 Created user: {user_data['email']}")
        session.commit()


def seed_default_data():
    """Seed default data into empty tables — mirrors old branch DEFAULT_* constants."""
    today = date.today()
    with Session(engine) as s:
        # Categories (3)
        if not s.exec(select(CategoryTable)).first():
            for row in [
                CategoryTable(id=1, name="Trang trí"),
                CategoryTable(id=2, name="Quà tặng"),
                CategoryTable(id=3, name="Seasonal Collections", parent_id=1),
            ]:
                s.add(row)
            print("  🌱 Seeded categories")

        # Supplier 2 (Bao bì B) if missing
        if not s.exec(select(SupplierTable).where(SupplierTable.id == 2)).first():
            s.add(SupplierTable(id=2, name="Bao bì B", contact_name="Anh Nam", phone="0909988776", notes="Túi hộp, ribbon"))
            print("  🌱 Seeded supplier 2")

        # Customers (5 default)
        if s.exec(select(CustomerTable)).first() is None or len(s.exec(select(CustomerTable)).all()) < 2:
            defaults = [
                CustomerTable(id=1, name="Nguyễn Văn A", phone="0901234567", email="nguyenvana@example.com",
                              source="TikTok", tags_json='["VIP"]', total_orders=5, total_spent=2500000,
                              last_order_date=date(2024,11,20), first_order_date=date(2024,1,15), created_by=1, created_at=datetime(2024,1,15)),
                CustomerTable(id=2, name="Trần Thị B", phone="0912345678", email="tranthib@example.com",
                              source="Facebook", tags_json='["repeater"]', total_orders=3, total_spent=1200000,
                              last_order_date=date(2024,10,5), first_order_date=date(2024,3,10), created_by=1, created_at=datetime(2024,3,10)),
                CustomerTable(id=3, name="Lê Văn C", phone="0923456789", email="levanc@example.com",
                              source="Instagram", tags_json='[]', total_orders=1, total_spent=350000,
                              last_order_date=date(2024,6,25), first_order_date=date(2024,6,20), created_by=1, created_at=datetime(2024,6,20)),
                CustomerTable(id=4, name="Phạm Thị D", phone="0934567890", email="phamthid@example.com",
                              source="TikTok", tags_json='["VIP"]', total_orders=8, total_spent=4500000,
                              last_order_date=date(2024,11,28), first_order_date=date(2024,2,1), created_by=1, created_at=datetime(2024,2,1)),
                CustomerTable(id=5, name="Hoàng Văn E", phone="0945678901",
                              source="Zalo", tags_json='[]', total_orders=2, total_spent=800000,
                              last_order_date=date(2024,9,15), first_order_date=date(2024,8,10), created_by=1, created_at=datetime(2024,8,10)),
            ]
            for row in defaults:
                existing = s.exec(select(CustomerTable).where(CustomerTable.id == row.id)).first()
                if not existing:
                    s.add(row)
            print("  🌱 Seeded customers")

        # Content Plans (2)
        if not s.exec(select(ContentPlanTable)).first():
            for row in [
                ContentPlanTable(id=1, title="Quá trình móc Bé ma Noel", platform="TikTok",
                                 status="Đã đăng", scheduled_date=today, related_product_id=1,
                                 estimate_views=5000, created_by=1),
                ContentPlanTable(id=2, title="Set up bàn làm việc chuẩn Noel", platform="Instagram Reels",
                                 status="Ý tưởng", scheduled_date=date(today.year, today.month, min(today.day+2,28)),
                                 related_product_id=3, estimate_views=2000, created_by=1),
            ]:
                s.add(row)
            print("  🌱 Seeded content_plans")

        # Experiments (2)
        if not s.exec(select(ExperimentTable)).first():
            for row in [
                ExperimentTable(id=1, name="Test thumbnail CTA",
                                hypothesis="CTA rõ ràng tăng inbox", metric="inquiries",
                                start_date=today, status="running",
                                variant_a="CTA mờ", variant_b="CTA rõ + giá",
                                description="Đo inbox/1000 views trong 7 ngày", created_by=1),
                ExperimentTable(id=2, name="Giảm giá 10% bó hoa",
                                hypothesis="Giảm giá tăng đơn +20%", metric="orders",
                                start_date=today, status="paused",
                                variant_a="Giá cũ", variant_b="Giá -10%",
                                description="Dừng tạm do thiếu nguyên liệu", created_by=1),
            ]:
                s.add(row)
            print("  🌱 Seeded experiments")

        # Goals (2)
        if not s.exec(select(GoalTable)).first():
            month_start = date(today.year, today.month, 1)
            import calendar
            month_end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
            for row in [
                GoalTable(id=1, title=f"Doanh thu tháng {today.month}", target_type="revenue",
                          target_value=10000000, current_value=0,
                          start_date=month_start, end_date=month_end,
                          status="active", created_by=1),
                GoalTable(id=2, title=f"Đơn hàng tháng {today.month}", target_type="orders",
                          target_value=50, current_value=0,
                          start_date=month_start, end_date=month_end,
                          status="active", created_by=1),
            ]:
                s.add(row)
            print("  🌱 Seeded goals")

        # Demand Signals (4) - dates within last 60 days so analytics can detect them
        if not s.exec(select(DemandSignalTable)).first():
            for row in [
                DemandSignalTable(id=1, product_id=1, week_of=today - timedelta(days=50), views=1200, inquiries=45, saves=30, created_by=1),
                DemandSignalTable(id=2, product_id=1, week_of=today - timedelta(days=35), views=1500, inquiries=60, saves=42, created_by=1),
                DemandSignalTable(id=3, product_id=1, week_of=today - timedelta(days=20), views=2100, inquiries=55, saves=50, created_by=1),
                DemandSignalTable(id=4, product_id=2, week_of=today - timedelta(days=20), views=800, inquiries=25, saves=18, created_by=1),
            ]:
                s.add(row)
            print("  🌱 Seeded demand_signals")

        # Product Images (3)
        if not s.exec(select(ProductImageTable)).first():
            for row in [
                ProductImageTable(id=1, product_id=1, url="https://placehold.co/400x400?text=Be+ma+Noel", is_primary=True),
                ProductImageTable(id=2, product_id=1, url="https://placehold.co/400x400?text=Be+ma+Noel+2", is_primary=False),
                ProductImageTable(id=3, product_id=2, url="https://placehold.co/400x400?text=Ech+may+man", is_primary=True),
            ]:
                s.add(row)
            print("  🌱 Seeded product_images")

        # Product Reviews (3)
        if not s.exec(select(ProductReviewTable)).first():
            for row in [
                ProductReviewTable(id=1, product_id=1, customer_name="Linh", rating=5, content="Đẹp và chắc tay"),
                ProductReviewTable(id=2, product_id=1, customer_name="Huy", rating=4, content="Giao nhanh, giá ổn"),
                ProductReviewTable(id=3, product_id=2, customer_name="My", rating=5, content="Bạn bè thích lắm"),
            ]:
                s.add(row)
            print("  🌱 Seeded product_reviews")

        # Product Bundles (1)
        if not s.exec(select(ProductBundleTable)).first():
            s.add(ProductBundleTable(id=1, parent_product_id=1, child_product_id=3, quantity=1))
            print("  🌱 Seeded product_bundles")

        s.commit()


def load_settings_from_db():
    """Load persisted settings from DB into in-memory app_settings."""
    try:
        with Session(engine) as session:
            row = session.exec(select(SettingsTable).where(SettingsTable.id == 1)).first()
            if not row:
                return
            for field in SettingsTable.model_fields:
                if field == "id":
                    continue
                val = getattr(row, field, None)
                if val is not None and hasattr(settings, field):
                    try:
                        setattr(settings, field, val)
                    except Exception:
                        pass
            print(f"✅ Settings loaded: logo={'set' if settings.business_logo else 'none'}, shop={settings.shop_name}")
    except Exception as e:
        print(f"⚠ Could not load settings from DB: {e}")


def init_services():
    """Initialize services with data stores."""
    product_service.set_data_stores(products, materials, demand_signals, issues)
    order_service.set_data_stores(orders, order_returns, [], stock_movements, materials)
    material_service.set_data_stores(materials)
    customer_service.set_data_stores(customers, orders)
    set_customer_orders(orders)
    inventory_service.set_data_stores(suppliers, purchase_orders, materials, stock_movements)
    issue_service.set_data_stores(issues)
    activity_service.set_data_stores(activity_logs, audit_logs)
    set_dashboard_stores(orders, products, materials, customers, tasks, purchase_orders, expenses, seasons, goals)
    set_order_related(products, customers, users, content_plans)
    set_inventory_stores(materials, products)
    try:
        set_analytics_stores(products, orders, materials, customers, activity_logs, content_plans, issues, ideas, experiments, goals, demand_signals)
    except Exception as e:
        print("Legacy analytics data mount err:", e)
    set_ideas_stores(ideas, products)
    set_goals_stores(goals, orders, expenses)
    set_experiments_stores(experiments)
    set_issues_stores(issues, issue_comments, users, products)
    set_growth_stores(products, orders, materials, customers, content_plans, demand_signals)
    set_cashflow_stores(payments, expenses, purchase_orders)


def load_data_from_sql():
    """Load data from SQL database into memory."""
    with Session(engine) as session:
        # Products
        from models.product import MaterialUsage
        for row in session.exec(select(ProductTable)).all():
            try:
                mat_usages = [MaterialUsage(**m) for m in json.loads(row.materials_json)] if row.materials_json and row.materials_json != "[]" else []
                tags = json.loads(row.tags_json) if row.tags_json and row.tags_json != "[]" else []
                cats = json.loads(row.categories_json) if row.categories_json and row.categories_json != "[]" else []
                seasons_list = json.loads(row.seasons_json) if row.seasons_json and row.seasons_json != "[]" else []
            except Exception:
                mat_usages = tags = cats = seasons_list = []
            products.append(Product(
                id=row.id, name=row.name, base_price=row.base_price,
                price=getattr(row, 'price', row.base_price) or row.base_price,
                time_minutes=row.time_minutes or 0, difficulty=row.difficulty or 1,
                wastage_percent=getattr(row, "wastage_percent", 0) or 0,
                lifecycle_status=row.lifecycle_status or "idea",
                role=row.role or "core",
                notes=row.notes,
                tags=tags, categories=cats, seasons=seasons_list,
                packaging_cost=row.packaging_cost or 0,
                marketing_cost=row.marketing_cost or 0,
                platform_fee_percent=row.platform_fee_percent or 0,
                priority=row.priority or 1,
                demand_score=row.demand_score or 0,
                feasibility_score=row.feasibility_score or 0,
                finished_qty=getattr(row, "finished_qty", 0) or 0,
                created_by=row.created_by,
                updated_by=row.updated_by,
                materials=mat_usages, created_at=row.created_at, updated_at=row.updated_at,
            ))

        # Materials
        for row in session.exec(select(MaterialTable)).all():
            stock_qty = row.stock_quantity or 0
            reserved_qty = getattr(row, "reserved_qty", None) or 0
            on_hand_qty = getattr(row, "on_hand_qty", None) or 0
            # on_hand_qty was added later with DEFAULT 0 — fall back to stock_quantity for old data
            if on_hand_qty == 0 and stock_qty > 0:
                on_hand_qty = stock_qty
            available_qty = max(0.0, on_hand_qty - reserved_qty)
            materials.append(Material(
                id=row.id, code=row.code, name=row.name, type=row.type,
                unit=row.unit, unit_type=getattr(row, "unit_type", None) or "continuous",
                unit_price=row.unit_price, stock_quantity=row.stock_quantity,
                base_unit=getattr(row, "base_unit", None),
                on_hand_qty=on_hand_qty,
                reserved_qty=reserved_qty,
                available_qty=available_qty,
                low_threshold=row.low_threshold, supplier_id=getattr(row, "supplier_id", None),
                note=row.note, created_at=row.created_at,
            ))

        # Orders
        for row in session.exec(select(OrderTable)).all():
            try:
                order_lines = json.loads(row.order_lines_json) if row.order_lines_json else []
                shipping_updates_json = json.loads(row.shipping_updates_json) if row.shipping_updates_json else []
                from models.order import Order, OrderLine
                from models.order import ShippingUpdate
                orders.append(Order(
                    id=row.id, channel=row.channel, status=row.status,
                    payment_status=row.payment_status, customer_id=row.customer_id,
                    date=row.order_date, estimated_delivery_date=row.estimated_delivery_date,
                    shipping_fee=row.shipping_fee,
                    discount=row.discount,
                    promo_code=row.promo_code,
                    shipping_carrier=row.shipping_carrier,
                    tracking_number=row.tracking_number,
                    note=row.note,
                    maker_user_id=row.maker_user_id,
                    source_content_id=row.source_content_id,
                    updated_by=row.updated_by,
                    order_lines=[OrderLine(**l) for l in order_lines] if order_lines else [],
                    shipping_updates=[ShippingUpdate(**u) for u in shipping_updates_json] if shipping_updates_json else [],
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                ))
            except Exception as e:
                print(f"  ⚠ Order {row.id} load error: {e}")

        # Customers
        for row in session.exec(select(CustomerTable)).all():
            try:
                customers.append(Customer(
                    id=row.id, name=row.name, phone=row.phone, email=row.email,
                    address=row.address, source=row.source,
                    tags=json.loads(row.tags_json) if row.tags_json else [],
                    notes=row.notes, total_orders=row.total_orders or 0,
                    total_spent=row.total_spent or 0.0,
                    last_order_date=row.last_order_date, first_order_date=row.first_order_date,
                    created_by=row.created_by, created_at=row.created_at
                ))
            except Exception as e:
                print(f"  ⚠ Customer {row.id} load error: {e}")
        # Categories
        for row in session.exec(select(CategoryTable)).all():
            categories.append(Category(
                id=row.id, name=row.name, description=row.description,
                parent_id=row.parent_id, created_at=row.created_at,
            ))

        # Tasks
        for row in session.exec(select(TaskTable)).all():
            try:
                _tags = json.loads(row.tags_json) if row.tags_json else []
            except Exception:
                _tags = []
            tasks.append(Task(
                id=row.id, title=row.title, description=row.description,
                status=row.status or "todo", priority=row.priority or 1,
                assignee_id=row.assignee_id, due_date=row.due_date,
                tags=_tags,
                created_by=row.created_by, created_at=row.created_at,
            ))

        # Users
        for row in session.exec(select(UserTable)).all():
            users.append({"id": row.id, "name": row.name, "email": row.email, "role": row.role})

        # Seasons
        for row in session.exec(select(SeasonTable)).all():
            seasons.append({"id": row.id, "name": row.name, "start_date": str(row.from_date) if row.from_date else None,
                             "end_date": str(row.to_date) if row.to_date else None})

        # Suppliers
        for row in session.exec(select(SupplierTable)).all():
            try:
                suppliers.append(Supplier(
                    id=row.id, name=row.name, contact_name=row.contact_name,
                    phone=row.phone, email=row.email, address=row.address,
                    notes=row.notes, note=getattr(row, "note", None),
                    rating=getattr(row, "rating", None),
                    lead_time_days=getattr(row, "lead_time_days", None),
                    created_at=row.created_at,
                ))
            except Exception as e:
                print(f"  ⚠ Supplier {row.id} load error: {e}")

        # Purchase Orders
        for row in session.exec(select(PurchaseOrderTable)).all():
            try:
                lines = json.loads(row.lines_json) if row.lines_json else []
                purchase_orders.append(PurchaseOrder(
                    id=row.id, supplier_id=row.supplier_id, status=row.status,
                    payment_status=getattr(row, "payment_status", None) or "unpaid",
                    expected_date=row.expected_date, received_at=row.received_at,
                    note=row.note, total_amount=row.total_amount,
                    paid_amount=getattr(row, "paid_amount", None) or 0,
                    lines=[PurchaseOrderLine(**l) for l in lines] if lines else [],
                    created_by=row.created_by, created_at=row.created_at,
                ))
            except Exception as e:
                print(f"  ⚠ PurchaseOrder {row.id} load error: {e}")

        # Stock Movements
        for row in session.exec(select(StockMovementTable)).all():
            try:
                stock_movements.append(StockMovement(
                    id=row.id, material_id=row.material_id,
                    quantity_change=row.quantity_change, movement_type=row.movement_type,
                    reference_type=row.reference_type, reference_id=row.reference_id,
                    batch_id=row.batch_id, expiry_date=row.expiry_date,
                    unit_price=row.unit_price, new_price=row.new_price,
                    user_id=row.user_id, note=row.note, created_at=row.created_at,
                ))
            except Exception as e:
                print(f"  ⚠ StockMovement {row.id} load error: {e}")

        # Payments
        from models.order import Payment as PaymentModel
        for row in session.exec(select(PaymentTable)).all():
            try:
                payments.append(PaymentModel(
                    id=row.id, order_id=row.order_id, amount=row.amount,
                    method=row.method, status=row.status,
                    transaction_id=row.transaction_id, paid_date=row.paid_date,
                    notes=row.notes, created_at=row.created_at,
                ))
            except Exception as e:
                print(f"  ⚠ Payment {row.id} load error: {e}")

        # Material batches are queried on-demand (not loaded into memory)

        # Issues
        for row in session.exec(select(IssueTable)).all():
            try:
                issues.append(IssueModel(
                    id=row.id, product_id=row.product_id, type=row.type,
                    description=row.description, evidence=row.evidence,
                    hypothesis=row.hypothesis, next_action=row.next_action,
                    priority=row.priority, status=row.status,
                    assigned_to=row.assigned_to, impact_revenue=row.impact_revenue,
                    is_template=row.is_template, resolution_hours=row.resolution_hours,
                    resolved_at=row.resolved_at, comments_count=row.comments_count,
                    created_by=row.created_by, created_at=row.created_at,
                ))
            except Exception as e:
                print(f"  ⚠ Issue {row.id} load error: {e}")

        # Ideas
        for row in session.exec(select(IdeaTable)).all():
            try:
                ideas.append(IdeaModel(
                    id=row.id, title=row.title, description=row.description,
                    source=row.source, status=row.status, priority=row.priority,
                    estimated_time=getattr(row, 'estimated_time', None),
                    estimated_price=getattr(row, 'estimated_price', None),
                    created_by=row.created_by, updated_by=row.updated_by,
                    created_at=row.created_at,
                ))
            except Exception as e:
                print(f"  ⚠ Idea {row.id} load error: {e}")

        # Activity Logs
        for row in session.exec(select(ActivityLogTable)).all():
            try:
                import ast as _ast
                _changes = None
                if row.changes:
                    try:
                        _changes = json.loads(row.changes)
                    except Exception:
                        try:
                            _changes = _ast.literal_eval(row.changes)
                        except Exception:
                            _changes = {}
                activity_logs.append(ActivityLog(
                    id=row.id, user_id=row.user_id, entity_type=row.entity_type,
                    entity_id=row.entity_id, action=row.action,
                    changes=_changes,
                    created_at=row.created_at,
                ))
            except Exception as e:
                print(f"  ⚠ ActivityLog {row.id} load error: {e}")

        # Audit Logs
        for row in session.exec(select(AuditLogTable)).all():
            try:
                audit_logs.append({
                    "id": row.id,
                    "user_id": row.user_id,
                    "user_name": row.user_name,
                    "action": row.action,
                    "table_name": row.table_name,
                    "record_id": row.record_id,
                    "before_data": json.loads(row.before_data) if row.before_data else None,
                    "after_data": json.loads(row.after_data) if row.after_data else None,
                    "ip_address": row.ip_address,
                    "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                })
            except Exception as e:
                print(f"  ⚠ AuditLog {row.id} load error: {e}")

        # Notification Logs
        try:
            for row in session.exec(select(_NotificationLog).order_by(_NotificationLog.timestamp.desc()).limit(100)).all():
                sent_notifications.append({
                    "id": row.id, "title": row.title, "body": row.body,
                    "sent_by": row.sent_by, "sent_count": row.sent_count,
                    "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                })
        except Exception as e:
            print(f"  ⚠ NotificationLog load error: {e}")

        # Content Plans
        for row in session.exec(select(ContentPlanTable)).all():
            try:
                content_plans.append(ContentPlan(
                    id=row.id, title=row.title, platform=row.platform,
                    channel=row.channel, format=row.format, status=row.status,
                    scheduled_date=row.scheduled_date, related_product_id=row.related_product_id,
                    created_by=row.created_by, created_at=row.created_at,
                ))
            except Exception as e:
                print(f"  ⚠ ContentPlan {row.id} load error: {e}")

        # Demand Signals
        for row in session.exec(select(DemandSignalTable)).all():
            try:
                demand_signals.append(DemandSignalModel(
                    id=row.id, product_id=row.product_id, week_of=row.week_of,
                    views=row.views, inquiries=row.inquiries, saves=row.saves,
                    created_by=row.created_by, created_at=row.created_at,
                ))
            except Exception as e:
                print(f"  ⚠ DemandSignal {row.id} load error: {e}")

        # Experiments
        for row in session.exec(select(ExperimentTable)).all():
            try:
                experiments.append(ExperimentModel(
                    id=row.id, name=row.name, description=row.description,
                    hypothesis=row.hypothesis, status=row.status,
                    start_date=row.start_date, end_date=row.end_date,
                    variant_a=row.variant_a, variant_b=row.variant_b,
                    metric=row.metric, result_a=row.result_a, result_b=row.result_b,
                    winner=row.winner, conclusion=row.conclusion,
                    created_by=row.created_by, created_at=row.created_at,
                ))
            except Exception as e:
                print(f"  ⚠ Experiment {row.id} load error: {e}")

        # Goals
        for row in session.exec(select(GoalTable)).all():
            try:
                goals.append(GoalModel(
                    id=row.id, title=row.title, description=row.description,
                    target_type=row.target_type, target_value=row.target_value,
                    current_value=row.current_value, start_date=row.start_date,
                    end_date=row.end_date, status=row.status,
                    achieved_at=row.achieved_at, created_by=row.created_by,
                    created_at=row.created_at,
                ))
            except Exception as e:
                print(f"  ⚠ Goal {row.id} load error: {e}")

        # Product Images
        for row in session.exec(select(ProductImageTable)).all():
            try:
                product_images.append(ProductImage(
                    id=row.id, product_id=row.product_id, url=row.url,
                    is_primary=row.is_primary,
                ))
            except Exception as e:
                print(f"  ⚠ ProductImage {row.id} load error: {e}")

        # Product Reviews
        for row in session.exec(select(ProductReviewTable)).all():
            try:
                product_reviews.append(ProductReview(
                    id=row.id, product_id=row.product_id, rating=row.rating,
                    content=row.content, customer_name=row.customer_name,
                    created_at=row.created_at,
                ))
            except Exception as e:
                print(f"  ⚠ ProductReview {row.id} load error: {e}")

        # Product Bundles
        for row in session.exec(select(ProductBundleTable)).all():
            try:
                product_bundles.append(ProductBundle(
                    id=row.id, parent_product_id=row.parent_product_id,
                    child_product_id=row.child_product_id, quantity=row.quantity,
                ))
            except Exception as e:
                print(f"  ⚠ ProductBundle {row.id} load error: {e}")

        # Production Jobs
        for row in session.exec(select(ProductionJobTable)).all():
            try:
                materials_json = json.loads(row.materials_json) if row.materials_json else []
                production_jobs.append(ProductionJob(
                    id=row.id,
                    order_id=row.order_id,
                    product_id=row.product_id,
                    product_name=row.product_name,
                    quantity=row.quantity,
                    status=row.status,
                    assigned_to=row.assigned_to,
                    notes=row.notes,
                    planned_minutes=row.planned_minutes,
                    started_at=row.started_at,
                    due_at=row.due_at,
                    completed_at=row.completed_at,
                    materials=[ProductionMaterial(**item) for item in materials_json],
                    created_by=row.created_by,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                ))
            except Exception as e:
                print(f"  ⚠ ProductionJob {row.id} load error: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    print("🚀 Starting Hala Handmade Business OS...")
    create_db_and_tables()
    run_schema_migrations()
    seed_default_users()
    seed_default_data()
    load_data_from_sql()
    load_expenses()
    load_settings_from_db()
    init_services()
    print(f"✅ Loaded: products={len(products)}, materials={len(materials)}, orders={len(orders)}, customers={len(customers)}, categories={len(categories)}, suppliers={len(suppliers)}, purchase_orders={len(purchase_orders)}, stock_movements={len(stock_movements)}, content_plans={len(content_plans)}, demand_signals={len(demand_signals)}, experiments={len(experiments)}, goals={len(goals)}, product_images={len(product_images)}, product_reviews={len(product_reviews)}, product_bundles={len(product_bundles)}, issues={len(issues)}, ideas={len(ideas)}, activity_logs={len(activity_logs)}")
    print("✅ Application ready!")
    yield
    print("👋 Shutting down...")


# ===================== Create FastAPI Application =====================
app = FastAPI(
    title="Hala Handmade Business OS",
    description="Complete business management system for handmade businesses",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===================== Include All Routers =====================
app.include_router(ideas_router, tags=["Ideas"])
app.include_router(goals_router, tags=["Goals"])
app.include_router(experiments_router, tags=["Experiments"])
app.include_router(issues_router, tags=["Issues"])
app.include_router(strategy_router, tags=["Strategy"])
app.include_router(growth_analytics_router, tags=["Growth Analytics"])
app.include_router(analytics_router, tags=["Analytics Legacy"])
app.include_router(auth_router, prefix="/auth", tags=["Auth"])
app.include_router(public_products_router, tags=["Public Products"])
app.include_router(products_router, prefix="/products", tags=["Products"])
app.include_router(materials_router, prefix="/materials", tags=["Materials"])
app.include_router(orders_router, prefix="/orders", tags=["Orders"])
app.include_router(customers_router, prefix="/customers", tags=["Customers"])
app.include_router(content_router, prefix="/content", tags=["Content"])
app.include_router(inventory_router, prefix="/inventory", tags=["Inventory"])
app.include_router(inventory_router, tags=["Inventory Compat"])  # backward-compat: /suppliers, /purchase-orders, /suggestions
app.include_router(dashboard_router, prefix="/dashboard", tags=["Dashboard"])
app.include_router(settings_router, prefix="/settings", tags=["Settings"])
app.include_router(upload_router, prefix="/upload", tags=["Upload"])
app.include_router(product_images_router, prefix="/product-images", tags=["Product Images"])
app.include_router(activity_router, prefix="/activity", tags=["Activity"])
app.include_router(tasks_router, prefix="/tasks", tags=["Tasks"])
app.include_router(categories_router, prefix="/categories", tags=["Categories"])
app.include_router(production_router, prefix="/production-jobs", tags=["Production"])
app.include_router(expenses_router, prefix="/expenses", tags=["Expenses"])
app.include_router(cashflow_router, prefix="/cashflow", tags=["CashFlow"])


# ===================== Root Level API Endpoints =====================

@app.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    """Get current user info."""
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role, "is_owner": user.is_owner}


@app.get("/users")
async def list_users(user: User = Depends(get_current_user)):
    """List all users."""
    return users


@app.get("/alerts")
async def get_alerts(user: User = Depends(get_current_user)):
    """Get system alerts."""
    low_stock = get_low_stock_alerts()
    pending_tasks = len([t for t in tasks if t.status != "done"])

    today = date.today()
    with Session(engine) as session:
        order_rows = session.exec(select(OrderTable)).all()
    overdue_orders = [
        {
            "id": o.id,
            "date": o.order_date.isoformat() if o.order_date else None,
            "status": o.status,
            "days_overdue": (today - o.order_date).days if o.order_date else 0
        }
        for o in order_rows
        if o.status not in ("delivered", "cancelled") and o.order_date and (today - o.order_date).days > 7
    ]

    return {
        "low_stock": low_stock[:10],
        "overdue_orders": overdue_orders[:10],
        "pending_tasks": pending_tasks,
        "notifications": []
    }




# ===================== Content Plans =====================




@app.put("/content-plans/{plan_id}")
async def update_content_plan(plan_id: int, payload: dict, user: User = Depends(get_current_user)):
    """Update content plan."""
    plan = next((c for c in content_plans if c.id == plan_id), None)
    if not plan:
        raise HTTPException(404, "Content plan không tồn tại")
    for key in ["title", "content_type", "platform", "scheduled_date", "status", "notes"]:
        if key in payload:
            setattr(plan, key, payload[key])
    return {"id": plan.id, "title": plan.title, "status": plan.status}






# ===================== Ideas =====================




@app.put("/ideas/{idea_id}")
async def update_idea(idea_id: int, payload: dict, user: User = Depends(get_current_user)):
    """Update idea."""
    idea = next((i for i in ideas if i.id == idea_id), None)
    if not idea:
        raise HTTPException(404, "Idea không tồn tại")
    for k, v in payload.items():
        if hasattr(idea, k):
            setattr(idea, k, v)
    return idea


# ===================== Issues =====================
# NOTE: All /issues endpoints are handled by routers/legacy_analytics.py (analytics_router)






@app.get("/issue-templates")
async def list_issue_templates(user: User = Depends(get_current_user)):
    """List issue templates."""
    return [
        {"id": 1, "name": "Lỗi chất lượng", "description": "Template cho vấn đề chất lượng sản phẩm"},
        {"id": 2, "name": "Thiếu nguyên liệu", "description": "Template cho vấn đề thiếu nguyên liệu"},
    ]




# ===================== Demand Signals =====================
@app.get("/demand")
async def list_demand_signals(product_id: int = None, user: User = Depends(get_current_user)):
    """Get demand signals."""
    result = [{"id": d.id, "product_id": d.product_id, "week_of": str(d.week_of),
               "views": d.views, "inquiries": d.inquiries, "saves": d.saves} for d in demand_signals]
    if product_id:
        result = [d for d in result if d["product_id"] == product_id]
    return result


@app.post("/demand")
async def create_demand_signal(payload: dict, user: User = Depends(get_current_user)):
    """Create demand signal."""
    from datetime import date as date_type
    new_id = max((d.id for d in demand_signals), default=0) + 1
    signal = DemandSignal(
        id=new_id, product_id=payload.get("product_id"),
        week_of=payload.get("week_of") or date_type.today(),
        views=payload.get("views", 0), inquiries=payload.get("inquiries", 0),
        saves=payload.get("saves", 0), created_by=user.id,
    )
    demand_signals.append(signal)
    return {"id": signal.id, "product_id": signal.product_id}


# ===================== Product Related =====================
@app.get("/bundles")
async def list_bundles(parent_product_id: int = None, user: User = Depends(get_current_user)):
    """List product bundles."""
    result = [{"id": b.id, "parent_product_id": b.parent_product_id, "child_product_id": b.child_product_id,
               "quantity": b.quantity} for b in product_bundles]
    if parent_product_id:
        result = [b for b in result if b["parent_product_id"] == parent_product_id]
    return result


@app.post("/bundles")
async def create_bundle(payload: dict, user: User = Depends(get_current_user)):
    """Create product bundle."""
    new_id = max((b.id for b in product_bundles), default=0) + 1
    bundle = ProductBundle(
        id=new_id, parent_product_id=payload.get("parent_product_id", payload.get("bundle_product_id")),
        child_product_id=payload.get("child_product_id"), quantity=payload.get("quantity", 1),
    )
    product_bundles.append(bundle)
    return {"id": bundle.id}


@app.get("/reviews")
async def list_reviews(product_id: int = None, user: User = Depends(get_current_user)):
    """List product reviews."""
    result = [{"id": r.id, "product_id": r.product_id, "rating": r.rating, "content": r.content,
               "customer_name": r.customer_name} for r in product_reviews]
    if product_id:
        result = [r for r in result if r["product_id"] == product_id]
    return result


@app.post("/reviews")
async def create_review(payload: dict, user: User = Depends(get_current_user)):
    """Create product review."""
    new_id = max((r.id for r in product_reviews), default=0) + 1
    review = ProductReview(
        id=new_id, product_id=payload.get("product_id"), rating=payload.get("rating", 5),
        comment=payload.get("comment"), customer_name=payload.get("customer_name", "Khách hàng"),
        created_at=datetime.utcnow(),
    )
    product_reviews.append(review)
    return {"id": review.id}


@app.get("/product-images")
async def list_product_images(product_id: int = None, user: User = Depends(get_current_user)):
    """List product images."""
    result = [{"id": img.id, "product_id": img.product_id, "url": img.url, "is_primary": img.is_primary}
              for img in product_images]
    if product_id:
        result = [img for img in result if img["product_id"] == product_id]
    return result


@app.post("/product-images")
async def create_product_image(payload: dict, user: User = Depends(get_current_user)):
    """Create product image."""
    new_id = max((img.id for img in product_images), default=0) + 1
    image = ProductImage(
        id=new_id, product_id=payload.get("product_id"), url=payload.get("url"),
        is_primary=payload.get("is_primary", False),
    )
    product_images.append(image)
    return {"id": image.id}


@app.get("/products/{product_id}/history")
async def get_product_history(product_id: int, user: User = Depends(get_current_user)):
    """Get product history."""
    return {"price_changes": [], "lifecycle": []}


@app.get("/products/summary")
async def get_products_summary(user: User = Depends(get_current_user)):
    """Get products summary."""
    return {"total": len(products), "active": len([p for p in products if getattr(p, 'status', 'active') == 'active']), "out_of_stock": 0}


# ===================== Variants =====================
@app.get("/variants")
async def list_variants(product_id: int = None, user: User = Depends(get_current_user)):
    """List product variants."""
    result = [{"id": v.id, "product_id": v.product_id, "name": v.name, "sku": v.sku,
               "price_adjustment": v.price_adjustment} for v in product_variants]
    if product_id:
        result = [v for v in result if v["product_id"] == product_id]
    return result


@app.post("/variants")
async def create_variant(payload: dict, user: User = Depends(get_current_user)):
    """Create product variant."""
    new_id = max((v.id for v in product_variants), default=0) + 1
    variant = ProductVariant(
        id=new_id, product_id=payload.get("product_id"), name=payload.get("name"),
        sku=payload.get("sku"), price_adjustment=payload.get("price_adjustment", 0),
        attributes=payload.get("attributes", {}),
    )
    product_variants.append(variant)
    return {"id": variant.id}


@app.put("/variants/{variant_id}")
async def update_variant(variant_id: int, payload: dict, user: User = Depends(get_current_user)):
    """Update variant."""
    variant = next((v for v in product_variants if v.id == variant_id), None)
    if not variant:
        raise HTTPException(404, "Variant không tồn tại")
    for key in ["name", "sku", "price_adjustment", "attributes"]:
        if key in payload:
            setattr(variant, key, payload[key])
    return {"id": variant.id}


@app.delete("/variants/{variant_id}")
async def delete_variant(variant_id: int, user: User = Depends(get_current_user)):
    """Delete variant."""
    global product_variants
    product_variants = [v for v in product_variants if v.id != variant_id]
    return {"success": True}


# ===================== Stock Movements =====================
@app.get("/stock-movements")
async def list_stock_movements(material_id: int = None, user: User = Depends(get_current_user)):
    """List stock movements — always read from DB so new movements appear immediately."""
    from models.material import StockMovementTable
    from sqlmodel import Session, select as sql_select
    with Session(engine) as session:
        stmt = sql_select(StockMovementTable).order_by(StockMovementTable.created_at.desc())
        if material_id:
            stmt = stmt.where(StockMovementTable.material_id == material_id)
        rows = session.exec(stmt).all()
    return [
        {
            "id": r.id, "material_id": r.material_id, "quantity_change": r.quantity_change,
            "movement_type": r.movement_type, "reference_type": r.reference_type,
            "reference_id": r.reference_id, "unit_price": r.unit_price,
            "note": r.note, "created_at": str(r.created_at) if r.created_at else None,
        }
        for r in rows
    ]


@app.post("/stock-movements")
async def create_stock_movement(payload: dict, user: User = Depends(get_current_user)):
    """Create stock movement via stock ledger (persists to SQL + updates balances)."""
    from services.stock_ledger import apply_adjustment, record_purchase
    from services.material import find_material, save_material_sql

    material_id = int(payload.get("material_id"))
    qty_change = float(payload.get("quantity_change", payload.get("quantity", 0)))
    movement_type = payload.get("movement_type", "adjustment")
    note = payload.get("note")
    new_price = payload.get("new_price")

    if movement_type == "purchase":
        movement = record_purchase(
            material_id=material_id,
            quantity=qty_change,
            user_id=user.id,
            reference_id=payload.get("reference_id"),
            note=note,
        )
    else:
        movement = apply_adjustment(
            material_id=material_id,
            quantity_change=qty_change,
            user_id=user.id,
            note=note,
        )

    if new_price is not None and float(new_price) > 0:
        mat = find_material(material_id)
        mat.unit_price = float(new_price)
        save_material_sql(mat)

    return movement


# ===================== Returns =====================
@app.get("/returns")
async def list_returns(order_id: int = None, user: User = Depends(get_current_user)):
    """List order returns."""
    result = [{"id": r.id, "order_id": r.order_id, "reason": r.reason, "status": r.status,
               "refund_amount": r.refund_amount} for r in order_returns]
    if order_id:
        result = [r for r in result if r["order_id"] == order_id]
    return result


@app.post("/returns")
async def create_return(payload: dict, user: User = Depends(get_current_user)):
    """Create order return."""
    new_id = max((r.id for r in order_returns), default=0) + 1
    ret = OrderReturn(
        id=new_id, order_id=payload.get("order_id"), reason=payload.get("reason"),
        status="pending", refund_amount=payload.get("refund_amount", 0), created_at=datetime.utcnow(),
    )
    order_returns.append(ret)
    return {"id": ret.id}


# ===================== Payments =====================
@app.get("/payments")
async def list_payments(order_id: int = None, user: User = Depends(get_current_user)):
    """List payments."""
    result = [{"id": p.id, "order_id": p.order_id, "amount": p.amount, "method": p.method,
               "status": p.status} for p in payments]
    if order_id:
        result = [p for p in result if p["order_id"] == order_id]
    return result


@app.post("/payments")
async def create_payment(payload: dict, user: User = Depends(get_current_user)):
    """Create payment."""
    from models.order import Payment
    new_id = max((p.id for p in payments), default=0) + 1
    payment = Payment(
        id=new_id, order_id=payload.get("order_id"), amount=payload.get("amount"),
        method=payload.get("method", "cash"), status="completed", created_at=datetime.utcnow(),
    )
    payments.append(payment)
    return {"id": payment.id}


# ===================== Seasons =====================
@app.get("/seasons")
async def list_seasons(user: User = Depends(get_current_user)):
    """List seasons."""
    return seasons


@app.post("/seasons")
async def create_season(payload: dict, user: User = Depends(get_current_user)):
    """Create season."""
    from models.season import SeasonTable
    from datetime import date as date_type
    new_id = max((s["id"] for s in seasons), default=0) + 1
    with Session(engine) as session:
        row = SeasonTable(
            id=new_id, name=payload["name"],
            from_date=payload.get("from_date") or payload.get("start_date"),
            to_date=payload.get("to_date") or payload.get("end_date"),
            description=payload.get("description"),
            created_by=user.id,
        )
        session.add(row)
        session.commit()
    seasons.append({"id": new_id, "name": payload["name"],
                    "start_date": str(row.from_date), "end_date": str(row.to_date)})
    return seasons[-1]


@app.put("/seasons/{season_id}")
async def update_season(season_id: int, payload: dict, user: User = Depends(get_current_user)):
    """Update season."""
    from models.season import SeasonTable
    season = next((s for s in seasons if s["id"] == season_id), None)
    if not season:
        raise HTTPException(404, "Không tìm thấy mùa / dịp")
    season["name"] = payload.get("name", season["name"])
    from_date = payload.get("from_date") or payload.get("start_date")
    to_date = payload.get("to_date") or payload.get("end_date")
    if from_date:
        season["start_date"] = str(from_date)
    if to_date:
        season["end_date"] = str(to_date)
    with Session(engine) as session:
        row = session.get(SeasonTable, season_id)
        if row:
            row.name = season["name"]
            if from_date:
                row.from_date = from_date
            if to_date:
                row.to_date = to_date
            if "description" in payload:
                row.description = payload["description"]
            session.add(row)
            session.commit()
    return season


@app.delete("/seasons/{season_id}")
async def delete_season(season_id: int, user: User = Depends(get_current_user)):
    """Delete season."""
    global seasons
    seasons = [s for s in seasons if s["id"] != season_id]
    with Session(engine) as session:
        from models.season import SeasonTable
        row = session.get(SeasonTable, season_id)
        if row:
            session.delete(row)
            session.commit()
    return {"success": True}


# ===================== Purchase Orders (auto-create only — CRUD handled by inventory router) =====================


@app.post("/purchase-orders/auto-create")
async def auto_create_purchase_orders(material_ids: list = Body(...), user: User = Depends(get_current_user)):
    """Auto-create purchase orders grouped by supplier from material.supplier_id."""
    from models.inventory import PurchaseOrder, PurchaseOrderLine, PurchaseOrderTable
    import json as _json

    low_stock = get_low_stock_alerts()
    alert_map = {m["material_id"]: m for m in low_stock}
    material_map = {m.id: m for m in materials}

    # Group lines by supplier_id (None → group 0 = "no supplier")
    groups: dict = {}
    for mid in material_ids:
        alert = alert_map.get(mid)
        if not alert:
            continue
        mat = material_map.get(mid)
        supplier_id = getattr(mat, "supplier_id", None) or 0
        threshold = alert.get("low_threshold") or 10
        current = alert.get("stock_quantity") or 0
        unit_price = alert.get("unit_price") or 0
        suggested_qty = max(threshold * 2 - current, threshold)
        groups.setdefault(supplier_id, []).append(
            PurchaseOrderLine(material_id=mid, quantity=suggested_qty, unit_price=unit_price)
        )

    now = datetime.utcnow()
    created = 0
    for supplier_id, lines in groups.items():
        lines_json = _json.dumps([l.model_dump(mode="json") for l in lines])
        total = sum(l.quantity * l.unit_price for l in lines)
        po_row = PurchaseOrderTable(
            supplier_id=supplier_id,
            status="draft",
            note="Tự động tạo từ gợi ý tồn kho",
            lines_json=lines_json,
            total_amount=total,
            created_by=user.id,
            created_at=now,
        )
        with Session(engine) as session:
            session.add(po_row)
            session.commit()
            session.refresh(po_row)
        po = PurchaseOrder(
            id=po_row.id, supplier_id=supplier_id, status="draft",
            note=po_row.note, lines=lines, total_amount=total,
            created_by=user.id, created_at=now,
        )
        purchase_orders.append(po)
        created += 1

    return {"created_count": created}


@app.post("/purchase-orders/generate")
async def generate_purchase_order(payload: dict, user: User = Depends(get_current_user)):
    """Generate purchase order from suggestions."""
    return {"id": 1, "status": "pending", "items": payload.get("items", [])}


# ===================== Experiments =====================




@app.put("/experiments/{exp_id}")
async def update_experiment(exp_id: int, payload: dict, user: User = Depends(get_current_user)):
    """Update experiment."""
    exp = next((e for e in experiments if e.id == exp_id), None)
    if not exp:
        raise HTTPException(404, "Experiment không tồn tại")
    for k, v in payload.items():
        if hasattr(exp, k):
            setattr(exp, k, v)
    return exp


@app.delete("/experiments/{exp_id}")
async def delete_experiment(exp_id: int, user: User = Depends(get_current_user)):
    """Delete experiment."""
    global experiments
    experiments = [e for e in experiments if e.id != exp_id]
    return {"success": True}



# ===================== Audit Logs =====================
@app.get("/audit-logs")
async def list_audit_logs(
    skip: int = 0, limit: int = 100,
    page: int = 1, page_size: int = 50,
    action: Optional[str] = None,
    user_id: Optional[int] = None,
    table_name: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    user: User = Depends(get_current_user)
):
    """List audit logs with page/skip pagination support."""
    result = sorted(audit_logs, key=lambda x: x.get("timestamp", ""), reverse=True)
    if action:
        result = [l for l in result if l.get("action") == action]
    if user_id:
        result = [l for l in result if l.get("user_id") == user_id]
    if table_name:
        result = [l for l in result if l.get("table_name") == table_name]
    if start_date:
        result = [l for l in result if l.get("timestamp", "")[:10] >= str(start_date)]
    if end_date:
        result = [l for l in result if l.get("timestamp", "")[:10] <= str(end_date)]
    total = len(result)
    # Support both skip/limit and page/page_size
    if skip > 0:
        offset, per_page = skip, limit
    else:
        offset = (page - 1) * page_size
        per_page = page_size
    return {"items": result[offset:offset + per_page], "total": total}


@app.get("/audit-logs/stats")
async def get_audit_stats(user: User = Depends(get_current_user)):
    """Get audit log statistics."""
    by_action: dict = {}
    by_user: dict = {}
    for log in audit_logs:
        a = log.get("action", "unknown")
        by_action[a] = by_action.get(a, 0) + 1
        u = str(log.get("user_id", "?"))
        by_user[u] = by_user.get(u, 0) + 1
    return {"total": len(audit_logs), "total_actions": len(audit_logs), "by_action": by_action, "by_user": by_user}


# ===================== Marketplace =====================
@app.get("/marketplace/logs")
async def get_marketplace_logs(marketplace: str = None, platform: str = None, limit: int = 50, user: User = Depends(get_current_user)):
    """Get marketplace sync logs."""
    filter_val = marketplace or platform
    result = marketplace_logs[:]
    if filter_val:
        result = [l for l in result if l.get("marketplace") == filter_val or l.get("platform") == filter_val]
    return {"logs": result[:limit]}


@app.post("/marketplace/sync")
async def sync_marketplace(payload: dict, user: User = Depends(get_current_user)):
    """Sync with marketplace."""
    mkt = payload.get("marketplace") or payload.get("platform", "shopee")
    log = {
        "id": len(marketplace_logs) + 1,
        "marketplace": mkt,
        "platform": mkt,
        "status": "completed",
        "synced_at": datetime.utcnow().isoformat(),
        "orders_synced": 0,
        "items_synced": 0,
    }
    marketplace_logs.append(log)
    return log


# ===================== Notifications =====================
@app.post("/notifications/subscribe")
async def subscribe_push(payload: dict, user: User = Depends(get_current_user)):
    """Register push notification subscription."""
    endpoint = payload.get("endpoint", "")
    keys = payload.get("keys", {})
    with Session(engine) as session:
        existing = session.exec(
            select(PushSubscriptionTable).where(PushSubscriptionTable.endpoint == endpoint)
        ).first()
        if existing:
            existing.user_id = user.id
            session.add(existing)
        else:
            session.add(PushSubscriptionTable(
                user_id=user.id,
                endpoint=endpoint,
                p256dh=keys.get("p256dh", ""),
                auth=keys.get("auth", "")
            ))
        session.commit()
    return {"message": "Subscription registered"}


@app.delete("/notifications/unsubscribe")
async def unsubscribe_push(endpoint: str, user: User = Depends(get_current_user)):
    """Unsubscribe from push notifications."""
    with Session(engine) as session:
        sub = session.exec(
            select(PushSubscriptionTable).where(
                PushSubscriptionTable.endpoint == endpoint,
                PushSubscriptionTable.user_id == user.id
            )
        ).first()
        if sub:
            session.delete(sub)
            session.commit()
    return {"message": "Unsubscribed"}


@app.post("/notifications/fcm-token")
async def register_fcm_token(payload: dict, user: User = Depends(get_current_user)):
    """Register FCM device token for push notifications when app is closed."""
    token = payload.get("token", "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="FCM token required")
    with Session(engine) as session:
        existing = session.exec(
            select(FcmTokenTable).where(FcmTokenTable.token == token)
        ).first()
        if existing:
            existing.user_id = user.id
            existing.updated_at = datetime.now()
            session.add(existing)
        else:
            session.add(FcmTokenTable(
                user_id=user.id,
                token=token,
                device_info=payload.get("device_info", "")
            ))
        session.commit()
    return {"message": "FCM token registered"}


@app.delete("/notifications/fcm-token")
async def remove_fcm_token(payload: dict, user: User = Depends(get_current_user)):
    """Remove FCM token (on logout)."""
    token = payload.get("token", "")
    with Session(engine) as session:
        row = session.exec(
            select(FcmTokenTable).where(
                FcmTokenTable.token == token,
                FcmTokenTable.user_id == user.id
            )
        ).first()
        if row:
            session.delete(row)
            session.commit()
    return {"message": "FCM token removed"}


@app.get("/notifications")
async def list_notifications(limit: int = 50, user: User = Depends(get_current_user)):
    """Get sent notification history from DB."""
    try:
        with Session(engine) as session:
            rows = session.exec(
                select(_NotificationLog).order_by(_NotificationLog.timestamp.desc()).limit(limit)
            ).all()
            return [{"id": r.id, "title": r.title, "body": r.body, "sent_by": r.sent_by,
                     "sent_count": r.sent_count, "timestamp": r.timestamp.isoformat()} for r in rows]
    except Exception:
        return sent_notifications[:limit]


@app.post("/notifications/send")
async def send_notification(payload: dict, user: User = Depends(get_current_user)):
    """Send notification via WebSocket (online) + FCM (offline/background)."""
    ts = datetime.now()
    title = payload.get("title", "")
    body = payload.get("body", "")
    notification_data = {
        "type": "notification",
        "title": title,
        "body": body,
        "data": payload.get("data", {}),
        "timestamp": ts.isoformat(),
    }
    user_ids = payload.get("user_ids")
    # 1. WebSocket for online users
    if user_ids:
        for uid in user_ids:
            await ws_manager.send_personal_message(notification_data, uid)
    else:
        await ws_manager.broadcast(notification_data)

    # 2. FCM for offline/background users
    with Session(engine) as session:
        if user_ids:
            tokens_rows = session.exec(
                select(FcmTokenTable).where(FcmTokenTable.user_id.in_(user_ids))
            ).all()
        else:
            tokens_rows = session.exec(select(FcmTokenTable)).all()
        tokens = [r.token for r in tokens_rows]
    fcm_sent = fcm_service.send_many(tokens, title, body, payload.get("data", {})) if tokens else 0

    sent_count = len(user_ids) if user_ids else 1
    record = {
        "title": notification_data["title"],
        "body": notification_data["body"],
        "sent_by": user.name or user.email,
        "sent_count": sent_count,
        "timestamp": ts.isoformat(),
    }
    # Persist to DB
    try:
        with Session(engine) as session:
            row = _NotificationLog(
                title=record["title"], body=record["body"],
                sent_by=record["sent_by"], sent_count=sent_count, timestamp=ts,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            record["id"] = row.id
    except Exception:
        record["id"] = len(sent_notifications) + 1
    sent_notifications.insert(0, record)
    return {"success": True, "message": "Notification sent", "sent_count": sent_count, "fcm_sent": fcm_sent}


@app.post("/notifications/test")
async def test_notification(user: User = Depends(get_current_user)):
    """Test notification."""
    await ws_manager.broadcast({"type": "notification", "title": "Test", "body": "Test notification", "timestamp": datetime.now().isoformat()})
    return {"success": True, "message": "Test notification sent"}


# ===================== Backup =====================
@app.post("/backup")
async def create_backup(user: User = Depends(get_current_user)):
    """Create system backup."""
    return {"success": True, "backup_id": datetime.utcnow().strftime("%Y%m%d_%H%M%S")}


# ===================== Orders Summary =====================
# NOTE: /inventory/summary is handled by routers/inventory.py (full summary with materials, products, suppliers)
# NOTE: /orders/summary is handled by routers/orders.py (includes products, customers, users)


# ===================== WebSocket =====================
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    """WebSocket for real-time notifications."""
    await ws_manager.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, user_id)


# ===================== Health & Root =====================
@app.get("/health")
async def health_check():
    """Health check."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat(), "version": "2.0.0"}


@app.get("/")
async def root():
    """Root endpoint."""
    return {"name": "Hala Handmade Business OS", "version": "2.0.0", "docs": "/docs"}


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler."""
    print(f"[ERROR] {type(exc).__name__}: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
