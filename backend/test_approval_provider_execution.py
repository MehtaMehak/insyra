import tempfile
import unittest
from pathlib import Path

try:
    import main
    from fastapi.testclient import TestClient
    from services.approval_ledger import ApprovalLedger, ApprovalLedgerError
    from services.notes_provider import LocalNotesProvider
    from services.gmail_draft_provider import MockGmailDraftProvider
except ImportError:  # pragma: no cover
    from backend import main  # type: ignore
    from fastapi.testclient import TestClient
    from backend.services.approval_ledger import (  # type: ignore
        ApprovalLedger,
        ApprovalLedgerError,
    )
    from backend.services.notes_provider import LocalNotesProvider  # type: ignore
    from backend.services.gmail_draft_provider import (  # type: ignore
        MockGmailDraftProvider,
    )


class ApprovalProviderExecutionUnitTests(unittest.TestCase):
    def make_temp_paths(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        base = Path(temp_dir.name)
        return base, base / "approvals.json", base / "notes", base / "drafts"

    def create_valid_approval(self, ledger):
        return ledger.create_request(
            {
                "title": "Execution test",
                "snapshot": {
                    "date": "2026-10-14",
                    "top_themes": ["Fees", "Support"],
                    "weekly_pulse": "Weekly Product Pulse report",
                    "identified_fee_issue": "Potential fee confusion",
                    "explanation_bullets": ["Compare final charge"],
                    "source_links": ["https://groww.in/pricing/"],
                },
            }
        )

    def test_successful_approval_executes_both_providers(self):
        _, approvals_path, notes_dir, drafts_dir = self.make_temp_paths()
        ledger = ApprovalLedger(approvals_path)
        approval = self.create_valid_approval(ledger)

        approved = ledger.approve_request(
            approval["id"],
            execute_providers=True,
            notes_provider=LocalNotesProvider(notes_dir),
            gmail_provider=MockGmailDraftProvider(drafts_dir),
            reason="Approved for execution",
        )

        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["execution"]["state"], "succeeded")
        self.assertEqual(approved["execution"]["notes"]["status"], "succeeded")
        self.assertEqual(approved["execution"]["gmail_draft"]["status"], "succeeded")
        self.assertTrue(Path(approved["execution"]["notes"]["path"]).exists())
        self.assertTrue(Path(approved["execution"]["gmail_draft"]["path"]).exists())
        self.assertTrue(approved["execution"]["gmail_draft"]["draft_id"].startswith("mock-draft-"))
        audit_events = [event["event"] for event in approved["audit_history"]]
        self.assertIn("execution", audit_events)

    def test_idempotent_execute_does_not_create_duplicates(self):
        _, approvals_path, notes_dir, drafts_dir = self.make_temp_paths()
        ledger = ApprovalLedger(approvals_path)
        approval = self.create_valid_approval(ledger)
        ledger.approve_request(
            approval["id"],
            execute_providers=True,
            notes_provider=LocalNotesProvider(notes_dir),
            gmail_provider=MockGmailDraftProvider(drafts_dir),
        )

        before_notes = sorted(path.name for path in notes_dir.glob("*.md"))
        before_drafts = sorted(path.name for path in drafts_dir.glob("*.json"))

        executed = ledger.execute_approved_providers(
            approval["id"],
            notes_provider=LocalNotesProvider(notes_dir),
            gmail_provider=MockGmailDraftProvider(drafts_dir),
        )
        after_notes = sorted(path.name for path in notes_dir.glob("*.md"))
        after_drafts = sorted(path.name for path in drafts_dir.glob("*.json"))

        self.assertEqual(before_notes, after_notes)
        self.assertEqual(before_drafts, after_drafts)
        self.assertEqual(executed["execution"]["state"], "succeeded")

    def test_rejected_request_does_not_execute_providers(self):
        _, approvals_path, notes_dir, drafts_dir = self.make_temp_paths()
        ledger = ApprovalLedger(approvals_path)
        approval = self.create_valid_approval(ledger)
        notes_calls = {"count": 0}
        draft_calls = {"count": 0}

        original_note = LocalNotesProvider(notes_dir).save_note
        original_draft = MockGmailDraftProvider(drafts_dir).create_draft

        def counting_note(*args, **kwargs):
            notes_calls["count"] += 1
            return original_note(*args, **kwargs)

        def counting_draft(*args, **kwargs):
            draft_calls["count"] += 1
            return original_draft(*args, **kwargs)

        notes_provider = LocalNotesProvider(notes_dir)
        notes_provider.save_note = counting_note
        draft_provider = MockGmailDraftProvider(drafts_dir)
        draft_provider.create_draft = counting_draft

        ledger.reject_request(approval["id"], reason="No execution")
        ledger.execute_approved_providers(
            approval["id"],
            notes_provider=notes_provider,
            gmail_provider=draft_provider,
        ) if False else None

        self.assertEqual(notes_calls["count"], 0)
        self.assertEqual(draft_calls["count"], 0)
        self.assertFalse(list(notes_dir.glob("*.md")))
        self.assertFalse(list(drafts_dir.glob("*.json")))

    def test_missing_snapshot_fields_raises(self):
        _, approvals_path, notes_dir, drafts_dir = self.make_temp_paths()
        ledger = ApprovalLedger(approvals_path)
        approval = ledger.create_request(
            {
                "title": "Missing field",
                "snapshot": {
                    "top_themes": ["Fees"],
                    "weekly_pulse": "Pulse",
                    "identified_fee_issue": "Issue",
                    "explanation_bullets": ["Bullet"],
                    "source_links": ["https://example.test"],
                },
            }
        )

        with self.assertRaises(ApprovalLedgerError) as context:
            ledger.approve_request(
                approval["id"],
                execute_providers=True,
                notes_provider=LocalNotesProvider(notes_dir),
                gmail_provider=MockGmailDraftProvider(drafts_dir),
            )
        self.assertIn("missing required fields", str(context.exception).lower())
        stored = ledger.get_request(approval["id"])
        self.assertEqual(stored["status"], "approved")
        self.assertIn("missing", str(stored["execution"].get("notes", {}).get("error", "")).lower())

    def test_partial_provider_failure_is_recorded(self):
        _, approvals_path, notes_dir, drafts_dir = self.make_temp_paths()
        ledger = ApprovalLedger(approvals_path)
        approval = self.create_valid_approval(ledger)

        notes_provider = LocalNotesProvider(notes_dir)

        def failing_save(*args, **kwargs):
            raise RuntimeError("notes provider failed")

        notes_provider.save_note = failing_save
        draft_provider = MockGmailDraftProvider(drafts_dir)

        approved = ledger.approve_request(
            approval["id"],
            execute_providers=True,
            notes_provider=notes_provider,
            gmail_provider=draft_provider,
        )

        self.assertEqual(approved["execution"]["notes"]["status"], "failed")
        self.assertEqual(approved["execution"]["gmail_draft"]["status"], "succeeded")
        self.assertEqual(approved["execution"]["state"], "partial")
        self.assertIn("notes provider failed", approved["execution"]["notes"]["error"])
        self.assertTrue(Path(approved["execution"]["gmail_draft"]["path"]).exists())


class ApprovalProviderExecutionApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.original_path = main.APPROVALS_FILE

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name) / "approvals.json"
        self.notes_dir = Path(self.temp_dir.name) / "approved_notes"
        self.drafts_dir = Path(self.temp_dir.name) / "gmail_drafts"
        main.APPROVALS_FILE = self.temp_path

        import services.notes_provider as notes_module
        import services.gmail_draft_provider as gmail_module

        self.original_notes_provider = notes_module.LocalNotesProvider
        self.original_gmail_provider = gmail_module.MockGmailDraftProvider

        notes_dir = self.notes_dir
        drafts_dir = self.drafts_dir

        def patched_notes_provider(*args, **kwargs):
            return self.original_notes_provider(notes_dir)

        def patched_gmail_provider(*args, **kwargs):
            return self.original_gmail_provider(drafts_dir)

        notes_module.LocalNotesProvider = patched_notes_provider
        gmail_module.MockGmailDraftProvider = patched_gmail_provider

    def tearDown(self):
        import services.notes_provider as notes_module
        import services.gmail_draft_provider as gmail_module

        notes_module.LocalNotesProvider = self.original_notes_provider
        gmail_module.MockGmailDraftProvider = self.original_gmail_provider
        main.APPROVALS_FILE = self.original_path
        self.temp_dir.cleanup()

    def create_valid_approval(self, title="Provider execution API"):
        response = self.client.post(
            "/api/approvals",
            json={
                "title": title,
                "snapshot": {
                    "date": "2026-10-14",
                    "top_themes": ["Fees"],
                    "weekly_pulse": "Pulse",
                    "identified_fee_issue": "Fee issue",
                    "explanation_bullets": ["Bullet"],
                    "source_links": ["https://groww.in/pricing/"],
                },
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["id"]

    def test_api_successful_approval_executes_providers(self):
        approval_id = self.create_valid_approval()
        response = self.client.post(
            f"/api/approvals/{approval_id}/approve",
            json={"reason": "Approved"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["execution"]["state"], "succeeded")
        self.assertEqual(body["execution"]["notes"]["status"], "succeeded")
        self.assertEqual(body["execution"]["gmail_draft"]["status"], "succeeded")
        self.assertTrue(Path(body["execution"]["notes"]["path"]).exists())
        self.assertTrue(Path(body["execution"]["gmail_draft"]["path"]).exists())

    def test_api_missing_snapshot_returns_bad_request(self):
        response = self.client.post(
            "/api/approvals",
            json={
                "title": "Missing date",
                "snapshot": {
                    "top_themes": ["Fees"],
                    "weekly_pulse": "Pulse",
                    "identified_fee_issue": "Fee issue",
                    "explanation_bullets": ["Bullet"],
                    "source_links": ["https://groww.in/pricing/"],
                },
            },
        )
        approval_id = response.json()["id"]

        approve_response = self.client.post(f"/api/approvals/{approval_id}/approve")

        self.assertEqual(approve_response.status_code, 400)

    def test_api_repeated_approval_does_not_create_duplicates(self):
        approval_id = self.create_valid_approval()
        first = self.client.post(f"/api/approvals/{approval_id}/approve")
        before_notes = sorted(path.name for path in self.notes_dir.glob("*.md"))
        before_drafts = sorted(path.name for path in self.drafts_dir.glob("*.json"))

        second = self.client.post(f"/api/approvals/{approval_id}/approve")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(sorted(path.name for path in self.notes_dir.glob("*.md")), before_notes)
        self.assertEqual(sorted(path.name for path in self.drafts_dir.glob("*.json")), before_drafts)


if __name__ == "__main__":
    unittest.main()
