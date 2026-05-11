# Hala Handmade Business OS - Backend

## 📁 Project Structure

```
backend/
├── main.py              # Application entry point
├── requirements.txt     # Python dependencies
├── .env                 # Environment variables
├── config/              # Configuration modules
│   ├── database.py      # Database connection & engine
│   ├── settings.py      # App settings (JWT, API keys)
│   └── __init__.py
├── models/              # SQLModel database models
│   ├── user.py
│   ├── product.py       # Product, variants, bundles, images, reviews
│   ├── material.py      # Materials & stock movements
│   ├── order.py         # Orders, returns, payments
│   ├── customer.py
│   ├── content.py       # Content plans, demand signals
│   ├── inventory.py     # Suppliers, purchase orders
│   ├── category.py
│   ├── season.py
│   ├── task.py
│   ├── issue.py
│   ├── idea.py
│   ├── experiment.py
│   ├── goal.py
│   ├── activity.py      # Activity & audit logs
│   ├── promo.py
│   ├── notifications.py
│   ├── settings_table.py
│   └── __init__.py
├── schemas/             # Pydantic request/response schemas
│   ├── auth.py
│   ├── product.py
│   ├── material.py
│   ├── order.py
│   ├── customer.py
│   ├── content.py
│   ├── inventory.py
│   ├── category.py
│   ├── season.py
│   ├── task.py
│   ├── issue.py
│   ├── idea.py
│   ├── experiment.py
│   ├── goal.py
│   ├── notifications.py
│   └── __init__.py
├── services/            # Business logic
│   ├── auth.py          # Authentication & JWT
│   ├── product.py       # Product operations
│   ├── order.py         # Order processing
│   ├── material.py      # Material management
│   ├── customer.py      # Customer metrics
│   ├── inventory.py     # Inventory & PO operations
│   ├── issue.py
│   ├── activity.py      # Logging services
│   ├── notification.py  # WebSocket & push notifications
│   └── __init__.py
├── routers/             # API endpoints
│   ├── auth.py          # /auth/*
│   ├── products.py      # /products/*
│   ├── materials.py     # /materials/*
│   ├── orders.py        # /orders/*
│   ├── customers.py     # /customers/*
│   ├── content.py       # /content/*
│   ├── inventory.py     # /inventory/*
│   ├── dashboard.py     # /dashboard/*
│   ├── settings.py      # /settings/*
│   ├── activity.py      # /activity/*
│   ├── tasks.py         # /tasks/*
│   ├── categories.py    # /categories/*
│   └── __init__.py
└── utils/               # Utility functions
    ├── validators.py    # Input validation
    ├── converters.py    # Data converters
    ├── helpers.py       # Helper functions
    └── __init__.py
```

## 🚀 Quick Start

```bash
# Create virtual environment
python -m venv .venv
.\.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Run server
python -m uvicorn main:app --reload --port 8000
```

## 📚 API Documentation

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 🔑 Environment Variables

```env
SECRET_KEY=your-secret-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
DATABASE_URL=sqlite:///./hala.db
```

## 🏗️ Architecture

### Modular Design

- **Config**: Database and application settings
- **Models**: SQLModel entities for database
- **Schemas**: Pydantic models for API
- **Services**: Business logic layer
- **Routers**: API endpoint handlers
- **Utils**: Helper utilities

### Data Flow

```
Request → Router → Service → Model → Database
                     ↓
                   Utils (validation, conversion)
```

## 📊 Key Features

- 🛍️ Product management with variants
- 📦 Order processing & returns
- 👥 Customer management
- 📊 Dashboard & analytics
- 🔔 Real-time notifications (WebSocket)
- 📝 Activity & audit logging
- 🔐 JWT authentication
- 📱 Mobile-ready API
