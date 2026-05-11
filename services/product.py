"""Product services."""
from typing import Dict, List, Optional
from fastapi import HTTPException

from config.settings import settings

# In-memory cache for product costs
_product_cost_cache: Dict[int, Dict[str, float]] = {}

# These will be injected from data store
products = []
materials = []
demand_signals = []
issues = []


def set_data_stores(p, m, d, i):
    """Set data stores for products, materials, demand signals, issues."""
    global products, materials, demand_signals, issues
    products = p
    materials = m
    demand_signals = d
    issues = i


def find_product(product_id: int):
    """Find product by ID."""
    for product in products:
        if product.id == product_id:
            return product
    raise HTTPException(status_code=404, detail=f"Product {product_id} không tồn tại")


def find_material_internal(material_id: int):
    """Find material by ID (internal use)."""
    for material in materials:
        if material.id == material_id:
            return material
    return None


def compute_product_cost(product) -> Dict[str, float]:
    """Compute full cost breakdown for a product."""
    material_cost = 0.0
    for usage in product.materials:
        material = find_material_internal(usage.material_id)
        if material:
            wastage_percent = (getattr(product, "wastage_percent", 0) or 0) + (getattr(usage, "wastage_percent", 0) or 0)
            material_cost += material.unit_price * usage.quantity * (1 + max(0.0, wastage_percent) / 100)

    labor_cost = (product.time_minutes / 60) * settings.hourly_rate
    packaging_cost = getattr(product, "packaging_cost", 0) or 0
    marketing_cost = getattr(product, "marketing_cost", 0) or 0
    platform_fee_percent = getattr(product, "platform_fee_percent", 0) or 0
    platform_fee_amount = product.base_price * platform_fee_percent / 100
    cost_breakdown = getattr(product, "cost_breakdown", None) or {}
    packaging_cost += cost_breakdown.get("packaging", 0) if isinstance(cost_breakdown, dict) else 0
    marketing_cost += cost_breakdown.get("marketing", 0) if isinstance(cost_breakdown, dict) else 0
    other_cost = cost_breakdown.get("other", 0) if isinstance(cost_breakdown, dict) else 0

    profit_per_unit = product.base_price - material_cost - labor_cost - packaging_cost - marketing_cost - platform_fee_amount - other_cost
    profit_margin = profit_per_unit / product.base_price if product.base_price else 0

    # Feasibility scoring
    time_score = max(0, 1 - (product.time_minutes / 240)) * 100
    difficulty_score = max(0, (5 - product.difficulty) / 5) * 100
    priority_score = (getattr(product, "priority", 1) or 1) / 5 * 100
    demand_score = (getattr(product, "demand_score", 0) or 0)

    # Trend score from demand signals
    trend_score = 50
    product_signals = sorted([d for d in demand_signals if d.product_id == product.id], key=lambda x: x.week_of)
    if len(product_signals) >= 2:
        latest, prev = product_signals[-1], product_signals[-2]
        delta = latest.views - prev.views
        base = prev.views or 1
        trend_score = max(0, min(100, 50 + (delta / base) * 50))

    open_issues = [i for i in issues if i.product_id == product.id and i.status != "resolved"]
    issue_health = max(0, 100 - len(open_issues) * 20)

    profit_per_hour = 0
    if product.time_minutes > 0:
        profit_per_hour = (profit_per_unit / product.time_minutes) * 60
    profit_score = max(0, min(100, profit_per_hour / 100000 * 100))

    feasibility_score = (
        demand_score * 0.4
        + profit_score * 0.3
        + trend_score * 0.2
        + issue_health * 0.1
    )
    feasibility_score = max(0, min(100, feasibility_score))

    # Capacity calculation
    capacities = []
    for usage in product.materials:
        material = find_material_internal(usage.material_id)
        if material and usage.quantity > 0:
            wastage_percent = (getattr(product, "wastage_percent", 0) or 0) + (getattr(usage, "wastage_percent", 0) or 0)
            effective_qty = usage.quantity * (1 + max(0.0, wastage_percent) / 100)
            capacities.append((material.stock_quantity or 0) // effective_qty)
    max_units = int(min(capacities)) if capacities else None

    shortage_materials = []
    for usage in product.materials:
        material = find_material_internal(usage.material_id)
        wastage_percent = (getattr(product, "wastage_percent", 0) or 0) + (getattr(usage, "wastage_percent", 0) or 0)
        required_qty = usage.quantity * (1 + max(0.0, wastage_percent) / 100)
        if material and material.stock_quantity < required_qty:
            shortage_materials.append({
                "material_id": usage.material_id,
                "need": required_qty,
                "have": material.stock_quantity,
                "code": material.code,
            })

    return {
        "material_cost": round(material_cost, 2),
        "labor_cost": round(labor_cost, 2),
        "packaging_cost": round(packaging_cost, 2),
        "marketing_cost": round(marketing_cost, 2),
        "other_cost": round(other_cost, 2),
        "platform_fee_amount": round(platform_fee_amount, 2),
        "profit_per_unit": round(profit_per_unit, 2),
        "profit_margin": round(profit_margin, 4),
        "profit_per_hour": round(profit_per_hour, 2),
        "feasibility_score": round(feasibility_score, 4),
        "feasibility_breakdown": {
            "demand": round(demand_score, 2),
            "profit_hour": round(profit_score, 2),
            "trend": round(trend_score, 2),
            "issue_health": round(issue_health, 2),
        },
        "max_units_from_stock": max_units,
        "shortage_materials": shortage_materials,
    }


def get_product_cost_cached(product) -> Dict[str, float]:
    """Cached version of compute_product_cost."""
    if product.id not in _product_cost_cache:
        _product_cost_cache[product.id] = compute_product_cost(product)
    return _product_cost_cache[product.id]


def clear_product_cost_cache(product_id: Optional[int] = None):
    """Clear product cost cache."""
    global _product_cost_cache
    if product_id is not None:
        _product_cost_cache.pop(product_id, None)
    else:
        _product_cost_cache.clear()
