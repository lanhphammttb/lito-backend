"""
Legacy analytics router — stub only.
All routes have been migrated to domain-specific routers:
  ideas.py, goals_router.py, experiments_router.py, issues_router.py,
  strategy_router.py, growth_analytics_router.py
"""
from fastapi import APIRouter

router = APIRouter()

def set_data_stores(*args, **kwargs):
    pass
