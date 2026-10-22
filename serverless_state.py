"""Keep legacy list-backed endpoints consistent across serverless instances.

Requests are serialized until legacy stores are replaced with SQL queries.
The transaction-scoped lock also works with Neon's transaction pooler.
"""
import asyncio

from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from config.database import engine


class ServerlessStateMiddleware:
    def __init__(self, app):
        self.app = app
        self.lock = asyncio.Lock()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] == "OPTIONS" or scope["path"] in {"/health", "/system/health"}:
            return await self.app(scope, receive, send)

        from app_bootstrap import load_data_from_sql, load_expenses, load_settings_from_db, init_services
        from services.product import _product_cost_cache

        def acquire_and_refresh():
            connection = engine.connect()
            try:
                connection.execute(text("SET LOCAL lock_timeout = '20s'"))
                connection.execute(text("SELECT pg_advisory_xact_lock(724019831)"))
                load_data_from_sql()
                load_expenses()
                load_settings_from_db()
                init_services()
                _product_cost_cache.clear()
                return connection
            except BaseException:
                connection.close()
                raise

        async with self.lock:
            connection = await run_in_threadpool(acquire_and_refresh)
            try:
                await self.app(scope, receive, send)
            finally:
                await run_in_threadpool(connection.close)
