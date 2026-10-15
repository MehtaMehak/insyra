import tempfile
import unittest
from pathlib import Path

try:
    import main
    from services.notes_provider import LocalNotesProvider
    from services.gmail_draft_provider import (
        MockGmailDraftProvider,
        REQUIRED_SUBJECT_PREFIX,
    )
except ImportError:  # pragma: no cover
    from backend import main  # type: ignore
    from notes_provider import LocalNotesProvider  # type: ignore
    from gmail_draft_provider import (  # type: ignore
        MockGmailDraftProvider,
        REQUIRED_SUBJECT_PREFIX,
    )
from services.approval_ledger import ApprovalLedger


class NotesProviderTests(unittest.TestCase):
    def test_local_notes_file_structure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            notes_dir = Path(temp_dir) / "approved_notes"
            provider = LocalNotesProvider(notes_dir)

            path = provider.save_note(
                date="2026-10-14",
                top_themes=["Fees", "Support", "Withdrawals"],
                weekly_pulse="Weekly Product Pulse report text",
                identified_fee_issue="Possible fee confusion",
                explanation_bullets=["Compare final charge", "Check STT/GST"],
                source_links=["https://groww.in/pricing/"],
            )

            self.assertTrue(Path(path).exists())
            content = Path(path).read_text(encoding="utf-8")
            self.assertIn("# Approved Product Insights", content)
            self.assertIn("Date: 2026-10-14", content)
            self.assertIn("## Top Themes", content)
            self.assertIn("Fees", content)
            self.assertIn("## Weekly Product Pulse", content)
            self.assertIn("Weekly Product Pulse report text", content)
            self.assertIn("## Identified Fee Issue", content)
            self.assertIn("Possible fee confusion", content)
            self.assertIn("## Explanation Bullets", content)
            self.assertIn("Compare final charge", content)
            self.assertIn("## Source Links", content)
            self.assertIn("https://groww.in/pricing/", content)

    def test_notes_provider_accepts_mapping_and_aliases(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            notes_dir = Path(temp_dir) / "approved_notes"
            provider = LocalNotesProvider({"notes_dir": notes_dir})

            path = provider.create_note(
                {
                    "report_date": "2026-10-15",
                    "themes": ["Fees"],
                    "weekly_pulse": "Pulse",
                    "fee_issue": "Fee issue",
                    "bullets": ["Bullet"],
                    "sources": ["https://example.test"],
                }
            )

            content = Path(path).read_text(encoding="utf-8")
            self.assertIn("Date: 2026-10-15", content)
            self.assertIn("Fee issue", content)


class GmailDraftProviderTests(unittest.TestCase):
    def make_provider(self, temp_dir):
        drafts_dir = Path(temp_dir) / "gmail_drafts"
        return MockGmailDraftProvider(drafts_dir), drafts_dir

    def test_draft_subject_and_body(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            provider, drafts_dir = self.make_provider(temp_dir)
            pulse = "Weekly Product Pulse report text"
            fee = "Factual fee explainer text"

            draft = provider.create_draft(
                subject="Weekly Pulse",
                body=pulse,
                weekly_pulse=pulse,
                fee_explainer=fee,
                date="2026-10-14",
                top_themes=["Fees"],
                identified_fee_issue="Fee confusion",
                explanation_bullets=["Compare charges"],
                source_links=["https://groww.in/pricing/"],
            )

            self.assertTrue(Path(draft).exists())
            self.assertTrue(draft.get("subject").startswith(REQUIRED_SUBJECT_PREFIX))
            stored = Path(draft).read_text(encoding="utf-8")
            self.assertIn("Weekly Product Pulse", stored)
            self.assertIn(pulse, stored)
            self.assertIn("Factual Fee Explainer", stored)
            self.assertIn(fee, stored)
            self.assertIn(REQUIRED_SUBJECT_PREFIX, draft.get("subject"))

    def test_mock_provider_has_no_send_capability(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            provider, _ = self.make_provider(temp_dir)

            self.assertFalse(hasattr(provider, "send"))
            self.assertFalse(hasattr(provider, "send_email"))
            self.assertFalse(hasattr(provider, "send_message"))
            forbidden = [
                name for name in dir(provider)
                if "send" in name.lower() and not name.startswith("_")
            ]
            self.assertEqual(forbidden, [])

    def test_draft_is_local_artifact_not_real_email(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            provider, drafts_dir = self.make_provider(temp_dir)
            draft = provider.create_draft(
                subject="Weekly Pulse",
                body="Body",
                weekly_pulse="Pulse",
                fee_explainer="Fee",
            )
            stored = Path(draft).read_text(encoding="utf-8")

            self.assertIn('"status": "draft"', stored)
            self.assertIn('"sent": false', stored.lower())
            self.assertTrue(list(drafts_dir.glob("*.json")))


class ProviderNonExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_temp = tempfile.TemporaryDirectory()
        cls.temp_path = Path(cls.client_temp.name) / "approvals.json"
        cls.original_path = main.APPROVALS_FILE
        main.APPROVALS_FILE = cls.temp_path

    @classmethod
    def tearDownClass(cls):
        main.APPROVALS_FILE = cls.original_path
        cls.client_temp.cleanup()

    def test_creating_approval_does_not_execute_providers(self):
        notes_dir = Path(self.client_temp.name) / "approved_notes"
        drafts_dir = Path(self.client_temp.name) / "gmail_drafts"
        LocalNotesProvider(notes_dir)
        MockGmailDraftProvider(drafts_dir)

        ledger = ApprovalLedger(self.temp_path)
        approval = ledger.create_request({"title": "No automatic action"})

        self.assertEqual(approval["status"], "pending")
        self.assertFalse(notes_dir.exists())
        self.assertFalse(drafts_dir.exists())


if __name__ == "__main__":
    unittest.main()
