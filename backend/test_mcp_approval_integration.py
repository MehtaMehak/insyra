import os
import tempfile
import unittest
from pathlib import Path

try:
    import main
    from fastapi.testclient import TestClient
    from services.approval_ledger import ApprovalLedger, ApprovalLedgerError
    from services.mcp_client_adapter import (
        ALLOWED_MCP_TOOLS,
        get_approval_provider_mode,
        McpToolClient,
        McpToolNotAllowedError,
    )
except ImportError:  # pragma: no cover
    from backend import main  # type: ignore
    from fastapi.testclient import TestClient
    from backend.services.approval_ledger import (  # type: ignore
        ApprovalLedger,
        ApprovalLedgerError,
    )
    from backend.services.mcp_client_adapter import (  # type: ignore
        ALLOWED_MCP_TOOLS,
        get_approval_provider_mode,
        McpToolClient,
        McpToolNotAllowedError,
    )

BASE_SNAPSHOT = {
    "date": "2026-10-14",
    "top_themes": ["Fees"],
    "weekly_pulse": "Weekly Product Pulse report",
    "identified_fee_issue": "Potential fee confusion",
    "explanation_bullets": ["Compare final charge"],
    "source_links": ["https://groww.in/pricing/"],
}


class McpApprovalIntegrationUnitTests(unittest.TestCase):
    def make_temp_paths(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        base = Path(temp_dir.name)
        return base, base / "approvals.json", base / "notes", base / "drafts"

    def create_approval(self, ledger):
        return ledger.create_request(
            {
                "title": "MCP integration",
                "snapshot": BASE_SNAPSHOT,
            }
        )

    def test_local_mode_remains_default(self):
        self.assertEqual(get_approval_provider_mode({}), "local")

    def test_mcp_mode_validates_allowlist(self):
        tools = McpToolClient().list_tools()
        self.assertEqual(set(tools), ALLOWED_MCP_TOOLS)
        with self.assertRaises(McpToolNotAllowedError):
            McpToolClient().call_tool("send_email", {})

    def test_rejection_never_calls_mcp_tools(self):
        calls = {"count": 0}

        class CountingClient:
            def list_tools(self):
                return list(ALLOWED_MCP_TOOLS)

            def assert_only_allowed_tools(self):
                return None

            def call_tool(self, tool_name, arguments):
                calls["count"] += 1
                raise AssertionError("MCP tool should not be called")

        import services.mcp_client_adapter as adapter

        original = adapter.McpToolClient
        adapter.McpToolClient = CountingClient
        try:
            _, approvals_path, _, _ = self.make_temp_paths()
            ledger = ApprovalLedger(approvals_path)
            approval = self.create_approval(ledger)
            ledger.reject_request(approval["id"], reason="Rejected")
            self.assertEqual(calls["count"], 0)
            stored = ledger.get_request(approval["id"])
            self.assertEqual(stored["status"], "rejected")
            self.assertIn("execution", stored)
            self.assertEqual(stored["execution"].get("state"), "not_started")
        finally:
            adapter.McpToolClient = original

    def test_mcp_mode_records_tool_results(self):
        os.environ["APPROVAL_PROVIDER_MODE"] = "mcp_mock"
        try:
            _, approvals_path, _, _ = self.make_temp_paths()
            ledger = ApprovalLedger(approvals_path)
            approval = self.create_approval(ledger)
            approved = ledger.approve_request(
                approval["id"],
                execute_providers=True,
            )

            self.assertEqual(approved["execution"]["state"], "succeeded")
            self.assertEqual(approved["execution"]["provider_mode"], "mcp_mock")
            self.assertEqual(
                approved["execution"]["notes"]["tool"],
                "create_or_update_google_doc",
            )
            self.assertEqual(
                approved["execution"]["gmail_draft"]["tool"],
                "create_gmail_draft",
            )
            self.assertIsNotNone(approved["execution"]["notes"].get("artifact_id"))
            self.assertIsNotNone(approved["execution"]["gmail_draft"].get("artifact_id"))
            audit_events = [event["event"] for event in approved["audit_history"]]
            self.assertIn("execution", audit_events)
            execution_audit = [event for event in approved["audit_history"] if event["event"] == "execution"][-1]
            self.assertEqual(execution_audit["notes_tool"], "create_or_update_google_doc")
            self.assertEqual(execution_audit["gmail_draft_tool"], "create_gmail_draft")
        finally:
            os.environ.pop("APPROVAL_PROVIDER_MODE", None)

    def test_repeated_approval_does_not_duplicate_mcp_actions(self):
        os.environ["APPROVAL_PROVIDER_MODE"] = "mcp_mock"
        try:
            _, approvals_path, _, _ = self.make_temp_paths()
            ledger = ApprovalLedger(approvals_path)
            approval = self.create_approval(ledger)
            first = ledger.approve_request(approval["id"], execute_providers=True)
            self.assertEqual(first["execution"]["state"], "succeeded")

            with self.assertRaises(Exception):
                ledger.approve_request(approval["id"], execute_providers=True)

            stored = ledger.get_request(approval["id"])
            execution_audits = [e for e in stored["audit_history"] if e["event"] == "execution"]
            self.assertEqual(len(execution_audits), 1)
        finally:
            os.environ.pop("APPROVAL_PROVIDER_MODE", None)

    def test_mcp_failure_handling(self):
        os.environ["APPROVAL_PROVIDER_MODE"] = "mcp_mock"

        class FailingClient:
            def __init__(self, *args, **kwargs):
                pass

            def list_tools(self):
                return list(ALLOWED_MCP_TOOLS)

            def assert_only_allowed_tools(self):
                return None

            def call_tool(self, tool_name, arguments):
                raise RuntimeError("simulated MCP failure")

        import services.mcp_client_adapter as adapter

        original_client = adapter.McpToolClient
        adapter.McpToolClient = FailingClient
        try:
            _, approvals_path, _, _ = self.make_temp_paths()
            ledger = ApprovalLedger(approvals_path)
            approval = self.create_approval(ledger)
            approved = ledger.approve_request(approval["id"], execute_providers=True)
            self.assertEqual(approved["status"], "approved")
            self.assertIn(approved["execution"]["state"], {"failed", "partial"})
            self.assertEqual(approved["execution"]["notes"]["status"], "failed")
            self.assertEqual(approved["execution"]["gmail_draft"]["status"], "failed")
            self.assertIn("simulated MCP failure", approved["execution"]["notes"]["error"])
        finally:
            adapter.McpToolClient = original_client
            os.environ.pop("APPROVAL_PROVIDER_MODE", None)


class McpApprovalIntegrationApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.original_path = main.APPROVALS_FILE

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name) / "approvals.json"
        main.APPROVALS_FILE = self.temp_path
        os.environ["APPROVAL_PROVIDER_MODE"] = "mcp_mock"
        os.environ.setdefault("MCP_SERVER_PATH", str(Path(__file__).resolve().parents[1] / "mcp_test_server.py"))

    def tearDown(self):
        main.APPROVALS_FILE = self.original_path
        os.environ.pop("APPROVAL_PROVIDER_MODE", None)
        os.environ.pop("MCP_SERVER_PATH", None)
        self.temp_dir.cleanup()

    def create_valid_approval(self):
        response = self.client.post(
            "/api/approvals",
            json={"title": "MCP API", "snapshot": BASE_SNAPSHOT},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["id"]

    def test_api_mcp_mode_creates_artifacts(self):
        approval_id = self.create_valid_approval()
        response = self.client.post(
            f"/api/approvals/{approval_id}/approve",
            json={"reason": "Approved for MCP"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["execution"]["provider_mode"], "mcp_mock")
        self.assertEqual(body["execution"]["state"], "succeeded")
        self.assertEqual(body["execution"]["notes"]["tool"], "create_or_update_google_doc")
        self.assertEqual(body["execution"]["gmail_draft"]["tool"], "create_gmail_draft")
        self.assertIsNotNone(body["execution"]["notes"].get("artifact_id"))
        self.assertIsNotNone(body["execution"]["gmail_draft"].get("artifact_id"))

    def test_api_rejection_blocks_mcp_calls(self):
        approval_id = self.create_valid_approval()
        response = self.client.post(
            f"/api/approvals/{approval_id}/reject",
            json={"reason": "Rejected"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "rejected")
        if "execution" in body:
            self.assertEqual(body["execution"].get("state"), "not_started")

    def test_api_repeated_approval_does_not_duplicate(self):
        approval_id = self.create_valid_approval()
        first = self.client.post(f"/api/approvals/{approval_id}/approve")
        second = self.client.post(f"/api/approvals/{approval_id}/approve")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)


if __name__ == "__main__":
    unittest.main()
