import json
import os
import tempfile
import unittest

try:
    import main
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    from backend import main  # type: ignore
    from fastapi.testclient import TestClient


class InsightsEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.original_path = main.INSIGHTS_FILE

    def tearDown(self):
        main.INSIGHTS_FILE = self.original_path

    def test_get_insights_returns_saved_analysis(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "ai_analysis.json")
            data = {
                "summary": "Summary",
                "review_count": 300,
                "themes": [{"theme": "Fees", "description": "Desc", "sentiment": "negative"}],
                "verified_quotes": [
                    {
                        "quote": "Example quote",
                        "date": "2026-10-01",
                        "rating": "1",
                        "source": "https://example.test/review",
                    }
                ],
                "fee_confusion": {"detected": True, "candidate_count": 2},
            }
            with open(path, "w", encoding="utf-8") as file:
                json.dump(data, file)
            main.INSIGHTS_FILE = type(self.original_path)(path)

            response = self.client.get("/api/insights")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["review_count"], 300)
        self.assertEqual(body["themes"][0]["theme"], "Fees")

    def test_get_insights_returns_404_when_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "missing.json")
            main.INSIGHTS_FILE = type(self.original_path)(path)

            response = self.client.get("/api/insights")

        self.assertEqual(response.status_code, 404)
        self.assertIn("generated", response.json()["detail"])

    def test_get_insights_returns_500_for_invalid_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "invalid.json")
            with open(path, "w", encoding="utf-8") as file:
                file.write("{not valid json")
            main.INSIGHTS_FILE = type(self.original_path)(path)

            response = self.client.get("/api/insights")

        self.assertEqual(response.status_code, 500)


if __name__ == "__main__":
    unittest.main()
