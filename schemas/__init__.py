"""Request/Response schemas package."""
from .auth import LoginRequest, TokenResponse
from .product import ProductBase, ProductCreate, ProductVariantCreate, ProductBundleCreate, ProductImageCreate, ProductReviewCreate
from .material import MaterialCreate, StockMovementCreate
from .order import OrderCreate, OrderReturnCreate, PaymentCreate, ShippingUpdatePayload
from .customer import CustomerCreate
from .content import ContentPlanCreate, ContentPerformanceUpdate, DemandSignalCreate
from .inventory import SupplierCreate, PurchaseOrderCreate
from .category import CategoryCreate
from .season import SeasonCreate
from .task import TaskCreate, TaskUpdate
from .issue import IssueCreate, IssueCommentCreate, IssueFromTemplateRequest
from .idea import IdeaCreate
from .experiment import ExperimentCreate, ExperimentUpdate
from .goal import GoalCreate
from .notifications import PushSubscription, NotificationPayload
from .marketplace import MarketplaceSyncRequest, MarketplaceOrder
from .bulk import BulkImportRequest, BulkImportResponse
from .forecast import ForecastRequest, ForecastResponse

__all__ = [
    # Auth
    "LoginRequest", "TokenResponse",
    # Product
    "ProductBase", "ProductCreate", "ProductVariantCreate", "ProductBundleCreate",
    "ProductImageCreate", "ProductReviewCreate",
    # Material
    "MaterialCreate", "StockMovementCreate",
    # Order
    "OrderCreate", "OrderReturnCreate", "PaymentCreate", "ShippingUpdatePayload",
    # Customer
    "CustomerCreate",
    # Content
    "ContentPlanCreate", "ContentPerformanceUpdate", "DemandSignalCreate",
    # Inventory
    "SupplierCreate", "PurchaseOrderCreate",
    # Others
    "CategoryCreate", "SeasonCreate",
    "TaskCreate", "TaskUpdate",
    "IssueCreate", "IssueCommentCreate", "IssueFromTemplateRequest",
    "IdeaCreate",
    "ExperimentCreate", "ExperimentUpdate",
    "GoalCreate",
    "PushSubscription", "NotificationPayload",
    "MarketplaceSyncRequest", "MarketplaceOrder",
    "BulkImportRequest", "BulkImportResponse",
    "ForecastRequest", "ForecastResponse",
]
