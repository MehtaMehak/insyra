import hashlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import main
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    from backend import main  # type: ignore
    from fastapi.testclient import TestClient  # type: ignore


class DemoReadOnlyApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.original_approvals_file = main.APPROVALS_FILE
        self.temp_dir = tempfile.TemporaryDirectory()
        main.APPROVALS_FILE = Path(self.temp_dir.name) / "approvals.json"
        self.env_patch = patch.dict(os.environ, {"DEMO_READ_ONLY": "true"}, clear=False)
        self.env_patch.start()
        os.environ.pop("DEMO_READ_ONLY", None)
        os.environ["DEMO_READ_ONLY"] = "true"

    def tearDown(self):
        main.APPROVALS_FILE = self.original_approvals_file
        self.temp_dir.cleanup()
        self.env_patch.stop()

    def test_state_changing_operations_are_blocked(self):
        upload_response = self.client.post(
            "/api/reviews/upload",
            files={"file": ("reviews.csv", io.BytesIO(b"date,review,rating\n2024-01-01,Review,5\n"), "text/csv")},
        )
        self.assertEqual(upload_response.status_code, 403)
        self.assertIn("read-only demo", upload_response.json()["detail"].lower())

        create_response = self.client.post("/api/approvals", json={"title": "Blocked", "snapshot": {}})
        self.assertEqual(create_response.status_code, 403)
        self.assertIn("read-only demo", create_response.json()["detail"].lower())

        approval_id = "blocked-approval"
        approve_response = self.client.post(f"/api/approvals/{approval_id}/approve")
        self.assertEqual(approve_response.status_code, 403)
        self.assertIn("read-only demo", approve_response.json()["detail"].lower())

        reject_response = self.client.post(f"/api/approvals/{approval_id}/reject")
        self.assertEqual(reject_response.status_code, 403)
        self.assertIn("read-only demo", reject_response.json()["detail"].lower())

    def test_read_only_operations_remain_available(self):
        for path in ["/", "/health", "/api/approvals", "/api/weekly-pulse", "/api/fee-explainer"]:
            response = self.client.get(path)
            self.assertNotEqual(response.status_code, 403, path)
            self.assertLess(response.status_code, 500, path)

    def test_flag_is_false_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEMO_READ_ONLY", None)
            self.assertFalse(main.is_demo_read_only())


class DemoReadOnlyReportTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.written_paths = [
            Path(__file__).resolve().parent / "data" / "weekly_pulse.md",
            Path(__file__).resolve().parent / "data" / "fee_explainer.json",
        ]
        self.original_hashes = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.written_paths
            if path.is_file()
        }
        self.env_patch = patch.dict(os.environ, {"DEMO_READ_ONLY": "true"}, clear=False)
        self.env_patch.start()
        os.environ["DEMO_READ_ONLY"] = "true"

    def tearDown(self):
        self.env_patch.stop()

    def test_weekly_pulse_reads_committed_report_without_generation(self):
        with patch("main.generate_weekly_pulse") as generate_pulse:
            response = self.client.get("/api/weekly-pulse")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            for field in (
                "report_date",
                "report",
                "word_count",
                "top_themes",
                "verified_quotes",
                "fee_observation",
                "recommended_actions",
            ):
                self.assertIn(field, body)
            generate_pulse.assert_not_called()

    def test_fee_explainer_reads_committed_data_without_generation(self):
        with patch("main.generate_fee_explainer_json") as generate_fee:
            response = self.client.get("/api/fee-explainer")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertIn("title", body)
            self.assertIn("sources", body)
            generate_fee.assert_not_called()

    def test_demo_read_only_does_not_modify_report_files(self):
        self.client.get("/api/weekly-pulse")
        self.client.get("/api/fee-explainer")
        for path, expected_hash in self.original_hashes.items():
            self.assertTrue(path.is_file(), path)
            actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(actual_hash, expected_hash, path)


if __name__ == "__main__":
    unittest.main()
