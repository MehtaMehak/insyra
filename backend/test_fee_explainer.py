import json
import os
import tempfile
import unittest

try:
    import main
    from fastapi.testclient import TestClient
    from services.fee_explainer import (
        build_fee_explainer,
        build_fee_explainer_json,
        generate_fee_explainer,
        generate_fee_explainer_json,
    )
except ImportError:  # pragma: no cover
    import main as main  # type: ignore
    from fastapi.testclient import TestClient
    from fee_explainer import (  # type: ignore
        build_fee_explainer,
        build_fee_explainer_json,
        generate_fee_explainer,
        generate_fee_explainer_json,
    )


class FeeExplainerTests(unittest.TestCase):
    def test_no_network_and_deterministic_output(self):
        first = build_fee_explainer()
        second = build_fee_explainer()
        self.assertEqual(first, second)
        self.assertIn("groww.in/pricing", first)
        self.assertIn("not confirmed complaints", first.lower())
        self.assertIn("Customer sentiment is provided only as review context", first)

    def test_generator_writes_output(self):
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "fee_explainer.md")
            content = generate_fee_explainer(output_path=type(__import__("pathlib").Path(path))(path))
            self.assertTrue(os.path.exists(path))
            self.assertEqual(content, open(path, encoding="utf-8").read())


class FeeExplainerApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def test_structured_json_contract(self):
        data = build_fee_explainer_json()
        self.assertLessEqual(len(data["explanation_bullets"]), 6)
        self.assertGreaterEqual(len(data["official_source_urls"]), 2)
        self.assertEqual(data["last_checked_date"], "2026-10-14")
        for bullet in data["explanation_bullets"]:
            self.assertTrue(bullet["text"])
            self.assertGreaterEqual(len(bullet["supporting_sources"]), 1)
        self.assertIn("not confirmed complaints", data["customer_context"].lower())

    def test_markdown_and_json_are_consistent(self):
        markdown = build_fee_explainer()
        data = build_fee_explainer_json()
        source_urls = [source["url"] for source in json.load(open("data/fee_sources.json", encoding="utf-8"))["official_sources"]]
        for url in data["official_source_urls"]:
            self.assertIn(url, markdown)
        self.assertEqual(data["official_source_urls"], source_urls)

    def test_api_returns_structured_fee_explainer(self):
        response = self.client.get("/api/fee-explainer")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["title"], "Groww Fee Explainer")
        self.assertLessEqual(len(body["explanation_bullets"]), 6)
        self.assertGreaterEqual(len(body["official_source_urls"]), 2)
        for bullet in body["explanation_bullets"]:
            self.assertGreaterEqual(len(bullet["supporting_sources"]), 1)

    def test_generated_json_file_exists(self):
        with open("data/fee_explainer.json", encoding="utf-8") as fee_file:
            data = json.load(fee_file)
        self.assertEqual(data["last_checked_date"], "2026-10-14")


    def test_supporting_sources_map_to_official_urls(self):
        data = build_fee_explainer_json()
        for bullet in data["explanation_bullets"]:
            for source_id in bullet["supporting_sources"]:
                self.assertIn(source_id, data["source_references"])
                self.assertTrue(data["source_references"][source_id].startswith("https://"))


if __name__ == "__main__":
    unittest.main()
