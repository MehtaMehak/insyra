import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    from services.approval_ledger import (
    ApprovalLedger,
    ApprovalLedgerError,
    _build_n8n_document_text,
    _build_n8n_email_body,
)
    from services.mcp_client_adapter import (
        N8N_WEBHOOK_TIMEOUT_SECONDS,
        post_approved_webhook,
    )
    from services.notes_provider import LocalNotesProvider
    from services.gmail_draft_provider import MockGmailDraftProvider
except ImportError:  # pragma: no cover
    from approval_ledger import (  # type: ignore
        ApprovalLedger,
        ApprovalLedgerError,
        _build_n8n_document_text,
        _build_n8n_email_body,
    )
    from mcp_client_adapter import (  # type: ignore
        N8N_WEBHOOK_TIMEOUT_SECONDS,
        post_approved_webhook,
    )
    from notes_provider import LocalNotesProvider  # type: ignore
    from gmail_draft_provider import MockGmailDraftProvider  # type: ignore


class N8nWebhookHelperTests(unittest.TestCase):
    def _mock_response(self, status_code=202):
        response = MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.getcode.return_value = status_code
        response.status = status_code
        return response

    @patch("urllib.request.urlopen")
    def test_posts_exact_payload_and_header(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response(202)
        env = {
            "N8N_WEBHOOK_URL": "https://n8n.example.test/webhook/insyra",
            "N8N_WEBHOOK_TOKEN": "secret-token",
        }

        result = post_approved_webhook(
            "approval-123",
            "Approved document text",
            "Weekly Product Pulse + Customer Clarification — Product Update",
            "Email body text",
            environ=env,
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["status_code"], 202)
        self.assertEqual(mock_urlopen.call_count, 1)

        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, env["N8N_WEBHOOK_URL"])
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(request.get_header("X-insyra-token"), env["N8N_WEBHOOK_TOKEN"])

        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            payload,
            {
                "approval_id": "approval-123",
                "document_text": "Approved document text",
                "email_subject": "Weekly Product Pulse + Customer Clarification — Product Update",
                "email_body": "Email body text",
            },
        )
        self.assertEqual(mock_urlopen.call_args.kwargs["timeout"], N8N_WEBHOOK_TIMEOUT_SECONDS)

    @patch("urllib.request.urlopen")
    def test_missing_config_skips_without_http_call(self, mock_urlopen):
        result = post_approved_webhook("approval-123", environ={})

        self.assertEqual(result["status"], "skipped")
        mock_urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_http_error_is_sanitized(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://n8n.example.test/webhook/insyra",
            500,
            "server error",
            {},
            io.BytesIO(b"secret diagnostics"),
        )

        env = {
            "N8N_WEBHOOK_URL": "https://n8n.example.test/webhook/insyra",
            "N8N_WEBHOOK_TOKEN": "secret-token",
        }
        result = post_approved_webhook("approval-123", environ=env)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["status_code"], 500)
        self.assertNotIn("secret-token", str(result))
        self.assertNotIn("secret-token", result.get("error", ""))


class N8nWebhookLedgerTests(unittest.TestCase):
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

    @patch("urllib.request.urlopen")
    def test_missing_n8n_config_does_not_break_approval(self, mock_urlopen):
        _, approvals_path, notes_dir, drafts_dir = self.make_temp_paths()
        ledger = ApprovalLedger(approvals_path)
        approval = self.create_valid_approval(ledger)

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("N8N_WEBHOOK_URL", None)
            os.environ.pop("N8N_WEBHOOK_TOKEN", None)
            approved = ledger.approve_request(
                approval["id"],
                execute_providers=True,
                notes_provider=LocalNotesProvider(notes_dir),
                gmail_provider=MockGmailDraftProvider(drafts_dir),
            )

        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["execution"]["state"], "succeeded")
        self.assertEqual(approved["execution"]["n8n_webhook"]["status"], "skipped")
        mock_urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_approved_approval_calls_webhook_once(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response_for_success()
        _, approvals_path, notes_dir, drafts_dir = self.make_temp_paths()
        ledger = ApprovalLedger(approvals_path)
        approval = self.create_valid_approval(ledger)

        env = {
            "N8N_WEBHOOK_URL": "https://n8n.example.test/webhook/insyra",
            "N8N_WEBHOOK_TOKEN": "secret-token",
        }
        with patch.dict(os.environ, env, clear=False):
            approved = ledger.approve_request(
                approval["id"],
                execute_providers=True,
                notes_provider=LocalNotesProvider(notes_dir),
                gmail_provider=MockGmailDraftProvider(drafts_dir),
            )

        self.assertEqual(approved["execution"]["state"], "succeeded")
        self.assertEqual(approved["execution"]["n8n_webhook"]["status"], "succeeded")
        self.assertEqual(mock_urlopen.call_count, 1)
        payload = json.loads(mock_urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(payload["approval_id"], approval["id"])
        self.assertIn("document_text", payload)
        self.assertIn("email_subject", payload)
        self.assertIn("email_body", payload)

    @patch("urllib.request.urlopen")
    def test_webhook_failure_then_retry_calls_again(self, mock_urlopen):
        failing_response = None
        mock_urlopen.side_effect = [
            urllib.error.URLError("temporary failure"),
            self._mock_response_for_success(),
        ]
        _, approvals_path, notes_dir, drafts_dir = self.make_temp_paths()
        ledger = ApprovalLedger(approvals_path)
        approval = self.create_valid_approval(ledger)

        env = {
            "N8N_WEBHOOK_URL": "https://n8n.example.test/webhook/insyra",
            "N8N_WEBHOOK_TOKEN": "secret-token",
        }
        with patch.dict(os.environ, env, clear=False):
            failed = ledger.approve_request(
                approval["id"],
                execute_providers=True,
                notes_provider=LocalNotesProvider(notes_dir),
                gmail_provider=MockGmailDraftProvider(drafts_dir),
            )
            self.assertEqual(failed["execution"]["state"], "partial")
            self.assertEqual(failed["execution"]["n8n_webhook"]["status"], "failed")

            # notes and draft are already succeeded; only n8n should be retried.
            before_notes = sorted(path.name for path in notes_dir.glob("*.md"))
            before_drafts = sorted(path.name for path in drafts_dir.glob("*.json"))
            retried = ledger.execute_approved_providers(
                approval["id"],
                notes_provider=LocalNotesProvider(notes_dir),
                gmail_provider=MockGmailDraftProvider(drafts_dir),
            )
            self.assertEqual(sorted(path.name for path in notes_dir.glob("*.md")), before_notes)
            self.assertEqual(sorted(path.name for path in drafts_dir.glob("*.json")), before_drafts)
            self.assertEqual(retried["execution"]["n8n_webhook"]["status"], "succeeded")
            self.assertEqual(retried["execution"]["state"], "succeeded")
            self.assertEqual(mock_urlopen.call_count, 2)

            # Already succeeded; a later run must not call n8n again.
            before_calls = mock_urlopen.call_count
            final = ledger.execute_approved_providers(
                approval["id"],
                notes_provider=LocalNotesProvider(notes_dir),
                gmail_provider=MockGmailDraftProvider(drafts_dir),
            )
            self.assertEqual(mock_urlopen.call_count, before_calls)
            self.assertEqual(final["execution"]["n8n_webhook"]["status"], "succeeded")

    @patch("urllib.request.urlopen")
    def test_rejected_approval_does_not_call_webhook(self, mock_urlopen):
        _, approvals_path, notes_dir, drafts_dir = self.make_temp_paths()
        ledger = ApprovalLedger(approvals_path)
        approval = self.create_valid_approval(ledger)

        env = {
            "N8N_WEBHOOK_URL": "https://n8n.example.test/webhook/insyra",
            "N8N_WEBHOOK_TOKEN": "secret-token",
        }
        with patch.dict(os.environ, env, clear=False):
            ledger.reject_request(approval["id"], reason="No webhook")

            with self.assertRaises(ApprovalLedgerError):
                ledger.execute_approved_providers(
                    approval["id"],
                    notes_provider=LocalNotesProvider(notes_dir),
                    gmail_provider=MockGmailDraftProvider(drafts_dir),
                )

        mock_urlopen.assert_not_called()

    def _mock_response_for_success(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.getcode.return_value = 202
        response.status = 202
        return response


class N8nFormattingTests(unittest.TestCase):
    def test_document_text_is_plain_and_complete(self):
        snapshot = {
            "date": "2026-10-14",
            "top_themes": ["Fees", "Support"],
            "weekly_pulse": (
                "# Weekly Product Pulse\n\n"
                "## Verified customer quotes\n"
                '> "Highly misleading fees." - source: https://example.test/quote\n'
            ),
            "identified_fee_issue": "Potential fee confusion",
            "explanation_bullets": [f"Bullet {index}" for index in range(1, 8)],
            "source_links": ["https://groww.in/pricing/"],
        }

        text = _build_n8n_document_text(snapshot)

        for shorthand in ("#", "##", ">", "*", "`"):
            self.assertNotIn(shorthand, text)
        self.assertIn("Date: 2026-10-14", text)
        self.assertIn("1. Fees", text)
        self.assertIn("2. Support", text)
        self.assertIn("Highly misleading fees.", text)
        self.assertIn("Potential fee confusion", text)
        self.assertIn("1. Bullet 1", text)
        self.assertIn("6. Bullet 6", text)
        self.assertNotIn("7. Bullet 7", text)
        self.assertIn("https://groww.in/pricing/", text)

    def test_email_body_avoids_duplicate_fee_paragraph(self):
        fee_issue = "Potential fee confusion"
        snapshot = {
            "date": "2026-10-14",
            "top_themes": ["Fees"],
            "weekly_pulse": (
                "# Weekly Product Pulse\n\n"
                "## Fee-confusion observation\n"
                f"{fee_issue}\n"
            ),
            "identified_fee_issue": fee_issue,
            "explanation_bullets": ["Compare final charge"],
            "source_links": ["https://groww.in/pricing/"],
        }

        body = _build_n8n_email_body(snapshot)

        self.assertEqual(body.count(fee_issue), 1)
        for shorthand in ("#", "##", ">", "*", "`"):
            self.assertNotIn(shorthand, body)


if __name__ == "__main__":
    unittest.main()
