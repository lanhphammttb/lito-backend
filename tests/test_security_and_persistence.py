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
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
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


if __name__ == "__main__":
    unittest.main()
