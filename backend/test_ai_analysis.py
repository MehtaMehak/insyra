import json
import unittest
from unittest.mock import MagicMock

try:
    from services.ai_analysis import (
        EvidenceGroundedReviewAnalyzer,
        analyze_reviews,
        detect_fee_confusion,
        AIAnalysisError,
    )
except ImportError:  # pragma: no cover
    from ai_analysis import (  # type: ignore
        EvidenceGroundedReviewAnalyzer,
        analyze_reviews,
        detect_fee_confusion,
        AIAnalysisError,
    )


def records():
    return [
        {
            "date": "2026-10-01",
            "review": "The brokerage fees are too high and hidden charges are bad.",
            "rating": "1",
            "source": "r1",
        },
        {
            "date": "2026-10-02",
            "review": "I like the app, but AMC deduction was confusing.",
            "rating": "2",
            "source": "r2",
        },
        {
            "date": "2026-10-03",
            "review": "Great mutual fund experience overall.",
            "rating": "5",
            "source": "r3",
        },
    ]


class AIAnalysisTests(unittest.TestCase):
    def _mock_client(self, payload):
        client = MagicMock()
        response = MagicMock()
        response.content = json.dumps(payload)
        client.chat_completion.return_value = response
        return client

    def test_themes_are_limited_to_five(self):
        payload = {
            "summary": "Summary",
            "themes": [
                {"theme": f"Theme {i}", "description": f"Desc {i}", "sentiment": "mixed"}
                for i in range(8)
            ],
            "quotes": [],
            "fee_confusion_summary": "Fees",
        }
        result = analyze_reviews(records(), groq_client=self._mock_client(payload))
        self.assertLessEqual(len(result["themes"]), 5)
        self.assertEqual(result["themes"][0]["theme"], "Theme 0")

    def test_quotes_are_verified_and_limited_to_three(self):
        payload = {
            "summary": "Summary",
            "themes": [],
            "quotes": ["hidden charges are bad.", "This quote is fabricated.", "overall."],
            "fee_confusion_summary": "",
        }
        result = analyze_reviews(records(), groq_client=self._mock_client(payload))
        self.assertEqual(len(result["verified_quotes"]), 2)
        self.assertEqual(result["verified_quotes"][0]["quote"], "hidden charges are bad.")
        self.assertIs(result["quotes"], result["verified_quotes"])

    def test_fee_confusion_detection_reports_candidates(self):
        fee = detect_fee_confusion(records())
        self.assertTrue(fee["detected"])
        self.assertEqual(fee["candidate_count"], 2)
        self.assertGreaterEqual(fee["unique_candidate_texts"], 1)
        self.assertIn("matched_terms", fee["candidates"][0])

    def test_invalid_json_raises_ai_analysis_error(self):
        client = MagicMock()
        response = MagicMock()
        response.content = "not json"
        client.chat_completion.return_value = response
        with self.assertRaises(AIAnalysisError):
            analyze_reviews(records(), groq_client=client)

    def test_verify_quotes_method(self):
        analyzer = EvidenceGroundedReviewAnalyzer()
        verified = analyzer.verify_quotes(records(), ["Great mutual fund experience", "missing"])
        self.assertEqual(len(verified), 1)
        self.assertEqual(verified[0]["source"], "r3")

    def test_no_groq_call_until_analyze(self):
        client = MagicMock()
        analyzer = EvidenceGroundedReviewAnalyzer(client=client)
        self.assertEqual(client.chat_completion.call_count, 0)
        payload = {"summary": "ok", "themes": [], "quotes": [], "fee_confusion_summary": ""}
        client.chat_completion.return_value = MagicMock(content=__import__("json").dumps(payload))
        analyzer.analyze(records())
        self.assertEqual(client.chat_completion.call_count, 1)


if __name__ == "__main__":
    unittest.main()
