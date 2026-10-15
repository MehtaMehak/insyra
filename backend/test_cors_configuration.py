import os
import unittest
from unittest.mock import patch

try:
    import main
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    from backend import main  # type: ignore
    from fastapi.testclient import TestClient  # type: ignore


class CorsConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_default_origins_are_allowed(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CORS_ALLOWED_ORIGINS", None)
            response = self.client.get("/", headers={"Origin": "http://localhost:5173"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.headers.get("access-control-allow-origin"),
                "http://localhost:5173",
            )

    def test_default_second_origin_is_allowed(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CORS_ALLOWED_ORIGINS", None)
            response = self.client.get("/", headers={"Origin": "http://127.0.0.1:5173"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.headers.get("access-control-allow-origin"),
                "http://127.0.0.1:5173",
            )

    def test_disallowed_origin_is_rejected(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CORS_ALLOWED_ORIGINS", None)
            response = self.client.get("/", headers={"Origin": "https://evil.example"})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("access-control-allow-origin", response.headers)

    def test_env_origins_are_trimmed_and_used(self):
        with patch.dict(
            os.environ,
            {"CORS_ALLOWED_ORIGINS": " https://app.example.com , http://localhost:5173 "},
            clear=False,
        ):
            allowed = self.client.get("/", headers={"Origin": "https://app.example.com"})
            self.assertEqual(allowed.headers.get("access-control-allow-origin"), "https://app.example.com")

            disallowed = self.client.get("/", headers={"Origin": "https://evil.example"})
            self.assertNotIn("access-control-allow-origin", disallowed.headers)

    def test_wildcard_is_rejected(self):
        with patch.dict(os.environ, {"CORS_ALLOWED_ORIGINS": "*"}, clear=False):
            response = self.client.get("/", headers={"Origin": "https://evil.example"})
            self.assertNotIn("access-control-allow-origin", response.headers)

    def test_preflight_for_allowed_origin(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CORS_ALLOWED_ORIGINS", None)
            response = self.client.options(
                "/api/approvals",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.headers.get("access-control-allow-origin"),
                "http://localhost:5173",
            )
            self.assertIn("POST", response.headers.get("access-control-allow-methods", ""))


if __name__ == "__main__":
    unittest.main()
