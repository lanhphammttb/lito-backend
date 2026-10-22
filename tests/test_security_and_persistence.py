import os
import sys
import tempfile
import unittest
from pathlib import Path

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

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)
        from config.database import close_mongo_connection, engine
        close_mongo_connection()
        engine.dispose()
        cls.temp_dir.cleanup()

    def test_internal_products_requires_auth(self):
        response = self.client.get("/products")
        self.assertEqual(response.status_code, 401)

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

    def test_ai_route_requires_auth(self):
        response = self.client.post("/ai/analyze", json={"prompt": "hello"})
        self.assertEqual(response.status_code, 401)

    def test_business_planning_routes_require_auth(self):
        for method, path in (
            ("get", "/ideas"),
            ("post", "/ideas"),
            ("get", "/experiments"),
            ("post", "/experiments"),
            ("get", "/strategy/okrs"),
            ("post", "/strategy/okrs"),
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


if __name__ == "__main__":
    unittest.main()
