"""
Application bootstrap, startup loading, and legacy in-memory store hydration.
"""
import os
import json
from contextlib import asynccontextmanager
from datetime import datetime, date, timedelta

from fastapi import FastAPI
from sqlmodel import Session, SQLModel, select

# Configuration
from config.settings import settings
from config.database import engine, close_mongo_connection

# Routers
from routers.products import products, product_bundles, product_images, product_reviews
from routers.materials import materials, stock_movements
from routers.orders import orders, order_returns, payments, set_related_stores as set_order_related
from routers.customers import customers, set_customer_orders
from routers.content import content_plans, demand_signals
from routers.inventory import suppliers, purchase_orders, set_data_stores as set_inventory_stores
from routers.legacy_analytics import set_data_stores as set_analytics_stores
from routers.goals_router import set_data_stores as set_goals_stores
from routers.experiments_router import set_data_stores as set_experiments_stores
from routers.issues_router import set_data_stores as set_issues_stores
from routers.growth_analytics_router import set_data_stores as set_growth_stores
from routers.dashboard import set_data_stores as set_dashboard_stores
from routers.activity import activity_logs
from routers.tasks import tasks
from routers.categories import categories
from routers.production import production_jobs
from routers.expenses import expenses, load_expenses
from routers.cashflow_router import set_data_stores as set_cashflow_stores

# Services
from services.auth import hash_password
import services.product as product_service
import services.order as order_service
import services.material as material_service
import services.customer as customer_service
import services.inventory as inventory_service
import services.issue as issue_service
import services.activity as activity_service

# Models
from models import (
    UserTable, ProductTable, ProductBundleTable,
    ProductImageTable, ProductReviewTable, MaterialTable, StockMovementTable,
    OrderTable, PaymentTable, CustomerTable,
    ContentPlanTable, DemandSignalTable, SupplierTable, PurchaseOrderTable,
    CategoryTable, SeasonTable, TaskTable, IssueTable,
    IdeaTable, ExperimentTable, GoalTable, ActivityLogTable, AuditLogTable,
    SettingsTable,
    ProductionJobTable,
    Product, Material, Customer, Category, Task,
)
from models.content import ContentPlan
from models.product import ProductBundle, ProductImage, ProductReview
from models.material import StockMovement
from models.inventory import Supplier, PurchaseOrder, PurchaseOrderLine
from utils.datetime import utcnow
from models.activity import ActivityLog
from models.experiment import Experiment as ExperimentModel
from models.goal import Goal as GoalModel
from models.content import DemandSignal as DemandSignalModel
from models.production import ProductionJob, ProductionMaterial
from legacy_state import (
    NotificationLog,
    audit_logs,
    experiments,
    goals,
    issue_comments,
    issues,
    seasons,
    sent_notifications,
    users,
)


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
        """
        CREATE TABLE IF NOT EXISTS strategy_items (
            id INTEGER PRIMARY KEY,
            kind VARCHAR NOT NULL,
            data_json VARCHAR NOT NULL DEFAULT '{}',
            created_by INTEGER,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_strategy_items_kind ON strategy_items (kind)",
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
    """Create bootstrap admin users only when explicitly configured."""
    default_users = []

    bootstrap_email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip()
    bootstrap_password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "").strip()
    if bootstrap_email and bootstrap_password:
        default_users.append(
            {
                "email": bootstrap_email,
                "password": bootstrap_password,
                "name": os.getenv("BOOTSTRAP_ADMIN_NAME", "Bootstrap Admin").strip() or "Bootstrap Admin",
                "role": "ADMIN",
                "is_owner": True,
            }
        )

    owner_a_password = os.getenv("OWNER_A_PASSWORD", "").strip()
    if owner_a_password:
        default_users.append(
            {
                "email": "owner_a@example.com",
                "password": owner_a_password,
                "name": "Owner A",
                "role": "ADMIN",
                "is_owner": True,
            }
        )

    owner_b_password = os.getenv("OWNER_B_PASSWORD", "").strip()
    if owner_b_password:
        default_users.append(
            {
                "email": "owner_b@example.com",
                "password": owner_b_password,
                "name": "Owner B",
                "role": "ADMIN",
                "is_owner": True,
            }
        )

    shared_admin_password = os.getenv("ADMIN_DEFAULT_PASSWORD", "").strip()
    if shared_admin_password:
        for email, name in (
            ("owner_a@example.com", "Owner A"),
            ("owner_b@example.com", "Owner B"),
        ):
            if not any(user["email"] == email for user in default_users):
                default_users.append(
                    {
                        "email": email,
                        "password": shared_admin_password,
                        "name": name,
                        "role": "ADMIN",
                        "is_owner": True,
                    }
                )

    if not default_users:
        print("ℹ No bootstrap admin credentials configured; skipping user seeding.")
        return

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
                    created_at=utcnow(),
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
        set_analytics_stores(products, orders, materials, customers, activity_logs, content_plans, issues, experiments, goals, demand_signals)
    except Exception as e:
        print("Legacy analytics data mount err:", e)
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
            for row in session.exec(select(NotificationLog).order_by(NotificationLog.timestamp.desc()).limit(100)).all():
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
    auto_init_db = os.getenv("AUTO_INIT_DB_ON_STARTUP", "false").lower() == "true"
    auto_seed_data = os.getenv("AUTO_SEED_DATA_ON_STARTUP", "false").lower() == "true"

    try:
        if auto_init_db:
            create_db_and_tables()
            run_schema_migrations()
        else:
            print("ℹ Skipping automatic DB init/migrations on startup.")

        seed_default_users()
        if auto_seed_data:
            seed_default_data()
        else:
            print("ℹ Skipping automatic seed data on startup.")
        load_data_from_sql()
        load_expenses()
        load_settings_from_db()
        init_services()
        print(f"✅ Loaded: products={len(products)}, materials={len(materials)}, orders={len(orders)}, customers={len(customers)}, categories={len(categories)}, suppliers={len(suppliers)}, purchase_orders={len(purchase_orders)}, stock_movements={len(stock_movements)}, content_plans={len(content_plans)}, demand_signals={len(demand_signals)}, experiments={len(experiments)}, goals={len(goals)}, product_images={len(product_images)}, product_reviews={len(product_reviews)}, product_bundles={len(product_bundles)}, issues={len(issues)}, activity_logs={len(activity_logs)}")
        print("✅ Application ready!")
        yield
    finally:
        close_mongo_connection()
        engine.dispose()
        print("👋 Shutting down...")
