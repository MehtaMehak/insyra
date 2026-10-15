import json
import os
import tempfile
import unittest

try:
    import main
    from services.weekly_pulse import WeeklyPulseError, generate_weekly_pulse
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    from backend import main  # type: ignore
    from backend.services.weekly_pulse import WeeklyPulseError, generate_weekly_pulse  # type: ignore
    from fastapi.testclient import TestClient


class WeeklyPulseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def test_generated_report_word_count_and_sections(self):
        result = generate_weekly_pulse()
        report = result.report
        required = [
            "# Weekly Product Pulse",
            "Report date:",
            "Scope:",
            "## Top 3 themes",
            "## Verified customer quotes",
            "## Fee-confusion observation",
            "## Recommended actions",
        ]
        for heading in required:
            self.assertIn(heading, report)
        self.assertLessEqual(result.word_count, 250)
        self.assertEqual(result.word_count, len(report.split()))
        self.assertEqual(len(result.recommended_actions), 3)
        self.assertEqual(len(result.supported_themes), 3)
        self.assertEqual(len(result.verified_quotes), 3)

    def test_quotes_preserved_verbatim_with_sources(self):
        result = generate_weekly_pulse()
        with open("data/ai_analysis.json", encoding="utf-8") as analysis_file:
            analysis = json.load(analysis_file)
        source_lookup = {
            quote["quote"]: quote["source"]
            for quote in analysis["verified_quotes"][:3]
        }
        for metadata in result.verified_quotes:
            self.assertIn(metadata["quote"], source_lookup)
            self.assertEqual(metadata["source"], source_lookup[metadata["quote"]])

    def test_keyword_candidates_are_not_claimed_as_confirmed(self):
        result = generate_weekly_pulse()
        observation = result.fee_observation.lower()
        self.assertIn("candidates", observation)
        self.assertIn("not confirmed complaints", observation)

    def test_api_returns_report(self):
        response = self.client.get("/api/weekly-pulse")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("report", body)
        self.assertIn("# Weekly Product Pulse", body["report"])
        self.assertLessEqual(body["word_count"], 250)
        self.assertEqual(len(body["verified_quotes"]), 3)

    def test_missing_analysis_returns_error(self):
        original = main.generate_weekly_pulse
        try:
            main.generate_weekly_pulse = lambda **kwargs: (_ for _ in ()).throw(
                WeeklyPulseError("AI analysis file does not exist: missing.json")
            )
            response = self.client.get("/api/weekly-pulse")
            self.assertEqual(response.status_code, 404)
        finally:
            main.generate_weekly_pulse = original


if __name__ == "__main__":
    unittest.main()
