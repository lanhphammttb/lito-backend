"""Shared per-product BOM calculation for costing, planning and stock checks."""
import math


def effective_quantity(quantity, product_wastage=0, usage_wastage=0, unit_type="continuous"):
    amount = float(quantity) * (1 + max(0, (product_wastage or 0) + (usage_wastage or 0)) / 100)
    return math.ceil(amount) if unit_type == "piece" else amount
