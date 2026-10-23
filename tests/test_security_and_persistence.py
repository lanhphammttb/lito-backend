import os
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


class SecurityAndPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(cls.temp_dir.name) / "test_hala.db"
        backend_root = Path(__file__).resolve().parents[1]
        if str(backend_root) not in sys.path:
            sys.path.insert(0, str(backend_root))

        os.environ["JWT_SECRET"] = "test-secret-1234567890"
        test_url = os.getenv("LITO_TEST_DATABASE_URL")
        if test_url:
            from sqlalchemy import create_engine, text
            schema_name = os.getenv("LITO_TEST_SCHEMA", "")
            if not schema_name.startswith("lito_qa_"):
                raise RuntimeError("PostgreSQL tests require an isolated lito_qa_ schema")
            check_engine = create_engine(test_url)
            with check_engine.connect() as connection:
                namespaces = connection.execute(text("SELECT current_schemas(false)")).scalar_one()
                if namespaces != [schema_name]:
                    raise RuntimeError("Refusing tests outside the isolated QA schema")
            check_engine.dispose()
        os.environ["DATABASE_URL"] = test_url or f"sqlite:///{db_path}"
        os.environ["AUTO_INIT_DB_ON_STARTUP"] = "true"
        os.environ["AUTO_SEED_DATA_ON_STARTUP"] = "false"
        os.environ["USE_MONGO"] = "false"
        os.environ["BOOTSTRAP_ADMIN_EMAIL"] = "admin@example.com"
        os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "strong-password"
        os.environ["ADMIN_DEFAULT_PASSWORD"] = ""
        os.environ["OWNER_A_PASSWORD"] = ""
        os.environ["OWNER_B_PASSWORD"] = ""
        os.environ["CORS_ORIGINS"] = "http://localhost:5173"

        import main as backend_main

        cls.backend_main = backend_main
        cls.client_cm = TestClient(cls.backend_main.app)
        cls.client = cls.client_cm.__enter__()

        login_response = cls.client.post(
            "/auth/login",
            json={"email": "admin@example.com", "password": "strong-password"},
        )
        assert login_response.status_code == 200, login_response.text
        cls.auth_headers = {
            "Authorization": f"Bearer {login_response.json()['access_token']}"
        }
        cls.user_id = cls.client.get('/auth/me', headers=cls.auth_headers).json()['id']

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)
        from config.database import close_mongo_connection, engine
        close_mongo_connection()
        engine.dispose()
        cls.temp_dir.cleanup()

    def test_internal_report_routes_require_auth(self):
        for path in ['/goals', '/issues', '/content-plans', '/content-plans/analytics',
                     '/business-health', '/growth/aarrr-metrics', '/customers/lifecycle-analysis',
                     '/customers/cohort-analysis', '/analytics/signals', '/analytics/funnel', '/content/marketing-frameworks']:
            self.assertEqual(self.client.get(path).status_code, 401, path)

    def test_goals_calculate_real_orders_and_get_does_not_write(self):
        from sqlmodel import Session
        from config.database import engine
        from models.goal import GoalTable
        mat = self.make_material('goal-cost', 100)
        self.catalog_request('put', f"/materials/{mat['id']}", {**mat, 'unit_price': 2})
        product = self.catalog_request('post', '/products', {'name': 'Goal cost', 'materials': [{'material_id': mat['id'], 'quantity': 10}]})
        self.catalog_request('post', '/orders', {'date': '2091-01-02', 'status': 'confirmed', 'discount': 10, 'shipping_fee': 20,
            'order_lines': [{'product_id': product['id'], 'quantity': 2, 'unit_price': 100}]})
        self.catalog_request('post', '/orders', {'date': '2091-01-03', 'status': 'cancelled',
            'order_lines': [{'product_id': product['id'], 'quantity': 10, 'unit_price': 100}]})
        goal = self.catalog_request('post', '/goals', {'title': 'Revenue goal', 'target_type': 'revenue', 'target_value': 100,
            'start_date': '2091-01-01', 'end_date': '2091-01-31'})
        self.assertEqual(goal['current_value'], 190)
        self.assertEqual(goal['status'], 'achieved')
        goals = self.catalog_request('get', '/goals')
        self.assertEqual(next(row for row in goals if row['id'] == goal['id'])['current_value'], 190)
        with Session(engine) as session:
            stored = session.get(GoalTable, goal['id'])
            self.assertEqual(stored.status, 'active')
            self.assertIsNone(stored.achieved_at)
        self.catalog_request('post', '/goals', {'title': 'Invalid period', 'start_date': '2091-02-01', 'end_date': '2091-01-01'}, status=422)

    def test_backup_can_restore_into_empty_database_and_rejects_overwrite(self):
        from sqlalchemy import create_engine, MetaData, select, func, text
        from sqlmodel import SQLModel
        from config.database import engine
        from services.backup import restore_snapshot
        response = self.client.post('/backup', headers=self.auth_headers)
        self.assertEqual(response.status_code, 200, response.text[:200])
        payload = response.json()
        self.assertEqual(payload['format'], 'lito-database-backup')
        self.assertIn('users', payload['tables'])
        self.assertIn('materials', payload['tables'])
        restore_schema = None
        if engine.dialect.name == 'postgresql':
            import uuid
            restore_schema = 'lito_qa_' + uuid.uuid4().hex
            with engine.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{restore_schema}"'))
            target = create_engine(engine.url.update_query_dict({'options': '-csearch_path=' + restore_schema}))
        else:
            target = create_engine(f"sqlite:///{Path(self.temp_dir.name) / 'restore-check.db'}")
        try:
            SQLModel.metadata.create_all(target)
            counts = restore_snapshot(target, payload)
            metadata = MetaData()
            metadata.reflect(bind=target)
            with target.connect() as conn:
                for name, expected in counts.items():
                    self.assertEqual(conn.execute(select(func.count()).select_from(metadata.tables[name])).scalar_one(), expected, name)
            with self.assertRaisesRegex(ValueError, 'trống'):
                restore_snapshot(target, payload)
            broken = {**payload, 'sha256': 'corrupt'}
            with self.assertRaisesRegex(ValueError, 'toàn vẹn'):
                restore_snapshot(target, broken)
            if restore_schema:
                users = metadata.tables['users']
                with target.begin() as conn:
                    next_user = conn.execute(users.insert().values(name='Restored sequence check', email='sequence@example.com',
                        password_hash='not-a-real-credential', role='USER', is_owner=False,
                        created_at=__import__('datetime').datetime.now())).inserted_primary_key[0]
                self.assertGreater(next_user, max(row['id'] for row in payload['tables']['users']))
        finally:
            target.dispose()
            if restore_schema:
                with engine.begin() as connection:
                    connection.execute(text(f'DROP SCHEMA "{restore_schema}" CASCADE'))
        self.assertEqual(self.client.post('/backup').status_code, 401)
        viewer = self.client.post('/auth/register', json={'email': 'backup-viewer@example.com', 'password': 'viewer-password'}).json()
        self.assertEqual(self.client.post('/backup', headers={'Authorization': 'Bearer ' + viewer['access_token']}).status_code, 403)

    def test_order_jobs_cannot_duplicate_existing_plan(self):
        product = self.catalog_request('post', '/products', {'name': 'Duplicate planning guard'})
        order = self.catalog_request('post', '/orders', {'date': '2026-10-23', 'status': 'confirmed',
            'order_lines': [{'product_id': product['id'], 'quantity': 2, 'unit_price': 100}]})
        job = self.catalog_request('post', '/production-jobs', {'order_id': order['id'], 'product_id': product['id'], 'quantity': 2})
        self.catalog_request('post', '/production-jobs', {'order_id': order['id'], 'product_id': product['id'], 'quantity': 1}, status=409)
        self.catalog_request('put', f"/production-jobs/{job['id']}", {'quantity': 3}, status=409)
        requirements = self.catalog_request('get', f"/orders/{order['id']}/production-requirements")
        self.assertEqual(requirements[0]['remaining_quantity'], 0)
        self.catalog_request('patch', f"/production-jobs/{job['id']}/status", {'status': 'cancelled'})
        requirements = self.catalog_request('get', f"/orders/{order['id']}/production-requirements")
        self.assertEqual(requirements[0]['remaining_quantity'], 2)

    def test_shipping_rejects_shortage_and_commits_stock_with_order(self):
        first = self.catalog_request('post', '/products', {'name': 'Shipment available'})
        second = self.catalog_request('post', '/products', {'name': 'Shipment missing'})
        self.catalog_request('post', f"/products/{first['id']}/adjust-finished", {'quantity_change': 5})
        order = self.catalog_request('post', '/orders', {'date': '2026-10-23', 'order_lines': [
            {'product_id': first['id'], 'quantity': 2, 'unit_price': 100},
            {'product_id': second['id'], 'quantity': 1, 'unit_price': 100}]})
        self.catalog_request('patch', f"/orders/{order['id']}", {'status': 'shipped'}, status=409)
        self.assertEqual(self.catalog_request('get', f"/products/{first['id']}")['finished_qty'], 5)
        self.assertEqual(self.catalog_request('get', f"/orders/{order['id']}")['status'], 'pending')
        self.catalog_request('post', f"/products/{second['id']}/adjust-finished", {'quantity_change': 1})
        self.catalog_request('patch', f"/orders/{order['id']}", {'status': 'shipped'})
        self.catalog_request('patch', f"/orders/{order['id']}", {'status': 'delivered'})
        self.catalog_request('patch', f"/orders/{order['id']}", {'status': 'delivered'})
        self.assertEqual(self.catalog_request('get', f"/products/{first['id']}")['finished_qty'], 3)
        self.catalog_request('patch', f"/orders/{order['id']}", {'status': 'confirmed'}, status=409)
        self.catalog_request('patch', f"/orders/{order['id']}", {'status': 'unknown'}, status=400)
        self.catalog_request('patch', f"/orders/{order['id']}", {'shipping_fee': -1}, status=422)
        self.catalog_request('post', f"/products/{first['id']}/adjust-finished", {'quantity_change': -4}, status=409)
        self.catalog_request('post', f"/products/{first['id']}/adjust-finished", {'quantity_change': 1.5}, status=422)

    def test_tracking_fields_and_status_survive_reload(self):
        product = self.catalog_request('post', '/products', {'name': 'Tracking persistence'})
        self.catalog_request('post', f"/products/{product['id']}/adjust-finished", {'quantity_change': 2})
        order = self.catalog_request('post', '/orders', {'date': '2026-10-23',
            'order_lines': [{'product_id': product['id'], 'quantity': 1, 'unit_price': 100}]})
        self.catalog_request('post', f"/orders/{order['id']}/tracking", {'status': 'shipped',
            'tracking_number': 'QA-TRACKING', 'shipping_carrier': 'QA', 'estimated_delivery_date': '2026-10-25'})
        loaded = self.catalog_request('get', f"/orders/{order['id']}")
        self.assertEqual(loaded['status'], 'shipped')
        self.assertEqual(loaded['tracking_number'], 'QA-TRACKING')
        self.assertEqual(loaded['shipping_carrier'], 'QA')
        self.assertEqual(loaded['estimated_delivery_date'], '2026-10-25')
        self.assertEqual(self.catalog_request('get', f"/products/{product['id']}")['finished_qty'], 1)

    def test_saved_estimated_order_cost_does_not_drift_with_material_price(self):
        material = self.make_material('stable-order-cost', 100)
        product = self.catalog_request('post', '/products', {'name': 'Stable cost', 'materials': [
            {'material_id': material['id'], 'quantity': 10}]})
        order = self.catalog_request('post', '/orders', {'date': '2026-10-23',
            'order_lines': [{'product_id': product['id'], 'quantity': 2, 'unit_price': 100}]})
        initial = order['computed']['cost']
        self.catalog_request('put', f"/materials/{material['id']}", {**material, 'unit_price': material['unit_price'] * 2})
        loaded = self.catalog_request('get', f"/orders/{order['id']}")
        self.assertEqual(loaded['computed']['cost'], initial)
        self.assertEqual(loaded['computed']['cost_basis'], 'saved_estimate')
        self.assertTrue(loaded['computed']['cost_is_estimated'])
        listed = next(row for row in self.catalog_request('get', '/orders') if row['id'] == order['id'])
        self.assertEqual(listed['computed']['cost'], initial)

    def test_reports_use_persisted_content_orders_and_real_expenses(self):
        from datetime import date
        before = self.catalog_request('get', '/business-health')
        product = self.catalog_request('post', '/products', {'name': 'Report source', 'time_minutes': 0,
            'cost_breakdown': {'other': 3}})
        order = self.catalog_request('post', '/orders', {'date': date.today().isoformat(),
            'order_lines': [{'product_id': product['id'], 'quantity': 2, 'unit_price': 50}]})
        self.assertEqual(order['computed']['cost'], 6)
        self.catalog_request('post', '/expenses', {'date': date.today().isoformat(), 'category': 'other', 'amount': 7})
        after = self.catalog_request('get', '/business-health')
        self.assertEqual(after['summary']['total_orders'], before['summary']['total_orders'] + 1)
        self.assertEqual(after['financial_metrics']['total_revenue'], before['financial_metrics']['total_revenue'] + 100)
        self.assertEqual(after['financial_metrics']['monthly_burn'], before['financial_metrics']['monthly_burn'] + 7)
        plan = self.catalog_request('post', '/content-plans', {'title': 'Published report source', 'status': 'published'})
        self.catalog_request('post', f"/content-plans/{plan['id']}/performance", {'actual_views': 10, 'actual_revenue': 50})
        metrics = self.catalog_request('get', '/content-plans/analytics')
        self.assertGreaterEqual(metrics['summary']['total_revenue'], 50)
        self.assertIsNone(metrics['summary']['avg_roi'])

    def test_order_summary_reads_current_reference_data_without_startup_cache(self):
        from routers import orders as orders_router
        customer = self.catalog_request('post', '/customers', {'name': 'Current reference customer'})
        product = self.catalog_request('post', '/products', {'name': 'Current reference product'})
        content = self.catalog_request('post', '/content-plans', {'title': 'Current reference post'})
        self.catalog_request('post', '/orders', {'date': '2026-10-23', 'customer_id': customer['id'],
            'maker_user_id': self.user_id,
            'order_lines': [{'product_id': product['id'], 'quantity': 1, 'unit_price': 100}]})
        with patch.object(orders_router, '_products', []), patch.object(orders_router, '_customers', []), \
             patch.object(orders_router, '_users', []), patch.object(orders_router, '_content_plans', []):
            response = self.catalog_request('get', '/orders/summary')
        self.assertIn(product['id'], [row['id'] for row in response['products']])
        self.assertIn(customer['id'], [row['id'] for row in response['customers']])
        self.assertIn(content['id'], [row['id'] for row in response['contents']])
        self.assertIn(self.user_id, [row['id'] for row in response['users']])
        self.assertTrue(all('password_hash' not in row for row in response['users']))

    def test_cashflow_reads_paid_transactions_from_sql_and_filters_dates(self):
        from datetime import date
        from routers import cashflow_router
        product = self.catalog_request('post', '/products', {'name': 'Cashflow product'})
        order = self.catalog_request('post', '/orders', {'date': date.today().isoformat(),
            'order_lines': [{'product_id': product['id'], 'quantity': 1, 'unit_price': 100}]})
        pending = self.catalog_request('post', f"/orders/{order['id']}/payments", {'order_id': order['id'], 'amount': 30})
        paid = self.catalog_request('post', f"/orders/{order['id']}/payments", {'order_id': order['id'], 'amount': 50, 'status': 'paid'})
        with patch.object(cashflow_router, '_payments', []), patch.object(cashflow_router, '_expenses', []):
            response = self.catalog_request('get', f'/cashflow/transactions?start_date={date.today().isoformat()}&end_date={date.today().isoformat()}')
        self.assertIn(f"pay_{paid['id']}", [row['id'] for row in response])
        self.assertNotIn(f"pay_{pending['id']}", [row['id'] for row in response])
        from datetime import datetime
        self.assertEqual(cashflow_router._parse_date(datetime(2026, 10, 22, 18)), date(2026, 10, 23))

    def test_growth_compares_equal_periods_and_uses_percentage_change(self):
        from datetime import date, timedelta
        from routers import growth_analytics_router as analytics
        product = self.catalog_request('post', '/products', {'name': 'Growth periods', 'time_minutes': 0})
        order_ids = []
        for age, price in [(100, 9000), (40, 100), (10, 150)]:
            order = self.catalog_request('post', '/orders', {'date': (date.today() - timedelta(days=age)).isoformat(),
                'order_lines': [{'product_id': product['id'], 'quantity': 1, 'unit_price': price}]})
            order_ids.append(order['id'])
        from services.order import find_order
        with patch.object(analytics, '_persisted_orders', return_value=[find_order(oid) for oid in order_ids]):
            response = self.catalog_request('get', '/growth/aarrr-metrics')
        self.assertEqual(response['summary']['revenue_growth'], 50)
        with patch.object(analytics, '_persisted_orders', return_value=[find_order(order_ids[-1])]):
            response = self.catalog_request('get', '/growth/aarrr-metrics')
        self.assertIsNone(response['summary']['revenue_growth'])

    def test_cohorts_use_calendar_months(self):
        from sqlmodel import Session
        from config.database import engine
        from models.customer import CustomerTable
        from datetime import datetime
        customer = self.catalog_request('post', '/customers', {'name': 'Calendar cohort'})
        with Session(engine) as session:
            row = session.get(CustomerTable, customer['id'])
            row.created_at = datetime(2001, 1, 1)
            session.add(row)
            session.commit()
        product = self.catalog_request('post', '/products', {'name': 'Calendar period', 'time_minutes': 0})
        for month in (2, 3):
            self.catalog_request('post', '/orders', {'date': f'2001-{month:02d}-01', 'customer_id': customer['id'],
                'order_lines': [{'product_id': product['id'], 'quantity': 1, 'unit_price': 100}]})
        response = self.catalog_request('get', '/customers/cohort-analysis')
        cohort = next(row for row in response['cohorts'] if row['cohort'] == '2001-01')
        self.assertEqual(cohort['revenue']['month_1'], 100)
        self.assertEqual(cohort['revenue']['month_2'], 100)

    def test_invalid_profit_margin_is_rejected_before_settings_save(self):
        for value in (-0.1, 1, 2):
            self.catalog_request('patch', '/settings', {'default_profit_margin': value}, status=422)

    def test_variant_shipment_uses_matching_variant_stock(self):
        product = self.catalog_request('post', '/products', {'name': 'Variant stock'})
        pink = self.catalog_request('post', '/products/variants', {'product_id': product['id'], 'name': 'Pink', 'stock_quantity': 2})
        blue = self.catalog_request('post', '/products/variants', {'product_id': product['id'], 'name': 'Blue', 'stock_quantity': 3})
        order = self.catalog_request('post', '/orders', {'date': '2026-10-23',
            'order_lines': [{'product_id': product['id'], 'variant_id': pink['id'], 'quantity': 1, 'unit_price': 100}]})
        self.catalog_request('patch', f"/orders/{order['id']}", {'status': 'shipped'})
        variants = self.catalog_request('get', '/products/variants')
        self.assertEqual(next(row for row in variants if row['id'] == pink['id'])['stock_quantity'], 1)
        self.assertEqual(next(row for row in variants if row['id'] == blue['id'])['stock_quantity'], 3)

    def test_legacy_content_routes_persist_and_keep_authenticated_author(self):
        from sqlmodel import Session
        from config.database import engine
        from models.content import ContentPlanTable
        plan = self.catalog_request('post', '/content-plans', {'title': 'Persisted legacy content', 'platform': 'facebook'})
        with Session(engine) as session:
            self.assertEqual(session.get(ContentPlanTable, plan['id']).created_by, self.user_id)
        self.catalog_request('put', f"/content-plans/{plan['id']}", {'title': 'Updated legacy content', 'caption': 'Keep this caption'})
        self.catalog_request('post', f"/content-plans/{plan['id']}/performance", {'actual_views': 20, 'actual_revenue': 100})
        loaded = next(row for row in self.catalog_request('get', '/content-plans') if row['id'] == plan['id'])
        self.assertEqual(loaded['caption'], 'Keep this caption')
        self.assertEqual(loaded['actual_views'], 20)

    def test_internal_products_requires_auth(self):
        response = self.client.get("/products")
        self.assertEqual(response.status_code, 401)

    def test_all_local_read_routes_return_without_server_error(self):
        for path, methods in self.backend_main.app.openapi()['paths'].items():
            if 'get' not in methods or '{' in path or path.startswith(('/ga4', '/auth/facebook', '/facebook', '/instagram')):
                continue
            with self.subTest(path=path):
                response = self.client.get(path, headers=self.auth_headers, follow_redirects=False)
                self.assertEqual(response.status_code, 200, response.text[:180])

    def test_frontend_system_routes_and_database_health(self):
        for path in ("/alerts", "/users", "/issue-templates"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)
                response = self.client.get(path, headers=self.auth_headers)
                self.assertEqual(response.status_code, 200, response.text)
        for path in ("/health", "/system/health"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            from config.database import engine
            self.assertEqual(response.json()["database"], engine.dialect.name)

    def test_settings_requires_auth(self):
        response = self.client.get("/settings")
        self.assertEqual(response.status_code, 401)

    def test_settings_hides_secret_fields_for_non_admin(self):
        register_response = self.client.post(
            "/auth/register",
            json={"email": "viewer@example.com", "password": "viewer-password"},
        )
        self.assertEqual(register_response.status_code, 200)
        headers = {
            "Authorization": f"Bearer {register_response.json()['access_token']}"
        }

        response = self.client.get("/settings", headers=headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn("smtp_password", payload)
        self.assertNotIn("shopee_partner_key", payload)
        self.assertNotIn("lazada_app_secret", payload)

    @contextmanager
    def saved_social_settings(self):
        from config.database import engine
        from config.settings import settings
        from models.settings_table import SettingsTable
        from routers.settings import _SOCIAL_FIELDS
        from sqlmodel import Session
        from app_bootstrap import load_settings_from_db
        previous_memory = {key: getattr(settings, key) for key in _SOCIAL_FIELDS}
        with Session(engine) as session:
            row = session.get(SettingsTable, 1)
            previous_row = {key: getattr(row, key) for key in _SOCIAL_FIELDS} if row else None
            row = row or SettingsTable(id=1)
            for key in _SOCIAL_FIELDS:
                setattr(row, key, f"test-{key}")
            session.add(row)
            session.commit()
        load_settings_from_db()
        try:
            yield
        finally:
            with Session(engine) as session:
                row = session.get(SettingsTable, 1)
                if previous_row is None:
                    session.delete(row)
                else:
                    for key, value in previous_row.items():
                        setattr(row, key, value)
                    session.add(row)
                session.commit()
            for key, value in previous_memory.items():
                setattr(settings, key, value)

    def test_general_settings_save_preserves_social_connection_after_reload(self):
        from app_bootstrap import load_settings_from_db
        from routers.settings import _SOCIAL_FIELDS
        with self.saved_social_settings():
            for blank in (None, "", "   "):
                response = self.client.patch("/settings", headers=self.auth_headers,
                    json={key: blank for key in _SOCIAL_FIELDS})
                self.assertEqual(response.status_code, 200, response.text)
                load_settings_from_db()
                saved = self.client.get("/settings", headers=self.auth_headers).json()
                self.assertTrue(saved["facebook_connected"])
                for key in _SOCIAL_FIELDS:
                    self.assertEqual(saved[key], f"test-{key}")
            response = self.client.put("/settings/facebook_page_access_token",
                headers=self.auth_headers, json={"value": " "})
            self.assertEqual(response.status_code, 400)

    def test_disconnect_clears_stale_worker_connection_after_reload(self):
        from app_bootstrap import load_settings_from_db
        from config.settings import settings
        with self.saved_social_settings():
            response = self.client.delete("/auth/facebook", headers=self.auth_headers)
            self.assertEqual(response.status_code, 200, response.text)
            # Simulate another warm worker still holding the previous token.
            settings.facebook_page_access_token = "stale-token"
            settings.facebook_page_id = "stale-page"
            settings.instagram_business_account_id = "stale-instagram"
            load_settings_from_db()
            self.assertIsNone(settings.facebook_page_access_token)
            self.assertIsNone(settings.facebook_page_id)
            self.assertIsNone(settings.instagram_business_account_id)
            self.assertFalse(settings.public_dump()["facebook_connected"])
            self.assertTrue(settings.public_dump()["facebook_oauth_configured"])

    def test_social_connection_status_does_not_expose_credentials(self):
        from config.settings import settings
        with self.saved_social_settings():
            payload = settings.public_dump()
            self.assertTrue(payload["facebook_connected"])
            self.assertTrue(payload["facebook_oauth_configured"])
            self.assertTrue(payload["instagram_connected"])
            self.assertNotIn("facebook_page_access_token", payload)
            self.assertNotIn("facebook_app_secret", payload)

    def test_facebook_callback_persists_connection_and_returns_to_hash_route(self):
        from urllib.parse import urlsplit, parse_qs
        from app_bootstrap import load_settings_from_db
        from config.settings import settings
        from unittest.mock import Mock
        with self.saved_social_settings():
            launch = self.catalog_request('post', '/auth/facebook/start', {})
            ticket = parse_qs(urlsplit(launch['url']).query)['ticket'][0]
            page_name = "LITO & Len / Màu #1"
            responses = [
                {"access_token": "short-user-token"},
                {"access_token": "long-user-token"},
                {"data": [{"id": "new-page", "name": page_name, "access_token": "saved-page-token"}]},
                {},
            ]
            graph = AsyncMock()
            graph.get.side_effect = [Mock(json=Mock(return_value=data)) for data in responses]
            with patch("routers.auth.httpx.AsyncClient") as client:
                client.return_value.__aenter__.return_value = graph
                response = self.client.get('/auth/facebook/callback', params={'code': 'test-code', 'state': ticket},
                    headers={'Cookie': 'facebook_oauth_state=' + ticket}, follow_redirects=False)
            self.assertEqual(response.status_code, 307)
            fragment = urlsplit(response.headers["location"]).fragment
            path, query = fragment.split("?", 1)
            self.assertEqual(path, "/settings")
            self.assertEqual(parse_qs(query)["page_name"], [page_name])
            load_settings_from_db()
            self.assertEqual(settings.facebook_page_id, "new-page")
            self.assertEqual(settings.facebook_page_access_token, "saved-page-token")
            self.assertIsNone(settings.instagram_business_account_id)

    def test_facebook_oauth_requires_admin_and_browser_bound_state(self):
        from urllib.parse import urlsplit, parse_qs
        self.assertEqual(self.client.post('/auth/facebook/start').status_code, 401)
        self.assertEqual(self.client.get('/auth/facebook', follow_redirects=False).status_code, 403)
        with self.saved_social_settings():
            launch = self.catalog_request('post', '/auth/facebook/start', {})
            ticket = parse_qs(urlsplit(launch['url']).query)['ticket'][0]
            start = self.client.get('/auth/facebook', params={'ticket': ticket}, follow_redirects=False)
            self.assertEqual(start.status_code, 307)
            self.assertEqual(parse_qs(urlsplit(start.headers['location']).query)['state'], [ticket])
            cookie = start.headers['set-cookie'].lower()
            self.assertIn('httponly', cookie)
            self.assertIn('samesite=lax', cookie)
            with patch('routers.auth.httpx.AsyncClient') as graph:
                for params, headers in [({'code': 'unused'}, {}),
                                        ({'code': 'unused', 'state': 'wrong'}, {'Cookie': 'facebook_oauth_state=' + ticket})]:
                    response = self.client.get('/auth/facebook/callback', params=params, headers=headers, follow_redirects=False)
                    self.assertIn('facebook_error=', response.headers['location'])
                graph.assert_not_called()
            # The OAuth ticket is scoped to consent and cannot authenticate API requests.
            self.assertEqual(self.client.get('/auth/me', headers={'Authorization': 'Bearer ' + ticket}).status_code, 401)
            registered = self.client.post('/auth/register', json={'email': 'oauth-viewer@example.com', 'password': 'viewer-password'})
            self.assertEqual(registered.status_code, 200)
            user_headers = {'Authorization': 'Bearer ' + registered.json()['access_token']}
            self.assertEqual(self.client.post('/auth/facebook/start', headers=user_headers).status_code, 403)

    def test_ai_route_requires_auth(self):
        response = self.client.post("/ai/analyze", json={"prompt": "hello"})
        self.assertEqual(response.status_code, 401)

    @contextmanager
    def notification_devices(self):
        from config.database import engine
        from models.notifications import FcmTokenTable
        from sqlmodel import Session, select
        tokens = ["qa-push-current-a", "qa-push-current-b", "qa-push-other"]
        with Session(engine) as session:
            for token, uid in zip(tokens, [self.user_id, self.user_id, 999999]):
                session.add(FcmTokenTable(token=token, user_id=uid))
            session.commit()
        try:
            yield tokens
        finally:
            with Session(engine) as session:
                for row in session.exec(select(FcmTokenTable).where(FcmTokenTable.token.in_(tokens))):
                    session.delete(row)
                session.commit()

    def test_notification_without_receivers_does_not_report_success(self):
        for path in ["/notifications/status", "/notifications"]:
            self.assertEqual(self.client.get(path).status_code, 401)
        for path in ["/notifications/send", "/notifications/test"]:
            self.assertEqual(self.client.post(path, json={}).status_code, 401)
        response = self.client.post("/notifications/send", headers=self.auth_headers,
            json={"title": "No receivers", "body": "Not delivered", "user_ids": [999998]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["success"])
        self.assertEqual(response.json()["status"], "no_recipients")
        self.assertEqual(response.json()["sent_count"], 0)

    def test_notification_counts_actual_acceptances_and_prunes_only_expired_tokens(self):
        from config.database import engine
        from models.notifications import FcmTokenTable
        from legacy_state import NotificationLog
        from sqlmodel import Session, select
        with self.notification_devices() as tokens:
            result = {"attempted": 2, "accepted": 1, "failed": 1,
                      "invalid_tokens": [tokens[0]], "error_codes": ["UnregisteredError"]}
            with patch("services.fcm.send_many_result", return_value=result) as transport:
                response = self.client.post("/notifications/send", headers=self.auth_headers,
                    json={"title": "Partial delivery", "body": "Only selected account", "data": None,
                          "user_ids": [self.user_id, self.user_id]})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(set(transport.call_args.args[0]), set(tokens[:2]))
            self.assertEqual(transport.call_args.args[3], {})
            self.assertEqual(response.json()["sent_count"], 1)
            self.assertEqual(response.json()["status"], "partial")
            self.assertNotIn(tokens[0], response.text)
            with Session(engine) as session:
                remaining = session.exec(select(FcmTokenTable)).all()
                self.assertNotIn(tokens[0], [row.token for row in remaining])
                self.assertIn(tokens[1], [row.token for row in remaining])
                self.assertIn(tokens[2], [row.token for row in remaining])
                log = session.exec(select(NotificationLog).where(NotificationLog.title == "Partial delivery")).one()
                self.assertEqual(log.sent_count, 1)

    def test_notification_missing_credentials_does_not_report_success(self):
        with self.notification_devices(), patch("services.fcm._init", return_value=False), \
             patch("services.fcm._last_error", "credentials_missing"):
            response = self.client.post("/notifications/send", headers=self.auth_headers,
                json={"title": "Disabled push", "body": "No backend credentials", "user_ids": [self.user_id]})
            self.assertFalse(response.json()["success"])
            self.assertEqual(response.json()["sent_count"], 0)
            self.assertEqual(response.json()["failed_devices"], 2)
            self.assertEqual(response.json()["error_codes"], ["credentials_missing"])

    def test_notification_test_only_targets_current_account(self):
        with self.notification_devices() as tokens:
            result = {"attempted": 2, "accepted": 2, "failed": 0, "invalid_tokens": [], "error_codes": []}
            with patch("services.fcm.send_many_result", return_value=result) as transport, \
                 patch("routers.notifications.ws_manager.broadcast", new_callable=AsyncMock) as broadcast, \
                 patch("routers.notifications.ws_manager.send_personal_message", new_callable=AsyncMock, return_value=0):
                response = self.client.post("/notifications/test", headers=self.auth_headers)
                broadcast.assert_not_awaited()
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["success"])
            self.assertEqual(set(transport.call_args.args[0]), set(tokens[:2]))

    def test_notification_rejects_invalid_content_and_recipients(self):
        for changes in [{"title": " "}, {"body": ""}, {"user_ids": []},
                        {"user_ids": [True]}, {"user_ids": ["1"]}, {"data": []}]:
            response = self.client.post("/notifications/send", headers=self.auth_headers,
                json={"title": "Content validation", "body": "Body", **changes})
            self.assertEqual(response.status_code, 422, response.text)

    def test_email_test_uses_email_and_reports_failure(self):
        from config.settings import settings
        with patch.object(settings, "smtp_host", "smtp.qa.example"), \
             patch.object(settings, "notification_emails", ["qa@example.com"]), \
             patch("routers.notifications.send_notifications", return_value=False) as email, \
             patch("services.fcm.send_many_result") as push:
            response = self.client.post("/notifications/test-email", headers=self.auth_headers)
            self.assertEqual(response.status_code, 503)
            push.assert_not_called()
            email.assert_called_once()
            email.return_value = True
            self.assertEqual(self.client.post("/notifications/test-email", headers=self.auth_headers).status_code, 200)

    def test_fcm_loads_json_credentials_without_file(self):
        from services import fcm
        import json
        fake_info = {"type": "service_account", "project_id": "qa-project"}
        with patch.object(fcm, "_app", None), patch.object(fcm, "_last_error", None), \
             patch.object(fcm, "_firebase_available", True), \
             patch.dict(os.environ, {"FIREBASE_CREDENTIALS_JSON": json.dumps(fake_info)}), \
             patch.object(fcm.credentials, "Certificate") as certificate, \
             patch.object(fcm.firebase_admin, "initialize_app", return_value=object()):
            self.assertTrue(fcm.delivery_status()["push_configured"])
            certificate.assert_called_once_with(fake_info)
        with patch.object(fcm, "_app", None), patch.object(fcm, "_last_error", None), \
             patch.dict(os.environ, {"FIREBASE_CREDENTIALS_JSON": "PRIVATE_VALUE_DO_NOT_LEAK"}):
            status = fcm.delivery_status()
            self.assertFalse(status["push_configured"])
            self.assertEqual(status["configuration_error"], "credentials_invalid")
            self.assertNotIn("PRIVATE_VALUE_DO_NOT_LEAK", str(status))

    def test_fcm_reports_per_device_failures_without_leaking_tokens(self):
        from services import fcm
        from unittest.mock import Mock
        response = Mock(success_count=1, failure_count=1, responses=[
            Mock(success=True), Mock(success=False, exception=fcm.messaging.UnregisteredError("expired")),
        ])
        with patch.object(fcm, "_init", return_value=True), \
             patch.object(fcm.messaging, "send_each_for_multicast", return_value=response) as send:
            result = fcm.send_many_result(["valid-device", "expired-device"], "Title", "Body")
            self.assertEqual(result["accepted"], 1)
            self.assertEqual(result["failed"], 1)
            self.assertEqual(result["invalid_tokens"], ["expired-device"])
            self.assertEqual(result["error_codes"], ["UnregisteredError"])
            self.assertTrue(send.call_args.args[0].webpush.fcm_options.link.endswith('/#/notifications'))

    def test_business_planning_routes_require_auth(self):
        for method, path in (
            ("get", "/ideas"),
            ("post", "/ideas"),
            ("get", "/experiments"),
            ("post", "/experiments"),
            ("get", "/strategy/okrs"),
            ("post", "/strategy/okrs"),
            ("get", "/ga4/dashboard"),
            ("get", "/ga4/realtime"),
            ("get", "/ga4/correlation"),
            ("get", "/ga4/ai-context"),
        ):
            request = getattr(self.client, method)
            response = request(path, json={}) if method == "post" else request(path)
            self.assertEqual(response.status_code, 401, path)

    def test_strategy_okr_persists(self):
        response = self.client.post(
            "/strategy/okrs",
            headers=self.auth_headers,
            json={
                "title": "Grow repeat customers",
                "quarter": "2026-Q2",
                "key_results": [
                    {"title": "Repeat orders", "target": 10, "current": 4, "unit": "orders"}
                ],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        okr_id = response.json()["id"]

        list_response = self.client.get("/strategy/okrs", headers=self.auth_headers)
        self.assertEqual(list_response.status_code, 200, list_response.text)
        payload = list_response.json()
        okr = next((item for item in payload["okrs"] if item["id"] == okr_id), None)
        self.assertIsNotNone(okr)
        self.assertEqual(okr["status"], "active")
        self.assertEqual(okr["overall_progress"], 40.0)

    def test_strategy_swot_and_insight_persist_after_creation(self):
        swot = self.client.post(
            "/strategy/swot", headers=self.auth_headers,
            json={"type": "opportunity", "category": "market", "description": "New yarn colors",
                  "impact": "medium", "action_items": ["Compare suppliers"]},
        )
        self.assertEqual(swot.status_code, 200, swot.text)
        matrix = self.client.get("/strategy/swot", headers=self.auth_headers).json()["matrix"]
        saved_swot = next(row for row in matrix["opportunities"] if row["id"] == swot.json()["id"])
        self.assertEqual(saved_swot["action_items"], ["Compare suppliers"])
        insight = self.client.post(
            "/strategy/market-insights", headers=self.auth_headers,
            json={"type": "trend", "title": "Autumn colors", "description": "Seasonal demand",
                  "source": "Customer survey", "priority": "high"},
        )
        self.assertEqual(insight.status_code, 200, insight.text)
        listing = self.client.get("/strategy/market-insights", headers=self.auth_headers).json()["insights"]
        saved_insight = next(row for row in listing if row["id"] == insight.json()["id"])
        self.assertEqual(saved_insight["priority"], "high")
        self.assertEqual(saved_insight["source"], "Customer survey")

    def test_supplier_create_and_edit_persist_in_summary(self):
        supplier = self.catalog_request("post", "/inventory/suppliers", {
            "name": "New supplier", "contact_name": "Supplier contact", "phone": "0123456789",
            "email": "supplier@example.com", "address": "Test address", "rating": 4,
            "lead_time_days": 3, "note": "Blue yarn",
        })
        summary = self.catalog_request("get", "/inventory/summary")
        saved = next(row for row in summary["suppliers"] if row["id"] == supplier["id"])
        self.assertEqual((saved["name"], saved["rating"], saved["lead_time_days"], saved["note"]),
                         ("New supplier", 4, 3, "Blue yarn"))
        self.catalog_request("put", f"/inventory/suppliers/{supplier['id']}",
                             {"name": "Renamed supplier", "lead_time_days": 5, "note": "Pink yarn"})
        saved = self.catalog_request("get", f"/inventory/suppliers/{supplier['id']}")
        self.assertEqual((saved["name"], saved["lead_time_days"], saved["note"]),
                         ("Renamed supplier", 5, "Pink yarn"))

    def test_ga4_missing_and_invalid_credentials_have_actionable_errors(self):
        from unittest.mock import Mock, patch
        from routers import ga4_router as ga4
        missing_file = str(Path(self.temp_dir.name) / "missing-ga4.json")
        with patch.object(ga4, "BetaAnalyticsDataClient", Mock()), \
             patch.object(ga4, "service_account", Mock()), \
             patch.dict(os.environ, {"GA4_CREDENTIALS_JSON": "", "GOOGLE_APPLICATION_CREDENTIALS": missing_file}):
            for path in ["/ga4/dashboard", "/ga4/realtime", "/ga4/correlation", "/ga4/ai-context"]:
                response = self.client.get(path, headers=self.auth_headers)
                self.assertEqual(response.status_code, 503, response.text)
                self.assertIn("GA4_CREDENTIALS_JSON", response.json()["detail"])
                self.assertNotIn(missing_file, response.text)
            os.environ["GA4_CREDENTIALS_JSON"] = "PRIVATE_KEY_SHOULD_NEVER_LEAK"
            response = self.client.get("/ga4/dashboard", headers=self.auth_headers)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("PRIVATE_KEY_SHOULD_NEVER_LEAK", response.text)

    def test_ga4_accepts_environment_json_and_local_file_credentials(self):
        import json
        from unittest.mock import Mock, patch
        from routers import ga4_router as ga4
        info = {"type": "service_account", "client_email": "ga4@example.com", "private_key": "fake-test-key"}
        credentials_file = Path(self.temp_dir.name) / "ga4.json"
        credentials_file.write_text(json.dumps(info), encoding="utf-8")
        for raw_json in (json.dumps(info), ""):
            with patch.object(ga4, "BetaAnalyticsDataClient") as client_factory, \
                 patch.object(ga4, "service_account", Mock()) as account, \
                 patch.dict(os.environ, {"GA4_CREDENTIALS_JSON": raw_json,
                                        "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_file),
                                        "GA4_PROPERTY_ID": "properties/123456"}):
                self.assertEqual(ga4._property_name(), "properties/123456")
                ga4._client()
                account.Credentials.from_service_account_info.assert_called_once_with(
                    info, scopes=["https://www.googleapis.com/auth/analytics.readonly"],
                )
                client_factory.assert_called_once_with(credentials=account.Credentials.from_service_account_info.return_value)

    def test_purchase_order_generate_persists_draft(self):
        response = self.client.post(
            "/inventory/purchase-orders/generate",
            headers=self.auth_headers,
            json={
                "supplier_id": None,
                "items": [
                    {"material_id": 1, "quantity": 3, "unit_price": 12000},
                    {"material_id": 2, "suggested_quantity": 2, "unit_price": 5000},
                ],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["status"], "draft")
        self.assertEqual(payload["total_amount"], 46000)

        detail = self.client.get(
            f"/inventory/purchase-orders/{payload['id']}",
            headers=self.auth_headers,
        )
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["computed_total"], 46000)

    def test_creating_multiple_orders_uses_distinct_ids(self):
        product_response = self.client.post(
            "/products",
            headers=self.auth_headers,
            json={
                "name": "Order ID Product",
                "base_price": 50000,
                "difficulty": 1,
                "time_minutes": 10,
                "materials": [],
            },
        )
        self.assertEqual(product_response.status_code, 200, product_response.text)
        product_id = product_response.json()["id"]

        order_ids = []
        for idx in range(2):
            response = self.client.post(
                "/orders",
                headers=self.auth_headers,
                json={
                    "date": f"2026-02-0{idx + 1}",
                    "channel": "web",
                    "order_lines": [
                        {
                            "product_id": product_id,
                            "quantity": 1,
                            "unit_price": 50000,
                        }
                    ],
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            order_ids.append(response.json()["id"])

        self.assertEqual(len(set(order_ids)), 2)

    def test_variant_review_payment_and_return_persist(self):
        product_response = self.client.post(
            "/products",
            headers=self.auth_headers,
            json={
                "name": "Test Product",
                "base_price": 120000,
                "difficulty": 2,
                "time_minutes": 30,
                "materials": [],
            },
        )
        self.assertEqual(product_response.status_code, 200, product_response.text)
        product_id = product_response.json()["id"]

        variant_response = self.client.post(
            f"/products/{product_id}/variants",
            headers=self.auth_headers,
            json={
                "product_id": product_id,
                "name": "Variant A",
                "sku": "SKU-A",
                "price_modifier": 5000,
                "stock_quantity": 3,
                "is_active": True,
            },
        )
        self.assertEqual(variant_response.status_code, 200, variant_response.text)

        review_response = self.client.post(
            f"/products/{product_id}/reviews",
            headers=self.auth_headers,
            json={
                "product_id": product_id,
                "customer_name": "Tester",
                "rating": 5,
                "content": "Great",
                "images": [],
            },
        )
        self.assertEqual(review_response.status_code, 200, review_response.text)

        product_detail = self.client.get(
            f"/products/{product_id}", headers=self.auth_headers
        )
        self.assertEqual(product_detail.status_code, 200)
        detail_payload = product_detail.json()
        self.assertEqual(len(detail_payload["variants"]), 1)
        self.assertEqual(detail_payload["variants"][0]["price_modifier"], 5000)
        self.assertEqual(len(detail_payload["reviews"]), 1)
        self.assertEqual(detail_payload["reviews"][0]["content"], "Great")

        order_response = self.client.post(
            "/orders",
            headers=self.auth_headers,
            json={
                "date": "2026-01-01",
                "channel": "web",
                "order_lines": [
                    {
                        "product_id": product_id,
                        "quantity": 1,
                        "unit_price": 120000,
                    }
                ],
            },
        )
        self.assertEqual(order_response.status_code, 200, order_response.text)
        order_id = order_response.json()["id"]

        payment_response = self.client.post(
            f"/orders/{order_id}/payments",
            headers=self.auth_headers,
            json={
                "order_id": order_id,
                "amount": 120000,
                "method": "cash",
                "status": "paid",
            },
        )
        self.assertEqual(payment_response.status_code, 200, payment_response.text)
        paid_order_response = self.client.get(
            f"/orders/{order_id}", headers=self.auth_headers
        )
        self.assertEqual(paid_order_response.status_code, 200)
        self.assertEqual(paid_order_response.json()["payment_status"], "paid")

        return_response = self.client.post(
            f"/orders/{order_id}/returns",
            headers=self.auth_headers,
            json={
                "order_id": order_id,
                "amount": 120000,
                "refund_amount": 120000,
                "reason": "test",
            },
        )
        self.assertEqual(return_response.status_code, 200, return_response.text)

        payments_response = self.client.get(
            "/orders/payments", headers=self.auth_headers, params={"order_id": order_id}
        )
        self.assertEqual(payments_response.status_code, 200)
        self.assertEqual(len(payments_response.json()), 1)

        returns_response = self.client.get(
            "/orders/returns", headers=self.auth_headers, params={"order_id": order_id}
        )
        self.assertEqual(returns_response.status_code, 200)
        self.assertEqual(len(returns_response.json()), 1)


    def catalog_request(self, method, path, payload=None, status=200):
        response = getattr(self.client, method)(path, headers=self.auth_headers, **({"json": payload} if payload is not None else {}))
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def make_material(self, code, stock=100):
        return self.catalog_request("post", "/materials", {"name": code, "code": code, "unit": "gram", "stock_quantity": stock})

    def test_material_edit_updates_balance_history_and_live_summary(self):
        m = self.make_material("stock-edit")
        self.catalog_request("put", f"/materials/{m['id']}", {"name": m["name"], "code": m["code"], "unit": "gram", "stock_quantity": 37})
        updated = self.catalog_request("get", f"/materials/{m['id']}")
        self.assertEqual([updated[k] for k in ("stock_quantity", "on_hand_qty", "available_qty")], [37, 37, 37])
        movements = self.catalog_request("get", f"/materials/{m['id']}/movements")
        self.assertEqual(movements[0]["quantity_change"], -63)
        summary = self.catalog_request("get", "/inventory/summary")
        self.assertEqual(next(r for r in summary["materials"] if r["id"] == m["id"])["stock_quantity"], 37)

    def completed_consumption_fixture(self, code='correct-consumption', usages=None):
        mat = self.make_material(code, 100)
        product = self.catalog_request('post', '/products', {'name': code, 'time_minutes': 0,
            'materials': usages or [{'material_id': mat['id'], 'quantity': 10}]})
        job = self.catalog_request('post', '/production-jobs', {'product_id': product['id'], 'quantity': 2})
        self.catalog_request('patch', f"/production-jobs/{job['id']}/status", {'status': 'completed'})
        job = self.catalog_request('get', f"/production-jobs/{job['id']}")
        return mat, product, job

    def consumption_correction(self, job, quantities, reason='Ghi nhầm lượng tiêu hao', status=200):
        return self.catalog_request('post', f"/production-jobs/{job['id']}/consumption-adjustments", {
            'revision': job['consumption_revision'], 'reason': reason,
            'materials': [{'material_index': index, 'material_id': row['material_id'], 'actual_quantity': quantities[index]}
                          for index, row in enumerate(job['materials'])]}, status=status)

    def test_consumption_correction_returns_only_difference_and_keeps_finished_and_price(self):
        from sqlmodel import Session, select
        from config.database import engine
        from models.material import MaterialBatchTable
        mat, product, job = self.completed_consumption_fixture()
        self.catalog_request('put', f"/materials/{mat['id']}", {'name': mat['name'], 'code': mat['code'], 'unit_price': 99})
        corrected = self.consumption_correction(job, [12])
        self.assertEqual(corrected['materials'][0]['actual_quantity'], 12)
        self.assertEqual(corrected['materials'][0]['unit_price'], job['materials'][0]['unit_price'])
        self.assertEqual(self.catalog_request('get', f"/materials/{mat['id']}")['stock_quantity'], 88)
        self.assertEqual(self.catalog_request('get', f"/products/{product['id']}")['finished_qty'], 2)
        self.assertEqual(corrected['status'], 'completed')
        history = self.catalog_request('get', f"/production-jobs/{job['id']}/consumption-adjustments")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['changes'][0]['stock_change'], 8)
        self.assertEqual(history[0]['changes'][0]['previous_quantity'], 20)
        self.assertEqual(history[0]['reason'], 'Ghi nhầm lượng tiêu hao')
        with Session(engine) as session:
            returned = session.exec(select(MaterialBatchTable).where(MaterialBatchTable.material_id == mat['id'])).all()
            self.assertEqual(sum(row.quantity_remaining for row in returned), 8)
        # A lost HTTP response and retry do not return stock twice or duplicate history.
        self.consumption_correction(job, [12])
        self.assertEqual(self.catalog_request('get', f"/materials/{mat['id']}")['stock_quantity'], 88)
        self.assertEqual(len(self.catalog_request('get', f"/production-jobs/{job['id']}/consumption-adjustments")), 1)
        self.consumption_correction(job, [11], status=409)
        corrected = self.consumption_correction(corrected, [25])
        self.assertEqual(self.catalog_request('get', f"/materials/{mat['id']}")['stock_quantity'], 75)
        corrected = self.consumption_correction(corrected, [0])
        self.assertEqual(corrected['materials'][0]['actual_quantity'], 0)
        self.assertEqual(self.catalog_request('get', f"/materials/{mat['id']}")['stock_quantity'], 100)
        self.assertEqual(self.catalog_request('get', f"/products/{product['id']}")['finished_qty'], 2)
        self.catalog_request('delete', f"/production-jobs/{job['id']}", status=409)

    def test_consumption_correction_batches_and_reservations_reconcile(self):
        from sqlmodel import Session, select
        from config.database import engine
        from models.material import MaterialBatchTable
        from datetime import date
        mat = self.make_material('correction-batches', 100)
        with Session(engine) as session:
            batch = MaterialBatchTable(material_id=mat['id'], batch_code='ORIGINAL-QA',
                quantity_received=100, quantity_remaining=100, unit_cost=2, received_date=date(2000, 1, 1))
            session.add(batch)
            session.commit()
        product = self.catalog_request('post', '/products', {'name': 'Batch correction', 'materials': [{'material_id': mat['id'], 'quantity': 10}]})
        job = self.catalog_request('post', '/production-jobs', {'product_id': product['id'], 'quantity': 2})
        self.catalog_request('patch', f"/production-jobs/{job['id']}/status", {'status': 'in_progress'})
        job = self.catalog_request('get', f"/production-jobs/{job['id']}")
        other = self.catalog_request('post', '/production-jobs', {'product_id': product['id'], 'quantity': 7})
        self.catalog_request('patch', f"/production-jobs/{other['id']}/status", {'status': 'reserved'})
        self.consumption_correction(job, [35], status=409)
        current = self.catalog_request('get', f"/materials/{mat['id']}")
        self.assertEqual((current['stock_quantity'], current['reserved_qty']), (80, 70))
        corrected = self.consumption_correction(job, [12])
        corrected = self.consumption_correction(corrected, [25])
        current = self.catalog_request('get', f"/materials/{mat['id']}")
        self.assertEqual((current['stock_quantity'], current['reserved_qty'], current['available_qty']), (75, 70, 5))
        with Session(engine) as session:
            batches = session.exec(select(MaterialBatchTable).where(MaterialBatchTable.material_id == mat['id'])).all()
            self.assertEqual(sum(row.quantity_remaining for row in batches), 75)
            original = next(row for row in batches if row.batch_code == 'ORIGINAL-QA')
            self.assertEqual(original.quantity_remaining, 67)
        self.catalog_request('patch', f"/production-jobs/{job['id']}/status", {'status': 'completed'})
        self.assertEqual(self.catalog_request('get', f"/materials/{mat['id']}")['stock_quantity'], 75)

    def test_consumption_correction_aggregates_repeated_material_and_rolls_back(self):
        first, second = self.make_material('correction-first', 100), self.make_material('correction-second', 5)
        product = self.catalog_request('post', '/products', {'name': 'Correction rollback', 'materials': [
            {'material_id': first['id'], 'quantity': 2}, {'material_id': first['id'], 'quantity': 3},
            {'material_id': second['id'], 'quantity': 1}]})
        job = self.catalog_request('post', '/production-jobs', {'product_id': product['id']})
        self.catalog_request('patch', f"/production-jobs/{job['id']}/status", {'status': 'completed'})
        job = self.catalog_request('get', f"/production-jobs/{job['id']}")
        self.consumption_correction(job, [60, 60, 1], status=409)
        self.consumption_correction(job, [0, 0, 100], status=409)
        self.assertEqual(self.catalog_request('get', f"/materials/{first['id']}")['stock_quantity'], 95)
        self.assertEqual(self.catalog_request('get', f"/materials/{second['id']}")['stock_quantity'], 4)
        self.assertEqual(self.catalog_request('get', f"/production-jobs/{job['id']}")['consumption_revision'], job['consumption_revision'])
        self.assertEqual(self.catalog_request('get', f"/production-jobs/{job['id']}/consumption-adjustments"), [])
        result = self.consumption_correction(job, [0, 7, 1])
        self.assertEqual([row['actual_quantity'] for row in result['materials']], [0, 7, 1])
        self.assertEqual(self.catalog_request('get', f"/materials/{first['id']}")['stock_quantity'], 93)

    def test_consumption_correction_validates_state_units_input_and_permissions(self):
        mat, product, job = self.completed_consumption_fixture('correction-input')
        for quantity in (-1, 1.00001):
            self.consumption_correction(job, [quantity], status=422)
        self.consumption_correction(job, [12], reason='   ', status=422)
        path = f"/production-jobs/{job['id']}/consumption-adjustments"
        body = {'revision': job['consumption_revision'], 'reason': 'QA', 'materials': [
            {'material_index': 0, 'material_id': mat['id'], 'actual_quantity': 12}]}
        self.assertEqual(self.client.post(path, json=body).status_code, 401)
        self.assertEqual(self.client.get(path).status_code, 401)
        viewer = self.client.post('/auth/register', json={'email': 'consumption-viewer@example.com', 'password': 'viewer-password'}).json()
        self.assertEqual(self.client.post(path, json=body, headers={'Authorization': 'Bearer ' + viewer['access_token']}).status_code, 403)
        duplicate = {**body, 'materials': body['materials'] * 2}
        self.catalog_request('post', path, duplicate, status=422)
        pending = self.catalog_request('post', '/production-jobs', {'product_id': product['id']})
        pending = self.catalog_request('get', f"/production-jobs/{pending['id']}")
        self.consumption_correction(pending, [5], status=409)
        piece = self.make_material('correction-piece', 100)
        self.catalog_request('put', f"/materials/{piece['id']}", {'name': piece['name'], 'code': piece['code'], 'unit_type': 'piece', 'unit': 'cái'})
        product = self.catalog_request('post', '/products', {'name': 'Piece correction', 'materials': [{'material_id': piece['id'], 'quantity': 1}]})
        job = self.catalog_request('post', '/production-jobs', {'product_id': product['id']})
        self.catalog_request('patch', f"/production-jobs/{job['id']}/status", {'status': 'completed'})
        job = self.catalog_request('get', f"/production-jobs/{job['id']}")
        self.consumption_correction(job, [0.5], status=422)

    def replace_consumption(self, job, edits, status=200):
        return self.catalog_request('post', f"/production-jobs/{job['id']}/consumption-adjustments", {
            'revision': job['consumption_revision'], 'reason': 'Ghi sai loại nguyên liệu thực tế',
            'materials': [{'material_index': index, 'material_id': job['materials'][index]['material_id'],
                          'replacement_material_id': mid, 'actual_quantity': quantity} for index, mid, quantity in edits]}, status=status)

    def test_consumption_replacement_returns_old_and_consumes_new_without_changing_finished(self):
        old, product, job = self.completed_consumption_fixture('replacement-old')
        new = self.make_material('replacement-new', 100)
        self.catalog_request('put', f"/materials/{new['id']}", {'name': new['name'], 'code': new['code'], 'unit_price': 3})
        result = self.replace_consumption(job, [(0, new['id'], 7)])
        actual = result['materials'][0]
        self.assertEqual((actual['material_id'], actual['actual_quantity'], actual['unit_price']), (new['id'], 7, 3))
        self.assertEqual(actual['unit_price_basis'], 'correction_current_price')
        self.assertEqual((actual['planned_material_id'], actual['planned_quantity'], actual['quantity_per_product']), (old['id'], 20, 10))
        self.assertEqual(self.catalog_request('get', f"/materials/{old['id']}")['stock_quantity'], 100)
        self.assertEqual(self.catalog_request('get', f"/materials/{new['id']}")['stock_quantity'], 93)
        self.assertEqual(self.catalog_request('get', f"/products/{product['id']}")['finished_qty'], 2)
        self.assertEqual(result['status'], 'completed')
        self.replace_consumption(job, [(0, new['id'], 7)])
        history = self.catalog_request('get', f"/production-jobs/{job['id']}/consumption-adjustments")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['replacements'][0]['previous_material_id'], old['id'])
        self.assertEqual([(c['material_id'], c['stock_change']) for c in history[0]['changes']], [(old['id'], 20), (new['id'], -7)])
        self.assertEqual(self.catalog_request('get', f"/materials/{new['id']}")['stock_quantity'], 93)
        self.replace_consumption(job, [(0, old['id'], 8)], status=409)
        restored = self.replace_consumption(result, [(0, old['id'], 8)])
        self.assertEqual(restored['materials'][0]['planned_material_id'], old['id'])
        self.assertEqual(self.catalog_request('get', f"/materials/{new['id']}")['stock_quantity'], 100)
        self.assertEqual(self.catalog_request('get', f"/materials/{old['id']}")['stock_quantity'], 92)

    def test_consumption_replacement_shortage_rolls_back_and_uses_new_unit(self):
        old, product, job = self.completed_consumption_fixture('replacement-atomic-old')
        new = self.make_material('replacement-piece', 1)
        self.catalog_request('put', f"/materials/{new['id']}", {'name': new['name'], 'code': new['code'], 'unit_type': 'piece', 'unit': 'cái'})
        self.replace_consumption(job, [(0, new['id'], 2)], status=409)
        self.replace_consumption(job, [(0, new['id'], 0.5)], status=422)
        self.replace_consumption(job, [(0, 999999, 1)], status=409)
        self.assertEqual(self.catalog_request('get', f"/materials/{old['id']}")['stock_quantity'], 80)
        self.assertEqual(self.catalog_request('get', f"/production-jobs/{job['id']}/consumption-adjustments"), [])
        result = self.replace_consumption(job, [(0, new['id'], 1)])
        self.assertEqual((result['materials'][0]['unit'], result['materials'][0]['unit_type']), ('cái', 'piece'))
        self.assertEqual(result['materials'][0]['planned_unit'], old['unit'])
        self.assertEqual(self.catalog_request('get', f"/materials/{old['id']}")['stock_quantity'], 100)

    def test_consumption_replacement_aggregates_shared_targets_and_supports_atomic_swap(self):
        first, second, target = [self.make_material(f'replacement-swap-{index}', 10) for index in range(3)]
        product = self.catalog_request('post', '/products', {'name': 'Replacement swap', 'materials': [
            {'material_id': first['id'], 'quantity': 10}, {'material_id': second['id'], 'quantity': 10}]})
        job = self.catalog_request('post', '/production-jobs', {'product_id': product['id']})
        self.catalog_request('patch', f"/production-jobs/{job['id']}/status", {'status': 'completed'})
        job = self.catalog_request('get', f"/production-jobs/{job['id']}")
        self.replace_consumption(job, [(0, target['id'], 6), (1, target['id'], 6)], status=409)
        self.assertEqual(self.catalog_request('get', f"/materials/{first['id']}")['stock_quantity'], 0)
        self.assertEqual(self.catalog_request('get', f"/materials/{target['id']}")['stock_quantity'], 10)
        swapped = self.replace_consumption(job, [(0, second['id'], 10), (1, first['id'], 10)])
        self.assertEqual([row['material_id'] for row in swapped['materials']], [second['id'], first['id']])
        self.assertEqual([self.catalog_request('get', f"/materials/{m['id']}")['stock_quantity'] for m in (first, second)], [0, 0])

    def test_consumption_replacement_zero_quantity_keeps_audit_and_progress_does_not_reconsume(self):
        old, product, job = self.completed_consumption_fixture('replacement-zero-old')
        other = self.make_material('replacement-zero-new', 100)
        zero = self.consumption_correction(job, [0])
        # Older completed jobs can lack a start timestamp; a zero correction must
        # not permanently prevent another correction to the completed record.
        from sqlmodel import Session
        from config.database import engine
        from models.production import ProductionJobTable
        with Session(engine) as session:
            legacy = session.get(ProductionJobTable, job['id'])
            legacy.started_at = None
            session.add(legacy)
            session.commit()
        result = self.replace_consumption(zero, [(0, other['id'], 0)])
        history = self.catalog_request('get', f"/production-jobs/{job['id']}/consumption-adjustments")
        self.assertEqual(history[0]['replacements'][0]['material_id'], other['id'])
        self.assertEqual(history[0]['materials'][0]['material_id'], other['id'])
        self.replace_consumption(zero, [(0, other['id'], 0)])
        self.assertEqual(len(self.catalog_request('get', f"/production-jobs/{job['id']}/consumption-adjustments")), len(history))
        running = self.catalog_request('post', '/production-jobs', {'product_id': product['id']})
        self.catalog_request('patch', f"/production-jobs/{running['id']}/status", {'status': 'in_progress'})
        running = self.catalog_request('get', f"/production-jobs/{running['id']}")
        self.replace_consumption(running, [(0, other['id'], 5)])
        self.catalog_request('patch', f"/production-jobs/{running['id']}/status", {'status': 'completed'})
        self.assertEqual(self.catalog_request('get', f"/materials/{other['id']}")['stock_quantity'], 95)
        self.assertEqual(self.catalog_request('get', f"/products/{product['id']}")['finished_qty'], 3)

    def test_job_uses_selected_material_snapshot_and_consumes_once(self):
        primary = self.make_material("primary-blue")
        actual = self.make_material("other-brand-blue")
        p = self.catalog_request("post", "/products", {"name": "Same product, different yarn", "materials": [{"material_id": primary["id"], "quantity": 10, "alternative_material_ids": [actual["id"]]}]})
        job = self.catalog_request("post", "/production-jobs", {"product_id": p["id"], "quantity": 2, "materials": [{"material_id": actual["id"], "quantity": 8}]})
        self.catalog_request("put", f"/products/{p['id']}", {"name": p["name"], "materials": [{"material_id": primary["id"], "quantity": 99}]})
        self.catalog_request("patch", f"/production-jobs/{job['id']}/status", {"status": "reserved"})
        reserved = self.catalog_request("get", f"/materials/{actual['id']}")
        self.assertEqual((reserved["stock_quantity"], reserved["reserved_qty"], reserved["available_qty"]), (100, 16, 84))
        self.catalog_request("put", f"/materials/{actual['id']}", {"name": actual["name"], "code": actual["code"], "stock_quantity": 10}, status=409)
        self.catalog_request("put", f"/production-jobs/{job['id']}", {"quantity": 4}, status=409)
        for status in ("in_progress", "paused", "in_progress", "completed", "completed"):
            self.catalog_request("patch", f"/production-jobs/{job['id']}/status", {"status": status})
        self.assertEqual(self.catalog_request("get", f"/materials/{actual['id']}")["stock_quantity"], 84)
        self.assertEqual(self.catalog_request("get", f"/materials/{primary['id']}")["stock_quantity"], 100)
        self.assertEqual(self.catalog_request("get", f"/products/{p['id']}")["finished_qty"], 2)
        self.catalog_request("patch", f"/production-jobs/{job['id']}/status", {"status": "in_progress"}, status=409)

    def test_job_shortage_rolls_back_all_materials(self):
        first, second = self.make_material("atomic-first"), self.make_material("atomic-second", 1)
        p = self.catalog_request("post", "/products", {"name": "Shortage rollback"})
        job = self.catalog_request("post", "/production-jobs", {"product_id": p["id"], "materials": [{"material_id": first["id"], "quantity": 5}, {"material_id": second["id"], "quantity": 5}]})
        self.catalog_request("patch", f"/production-jobs/{job['id']}/status", {"status": "in_progress"}, status=400)
        self.assertEqual(self.catalog_request("get", f"/materials/{first['id']}")["stock_quantity"], 100)
        self.assertEqual(self.catalog_request("get", f"/materials/{first['id']}/movements"), [])

    def test_job_edit_and_cancel_only_releases_its_own_hold(self):
        mat = self.make_material("shared-yarn")
        p = self.catalog_request("post", "/products", {"name": "Shared holds", "materials": [{"material_id": mat["id"], "quantity": 5}]})
        a = self.catalog_request("post", "/production-jobs", {"product_id": p["id"]})
        b = self.catalog_request("post", "/production-jobs", {"product_id": p["id"]})
        edited = self.catalog_request("put", f"/production-jobs/{a['id']}", {"quantity": 3, "notes": "blue"})
        self.assertEqual(edited["materials"][0]["planned_quantity"], 15)
        for job in (a, b):
            self.catalog_request("patch", f"/production-jobs/{job['id']}/status", {"status": "reserved"})
        self.catalog_request("patch", f"/production-jobs/{a['id']}/status", {"status": "cancelled"})
        state = self.catalog_request("get", f"/materials/{mat['id']}")
        self.assertEqual((state["stock_quantity"], state["reserved_qty"]), (100, 5))

    def test_price_history_partial_edit_preserves_other_fields(self):
        p = self.catalog_request("post", "/products", {"name": "Price history", "base_price": 100, "packaging_cost": 25, "tags": ["keep"]})
        updated = self.catalog_request("put", f"/products/{p['id']}", {"name": p["name"], "base_price": 150, "time_minutes": 0})
        self.assertEqual((updated["packaging_cost"], updated["tags"], updated["time_minutes"]), (25, ["keep"], 0))
        self.catalog_request("put", f"/products/{p['id']}", {"name": p["name"], "base_price": 150})
        history = self.catalog_request("get", f"/products/{p['id']}/history")["price_changes"]
        self.assertEqual(len(history), 1)
        self.assertEqual((history[0]["old_price"], history[0]["new_price"]), (100, 150))

    def test_catalog_supplier_category_and_image_edit(self):
        self.catalog_request("post", "/inventory/suppliers", {"name": "Yarn supplier"})
        parent = self.catalog_request("post", "/categories", {"name": "Parent"})
        child = self.catalog_request("post", "/categories", {"name": "Child", "parent_id": parent["id"]})
        self.catalog_request("put", f"/categories/{parent['id']}", {"name": "Parent", "parent_id": child["id"]}, status=400)
        self.catalog_request("put", f"/categories/{child['id']}", {"name": "Child edited", "parent_id": parent["id"], "display_order": 0})
        self.catalog_request("post", "/catalog/tags", {"name": "new tag"})
        canonical = self.catalog_request("post", "/catalog/tags", {"name": "NEW TAG"})
        self.assertEqual(canonical["name"], "new tag")
        p = self.catalog_request("post", "/products", {"name": "Image and tag", "tags": ["new tag"]})
        self.catalog_request("put", "/catalog/tags/new%20tag", {"name": "renamed tag"})
        self.assertEqual(self.catalog_request("get", f"/products/{p['id']}")["tags"], ["renamed tag"])
        self.catalog_request("delete", "/catalog/tags/renamed%20tag", status=409)
        image = self.catalog_request("post", "/product-images", {"product_id": p["id"], "url": "https://example.com/old.png"})
        self.catalog_request("put", f"/product-images/{image['id']}", {"url": "https://example.com/new.png"})
        images = self.catalog_request("get", f"/products/{p['id']}")["images"]
        self.assertEqual(images[0]["url"], "https://example.com/new.png")

    def test_order_confirmation_does_not_hold_default_yarn(self):
        mat = self.make_material("order-default-yarn", 1)
        actual = self.make_material("order-selected-yarn", 50)
        p = self.catalog_request("post", "/products", {"name": "Order custom color", "materials": [{"material_id": mat["id"], "quantity": 10}]})
        order = self.catalog_request("post", "/orders", {"date": "2026-10-22", "status": "confirmed", "order_lines": [{"product_id": p["id"], "quantity": 1, "unit_price": 100}]})
        self.assertEqual(self.catalog_request("get", f"/materials/{mat['id']}")["reserved_qty"], 0)
        job = self.catalog_request("post", "/production-jobs", {"product_id": p["id"], "order_id": order["id"], "materials": [{"material_id": actual["id"], "quantity": 10}]})
        self.catalog_request("patch", f"/production-jobs/{job['id']}/status", {"status": "completed"})
        self.assertEqual(self.catalog_request("get", f"/materials/{actual['id']}")["stock_quantity"], 40)
        self.assertEqual(self.catalog_request("get", f"/materials/{mat['id']}")["stock_quantity"], 1)

    def test_unit_metadata_rounding_and_invalid_job_quantities(self):
        self.catalog_request("post", "/catalog/units", {"name": "test pair", "unit_type": "piece"})
        entries = self.catalog_request("get", "/catalog/units")
        self.assertEqual(next(r for r in entries if r["name"] == "test pair")["unit_type"], "piece")
        mat = self.catalog_request("post", "/materials", {"name": "Pair", "code": "pair", "unit": "test pair", "unit_type": "piece", "stock_quantity": 10})
        p = self.catalog_request("post", "/products", {"name": "Rounded use", "materials": [{"material_id": mat["id"], "quantity": 0.5, "wastage_percent": 10}]})
        self.assertEqual(self.catalog_request("get", f"/products/{p['id']}")["materials"][0]["quantity"], 0.5)
        job = self.catalog_request("post", "/production-jobs", {"product_id": p["id"], "quantity": 2})
        self.assertEqual(job["materials"][0]["planned_quantity"], 2)
        self.catalog_request("post", "/production-jobs", {"product_id": p["id"], "materials": [{"material_id": mat["id"], "quantity": -1}]}, status=422)

    def test_upload_without_cloudinary_persists_image_in_sql(self):
        import base64
        from unittest.mock import patch
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        with patch("routers.upload.cloudinary", None):
            response = self.client.post("/upload/images", headers=self.auth_headers, files={"file": ("pixel.png", png, "image/png")})
        self.assertEqual(response.status_code, 200, response.text)
        url = response.json()["url"]
        self.assertTrue(url.startswith("data:image/png;base64,"))
        p = self.catalog_request("post", "/products", {"name": "Stored upload"})
        self.catalog_request("post", "/product-images", {"product_id": p["id"], "url": url})
        self.assertEqual(self.catalog_request("get", f"/products/{p['id']}")["images"][0]["url"], url)

    def test_order_cancellation_releases_job_hold_but_rejects_consumed_job(self):
        mat = self.make_material("cancel-order-job", 30)
        p = self.catalog_request("post", "/products", {"name": "Cancel job", "materials": [{"material_id": mat["id"], "quantity": 5}]})
        def create_pair():
            order = self.catalog_request("post", "/orders", {"date": "2026-10-22", "status": "confirmed", "order_lines": [{"product_id": p["id"], "quantity": 1, "unit_price": 100}]})
            job = self.catalog_request("post", "/production-jobs", {"product_id": p["id"], "order_id": order["id"]})
            return order, job
        order, job = create_pair()
        self.catalog_request("patch", f"/production-jobs/{job['id']}/status", {"status": "reserved"})
        self.catalog_request("patch", f"/orders/{order['id']}/status", {"status": "cancelled"})
        self.assertEqual(self.catalog_request("get", f"/materials/{mat['id']}")["reserved_qty"], 0)
        self.assertEqual(next(j for j in self.catalog_request("get", "/production-jobs") if j["id"] == job["id"])["status"], "cancelled")
        order, job = create_pair()
        self.catalog_request("patch", f"/production-jobs/{job['id']}/status", {"status": "in_progress"})
        self.catalog_request("patch", f"/orders/{order['id']}/status", {"status": "cancelled"}, status=409)
        self.assertEqual(self.catalog_request("get", f"/materials/{mat['id']}")["stock_quantity"], 25)

    def test_job_keeps_raw_usage_and_wastage_when_edited(self):
        mat = self.make_material("raw-plan")
        p = self.catalog_request("post", "/products", {"name": "Raw plan", "wastage_percent": 5})
        job = self.catalog_request("post", "/production-jobs", {"product_id": p["id"], "quantity": 2, "materials": [{"material_id": mat["id"], "quantity": 10, "wastage_percent": 3}]})
        usage = job["materials"][0]
        self.assertEqual((usage["quantity_per_product"], usage["wastage_percent"], usage["product_wastage_percent"], usage["planned_quantity"]), (10, 3, 5, 21.6))
        self.catalog_request("put", f"/products/{p['id']}", {"name": p["name"], "wastage_percent": 20})
        edited = self.catalog_request("put", f"/production-jobs/{job['id']}", {"materials": [{"material_id": mat["id"], "quantity": 12, "wastage_percent": 3, "product_wastage_percent": 5}]})
        self.assertEqual(edited["materials"][0]["planned_quantity"], 25.92)
        resized = self.catalog_request("put", f"/production-jobs/{job['id']}", {"quantity": 3})
        self.assertEqual(resized["materials"][0]["planned_quantity"], 38.88)

    def test_unit_is_inferred_and_duplicate_material_code_returns_conflict(self):
        payload = {"name": "Paired unit", "code": "unique-pair", "unit": "cặp", "stock_quantity": 4}
        mat = self.catalog_request("post", "/materials", payload)
        self.assertEqual(mat["unit_type"], "piece")
        self.catalog_request("post", "/materials", payload, status=409)
        self.catalog_request("post", "/catalog/units", {"name": "custom whole", "unit_type": "piece"})
        changed = self.catalog_request("put", f"/materials/{mat['id']}", {**payload, "unit": "custom whole"})
        self.assertEqual(changed["unit_type"], "piece")

    def test_job_actual_price_is_fixed_at_consumption(self):
        mat = self.catalog_request("post", "/materials", {"name": "Actual cost", "code": "actual-cost", "stock_quantity": 20, "unit": "gram", "unit_price": 50})
        p = self.catalog_request("post", "/products", {"name": "Actual yarn cost", "materials": [{"material_id": mat["id"], "quantity": 2}]})
        job = self.catalog_request("post", "/production-jobs", {"product_id": p["id"]})
        self.catalog_request("put", f"/materials/{mat['id']}", {"name": mat["name"], "code": mat["code"], "unit": "gram", "unit_price": 60})
        started = self.catalog_request("patch", f"/production-jobs/{job['id']}/status", {"status": "in_progress"})
        self.assertEqual(started["materials"][0]["unit_price"], 60)
        self.catalog_request("put", f"/materials/{mat['id']}", {"name": mat["name"], "code": mat["code"], "unit": "gram", "unit_price": 99})
        completed = self.catalog_request("patch", f"/production-jobs/{job['id']}/status", {"status": "completed"})
        self.assertEqual(completed["materials"][0]["unit_price"], 60)

    def test_cost_capacity_and_job_use_the_same_piece_rounding(self):
        mat = self.catalog_request("post", "/materials", {"name": "Whole pieces", "code": "cost-pieces", "unit": "cặp", "unit_price": 100, "stock_quantity": 5})
        p = self.catalog_request("post", "/products", {"name": "Whole piece costing", "wastage_percent": 5, "materials": [{"material_id": mat["id"], "quantity": 1}]})
        cost = self.catalog_request("get", f"/products/{p['id']}/cost")
        self.assertEqual(cost["material_cost"], 200)
        self.assertEqual(cost["max_units_from_stock"], 2)
        job = self.catalog_request("post", "/production-jobs", {"product_id": p["id"]})
        self.catalog_request("patch", f"/production-jobs/{job['id']}/status", {"status": "reserved"})
        cost = self.catalog_request("get", f"/products/{p['id']}/cost")
        self.assertEqual(cost["max_units_from_stock"], 1)
        summary = self.catalog_request("get", "/inventory/summary")
        self.assertEqual(next(x for x in summary["products"] if x["id"] == p["id"])["max_units_from_stock"], 1)

    def test_notification_settings_round_trip_as_a_list(self):
        emails = ["qa-one@example.com", "qa-two@example.com"]
        self.catalog_request("put", "/settings", {"notification_emails": emails})
        from app_bootstrap import load_settings_from_db
        load_settings_from_db()
        self.assertEqual(self.catalog_request("get", "/settings")["notification_emails"], emails)
        self.assertEqual(self.catalog_request("get", "/settings/notification_emails")["value"], emails)


    def test_delete_product_cleans_owned_rows_and_disappears(self):
        from sqlmodel import Session, select
        from config.database import engine
        from models import ProductImageTable, ProductVariantTable, PriceChangeTable, LifecycleEventTable
        product = self.catalog_request("post", "/products", {"name": "Disposable product", "base_price": 100})
        pid = product["id"]
        self.catalog_request("post", "/product-images", {"product_id": pid, "url": "https://example.com/test.png"})
        self.catalog_request("post", f"/products/{pid}/variants", {"name": "Disposable variant"})
        self.catalog_request("put", f"/products/{pid}", {"name": product["name"], "base_price": 120, "lifecycle_status": "prototype"})
        self.catalog_request("delete", f"/products/{pid}")
        self.catalog_request("get", f"/products/{pid}", status=404)
        self.catalog_request("delete", f"/products/{pid}", status=404)
        with Session(engine) as session:
            for model in (ProductImageTable, ProductVariantTable, PriceChangeTable, LifecycleEventTable):
                self.assertEqual(session.exec(select(model).where(model.product_id == pid)).all(), [])

    def test_delete_product_order_and_job_dependencies(self):
        p = self.catalog_request("post", "/products", {"name": "Order dependency"})
        order = self.catalog_request("post", "/orders", {"date": "2026-10-22", "order_lines": [{"product_id": p["id"], "quantity": 1, "unit_price": 100}]})
        self.catalog_request("delete", f"/products/{p['id']}", status=409)
        self.catalog_request("delete", f"/orders/{order['id']}")
        job = self.catalog_request("post", "/production-jobs", {"product_id": p["id"]})
        self.catalog_request("delete", f"/products/{p['id']}", status=409)
        self.catalog_request("delete", f"/production-jobs/{job['id']}")
        self.catalog_request("delete", f"/products/{p['id']}")

    def test_delete_material_checks_alternatives_stock_and_supplier_links(self):
        supplier = self.catalog_request("post", "/inventory/suppliers", {"name": "Disposable supplier"})
        main = self.catalog_request("post", "/materials", {"code": "delete-main", "name": "Primary", "supplier_id": supplier["id"]})
        alt = self.make_material("delete-alternative", 0)
        product = self.catalog_request("post", "/products", {"name": "Alternative dependency", "materials": [
            {"material_id": main["id"], "quantity": 10, "alternative_material_ids": [main["id"], alt["id"], alt["id"]]}
        ]})
        self.assertEqual(product["materials"][0]["alternative_material_ids"], [alt["id"]])
        self.catalog_request("delete", f"/materials/{main['id']}", status=409)
        self.catalog_request("delete", f"/materials/{alt['id']}", status=409)
        self.catalog_request("delete", f"/inventory/suppliers/{supplier['id']}", status=409)
        self.catalog_request("delete", f"/products/{product['id']}")
        self.catalog_request("delete", f"/materials/{main['id']}")
        self.catalog_request("delete", f"/materials/{alt['id']}")
        self.catalog_request("delete", f"/inventory/suppliers/{supplier['id']}")
        stock = self.make_material("delete-has-stock", 10)
        self.catalog_request("delete", f"/materials/{stock['id']}", status=409)
        self.assertEqual(self.catalog_request("get", f"/materials/{stock['id']}")["stock_quantity"], 10)

    def test_delete_customer_only_without_orders(self):
        customer = self.catalog_request("post", "/customers", {"name": "Disposable customer"})
        product = self.catalog_request("post", "/products", {"name": "Customer reference"})
        order = self.catalog_request("post", "/orders", {"date": "2026-10-22", "customer_id": customer["id"],
            "order_lines": [{"product_id": product["id"], "quantity": 1, "unit_price": 100}]})
        self.catalog_request("delete", f"/customers/{customer['id']}", status=409)
        self.catalog_request("delete", f"/orders/{order['id']}")
        self.catalog_request("delete", f"/customers/{customer['id']}")
        self.catalog_request("get", f"/customers/{customer['id']}", status=404)

    def test_delete_po_preserves_paid_history(self):
        draft = self.catalog_request("post", "/inventory/purchase-orders", {"lines": []})
        self.catalog_request("delete", f"/inventory/purchase-orders/{draft['id']}")
        paid = self.catalog_request("post", "/inventory/purchase-orders", {"lines": []})
        self.catalog_request("post", f"/inventory/purchase-orders/{paid['id']}/payment", {"amount": 50})
        self.catalog_request("delete", f"/inventory/purchase-orders/{paid['id']}", status=409)
        self.assertEqual(self.catalog_request("get", f"/inventory/purchase-orders/{paid['id']}")["paid_amount"], 50)

    def test_delete_strategy_all_kinds_and_wrong_kind_rejected(self):
        for kind, payload in [
            ("okrs", {"title": "Disposable OKR", "quarter": "Q4-2026"}),
            ("swot", {"type": "strength", "description": "Disposable SWOT"}),
            ("market-insights", {"type": "trend", "title": "Disposable insight"}),
        ]:
            item = self.catalog_request("post", f"/strategy/{kind}", payload)
            wrong_kind = "swot" if kind == "okrs" else "okrs"
            self.catalog_request("delete", f"/strategy/{wrong_kind}/{item['id']}", status=404)
            self.catalog_request("delete", f"/strategy/{kind}/{item['id']}")
            self.catalog_request("delete", f"/strategy/{kind}/{item['id']}", status=404)

    def test_delete_content_legacy_alias_removes_sql_and_checks_order_source(self):
        plan = self.catalog_request("post", "/content/plans", {"title": "Disposable content"})
        self.catalog_request("delete", f"/content-plans/{plan['id']}")
        listing = self.catalog_request("get", "/content/plans")
        self.assertNotIn(plan["id"], [p["id"] for p in listing])
        plan = self.catalog_request("post", "/content/plans", {"title": "Content revenue"})
        product = self.catalog_request("post", "/products", {"name": "Content attribution product"})
        self.catalog_request("post", "/orders", {"date": "2026-10-22", "source_content_id": plan["id"],
            "order_lines": [{"product_id": product["id"], "quantity": 1, "unit_price": 100}]})
        self.catalog_request("delete", f"/content/plans/{plan['id']}", status=409)
        self.catalog_request("delete", f"/content-plans/{plan['id']}", status=409)

    def test_delete_job_after_cancel_does_not_change_stock_or_other_holds(self):
        material = self.make_material("delete-job-yarn", 100)
        product = self.catalog_request("post", "/products", {"name": "Job deletion", "materials": [{"material_id": material["id"], "quantity": 10}]})
        jobs = [self.catalog_request("post", "/production-jobs", {"product_id": product["id"]}) for _ in range(2)]
        for job in jobs:
            self.catalog_request("patch", f"/production-jobs/{job['id']}/status", {"status": "reserved"})
        self.catalog_request("delete", f"/production-jobs/{jobs[0]['id']}", status=409)
        self.catalog_request("patch", f"/production-jobs/{jobs[0]['id']}/status", {"status": "cancelled"})
        self.catalog_request("delete", f"/production-jobs/{jobs[0]['id']}")
        current = self.catalog_request("get", f"/materials/{material['id']}")
        self.assertEqual((current["stock_quantity"], current["reserved_qty"]), (100, 10))
        self.catalog_request("patch", f"/production-jobs/{jobs[1]['id']}/status", {"status": "in_progress"})
        self.catalog_request("delete", f"/production-jobs/{jobs[1]['id']}", status=409)
        self.assertEqual(self.catalog_request("get", f"/materials/{material['id']}")["stock_quantity"], 90)

    def test_delete_routes_require_admin_and_do_not_accept_anonymous_requests(self):
        response = self.client.post("/auth/register", json={"email": "delete-viewer@example.com", "password": "ViewerPassword123"})
        self.assertEqual(response.status_code, 200, response.text)
        headers = {"Authorization": "Bearer " + response.json()["access_token"]}
        for path in ["/products/999999", "/materials/999999", "/inventory/suppliers/999999", "/inventory/purchase-orders/999999",
                     "/customers/999999", "/orders/999999", "/production-jobs/999999", "/strategy/okrs/999999",
                     "/strategy/swot/999999", "/strategy/market-insights/999999", "/products/variants/999999",
                     "/content/plans/999999", "/content-plans/999999", "/issues/999999"]:
            self.assertEqual(self.client.delete(path).status_code, 401, path)
            self.assertEqual(self.client.delete(path, headers=headers).status_code, 403, path)

    def test_bom_alternatives_are_validated_per_row_and_saved_as_snapshot(self):
        main, alt1, alt2, pink, pink_alt = [self.make_material(f"bom-row-{i}", 100) for i in range(5)]
        product = self.catalog_request("post", "/products", {"name": "Per-row alternatives", "materials": [
            {"material_id": main["id"], "quantity": 10, "alternative_material_ids": [alt1["id"], alt2["id"]]},
            {"material_id": pink["id"], "quantity": 15, "alternative_material_ids": [pink_alt["id"]]},
        ]})
        job = self.catalog_request("post", "/production-jobs", {"product_id": product["id"], "quantity": 2})
        self.assertEqual([row["bom_line_index"] for row in job["materials"]], [0, 1])
        self.assertEqual(job["materials"][0]["alternative_material_ids"], [alt1["id"], alt2["id"]])
        rows = [{"material_id": alt2["id"], "bom_line_index": 0, "bom_material_id": main["id"], "quantity": 10},
                {"material_id": pink_alt["id"], "bom_line_index": 1, "bom_material_id": pink["id"], "quantity": 15}]
        self.catalog_request("put", f"/production-jobs/{job['id']}", {"materials": [{**rows[0], "material_id": pink_alt["id"]}]}, status=422)
        self.catalog_request("put", f"/products/{product['id']}", {"name": product["name"], "materials": []})
        updated = self.catalog_request("put", f"/production-jobs/{job['id']}", {"materials": rows})
        self.assertEqual([row["planned_quantity"] for row in updated["materials"]], [20, 30])
        self.catalog_request("patch", f"/production-jobs/{job['id']}/status", {"status": "completed"})
        for material, expected in [(main, 100), (alt1, 100), (alt2, 80), (pink, 100), (pink_alt, 70)]:
            self.assertEqual(self.catalog_request("get", f"/materials/{material['id']}")["stock_quantity"], expected)

    def test_shared_alternative_keeps_bom_rows_and_checks_combined_stock(self):
        main1, main2, common = [self.make_material(f"bom-shared-{i}", 40) for i in range(3)]
        product = self.catalog_request("post", "/products", {"name": "Shared alternative", "materials": [
            {"material_id": main1["id"], "quantity": 10, "alternative_material_ids": [common["id"]]},
            {"material_id": main2["id"], "quantity": 15, "alternative_material_ids": [common["id"]]},
        ]})
        rows = [{"bom_line_index": index, "material_id": common["id"], "quantity": amount} for index, amount in enumerate([10, 15])]
        job = self.catalog_request("post", "/production-jobs", {"product_id": product["id"], "quantity": 2, "materials": rows})
        self.assertEqual(len(job["materials"]), 2)
        self.assertEqual([m["quantity_per_product"] for m in job["materials"]], [10, 15])
        self.catalog_request("patch", f"/production-jobs/{job['id']}/status", {"status": "reserved"}, status=400)
        self.assertEqual(self.catalog_request("get", f"/materials/{common['id']}")["reserved_qty"], 0)
        self.catalog_request("put", f"/production-jobs/{job['id']}", {"quantity": 1})
        self.catalog_request("patch", f"/production-jobs/{job['id']}/status", {"status": "reserved"})
        self.assertEqual(self.catalog_request("get", f"/materials/{common['id']}")["reserved_qty"], 25)
        self.catalog_request("patch", f"/production-jobs/{job['id']}/status", {"status": "in_progress"})
        material = self.catalog_request("get", f"/materials/{common['id']}")
        self.assertEqual((material["stock_quantity"], material["reserved_qty"]), (15, 0))

    def test_variant_delete_checks_stock_and_order_history(self):
        product = self.catalog_request("post", "/products", {"name": "Variant deletion"})
        variant = self.catalog_request("post", "/products/variants", {"product_id": product["id"], "name": "Stocked variant", "stock_quantity": 3})
        self.catalog_request("delete", f"/products/variants/{variant['id']}", status=409)
        self.catalog_request("delete", f"/products/{product['id']}", status=409)
        self.catalog_request("put", f"/products/variants/{variant['id']}", {"stock_quantity": 0})
        order = self.catalog_request("post", "/orders", {"date": "2026-10-22", "order_lines": [
            {"product_id": product["id"], "variant_id": variant["id"], "quantity": 1, "unit_price": 100}]})
        self.catalog_request("delete", f"/products/variants/{variant['id']}", status=409)
        self.catalog_request("delete", f"/orders/{order['id']}")
        self.catalog_request("delete", f"/products/variants/{variant['id']}")
        self.catalog_request("delete", f"/products/variants/{variant['id']}", status=404)

    def test_customer_fields_and_paid_order_flags_round_trip(self):
        customer = self.catalog_request("post", "/customers", {"name": "Customer fields", "notes": "Keep this note", "tags": ["VIP"]})
        loaded = self.catalog_request("get", f"/customers/{customer['id']}")
        self.assertEqual((loaded["notes"], loaded["tags"]), ("Keep this note", ["VIP"]))
        self.catalog_request("put", f"/customers/{customer['id']}", {"name": "Customer fields", "notes": "Updated", "tags": []})
        self.assertEqual(self.catalog_request("get", f"/customers/{customer['id']}")["tags"], [])
        product = self.catalog_request("post", "/products", {"name": "Paid order guard"})
        order = self.catalog_request("post", "/orders", {"date": "2026-10-22", "customer_id": customer["id"],
            "payment_status": "paid", "maker_user_id": self.user_id,
            "order_lines": [{"product_id": product["id"], "quantity": 1, "unit_price": 100}]})
        self.assertEqual(order["payment_status"], "paid")
        self.catalog_request("delete", f"/orders/{order['id']}", status=409)
        self.catalog_request("get", "/customers/summary")

    def test_issue_delete_removes_comments_and_category_in_use_is_kept(self):
        from sqlmodel import Session, select
        from config.database import engine
        from models.issue import IssueTable, IssueCommentTable
        category = self.catalog_request("post", "/categories", {"name": "Category deletion guard"})
        product = self.catalog_request("post", "/products", {"name": "Issue deletion", "categories": [category["id"]]})
        self.catalog_request("delete", f"/categories/{category['id']}", status=409)
        with Session(engine) as session:
            issue = IssueTable(product_id=product["id"], description="Disposable issue")
            session.add(issue)
            session.commit()
            session.refresh(issue)
            issue_id = issue.id
            session.add(IssueCommentTable(issue_id=issue_id, user_id=self.user_id, content="Disposable comment"))
            session.commit()
        self.catalog_request("delete", f"/products/{product['id']}", status=409)
        self.catalog_request("delete", f"/issues/{issue_id}")
        with Session(engine) as session:
            self.assertEqual(session.exec(select(IssueCommentTable).where(IssueCommentTable.issue_id == issue_id)).all(), [])
        self.catalog_request("delete", f"/products/{product['id']}")
        self.catalog_request("delete", f"/categories/{category['id']}")


if __name__ == "__main__":
    unittest.main()
