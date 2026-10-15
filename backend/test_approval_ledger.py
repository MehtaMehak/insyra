import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

try:
    import main
    from fastapi.testclient import TestClient
    from services.approval_ledger import ApprovalLedger
except ImportError:  # pragma: no cover
    from backend import main  # type: ignore
    from fastapi.testclient import TestClient
    from backend.services.approval_ledger import ApprovalLedger  # type: ignore


class ApprovalLedgerUnitTests(unittest.TestCase):
    def make_temporary_ledger(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        return Path(temp_dir.name) / "approvals.json", temp_dir

    def test_create_request_is_pending_with_audit_and_id(self):
        path, _ = self.make_temporary_ledger()
        ledger = ApprovalLedger(path)

        approval = ledger.create_request({"title": "Weekly pulse"})

        self.assertEqual(approval["status"], "pending")
        self.assertTrue(approval["id"])
        self.assertEqual(approval["id"], approval["approval_id"])
        self.assertEqual(approval["id"], approval["request_id"])
        self.assertIsInstance(approval["audit_history"], list)
        self.assertEqual(approval["audit_history"][0]["event"], "created")

    def test_persistence_across_ledger_instances(self):
        path, _ = self.make_temporary_ledger()
        first_ledger = ApprovalLedger(path)
        approval = first_ledger.create_request({"title": "Persist me"})

        second_ledger = ApprovalLedger(path)
        loaded = second_ledger.list_requests()

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["id"], approval["id"])
        self.assertEqual(loaded[0]["status"], "pending")

    def test_snapshot_is_immutable_to_source_mutation(self):
        path, _ = self.make_temporary_ledger()
        weekly_pulse = {"report": "original report", "score": 1}
        fee_explainer = {"title": "Fee Explainer", "bullets": [{"text": "x"}]}
        ledger = ApprovalLedger(path)

        approval = ledger.create_request(
            {"title": "Immutable snapshot"},
            weekly_pulse=weekly_pulse,
            fee_explainer=fee_explainer,
        )

        weekly_pulse["report"] = "changed"
        weekly_pulse["new"] = "mutated"
        fee_explainer["title"] = "changed title"
        fee_explainer["bullets"][0]["text"] = "changed"

        stored = ApprovalLedger(path).get_request(approval["id"])
        self.assertEqual(stored["weekly_pulse"]["report"], "original report")
        self.assertNotIn("new", stored["weekly_pulse"])
        self.assertEqual(stored["fee_explainer"]["title"], "Fee Explainer")
        self.assertEqual(stored["fee_explainer"]["bullets"][0]["text"], "x")

    def test_audit_history_is_persisted(self):
        path, _ = self.make_temporary_ledger()
        ledger = ApprovalLedger(path)
        approval = ledger.create_request({"title": "Audit"})

        reloaded = ApprovalLedger(path).get_request(approval["id"])
        self.assertEqual(reloaded["audit_history"][0]["event"], "created")
        self.assertEqual(reloaded["audit"][0]["event"], "created")
        self.assertEqual(reloaded["history"][0]["event"], "created")


class ApprovalLedgerApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.original_path = main.APPROVALS_FILE

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name) / "approvals.json"
        main.APPROVALS_FILE = self.temp_path

    def tearDown(self):
        main.APPROVALS_FILE = self.original_path
        self.temp_dir.cleanup()

    def test_post_creates_pending_request(self):
        response = self.client.post("/api/approvals", json={"title": "API request"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "pending")
        self.assertTrue(body["id"])
        self.assertTrue(Path(body["id"]).name)

    def test_get_lists_created_requests(self):
        create_response = self.client.post("/api/approvals", json={"title": "List me"})
        created_id = create_response.json()["id"]

        list_response = self.client.get("/api/approvals")

        self.assertEqual(list_response.status_code, 200)
        body = list_response.json()
        self.assertIn("approvals", body)
        approvals = body["approvals"]
        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0]["id"], created_id)
        self.assertEqual(approvals[0]["status"], "pending")
        self.assertEqual(body["items"][0]["id"], created_id)
        self.assertEqual(body["requests"][0]["id"], created_id)

    def test_empty_body_creates_pending_request(self):
        response = self.client.post("/api/approvals")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "pending")


class ApprovalDecisionUnitTests(unittest.TestCase):
    def make_temporary_ledger(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        return Path(temp_dir.name) / "approvals.json"

    def create_pending_request(self, path):
        ledger = ApprovalLedger(path)
        return ledger.create_request(
            {"title": "Decision test"},
            weekly_pulse={"report": "immutable pulse"},
            fee_explainer={"title": "immutable fee"},
        )

    def test_approve_pending_request_records_decision_and_audit(self):
        path = self.make_temporary_ledger()
        approval = self.create_pending_request(path)
        ledger = ApprovalLedger(path)

        approved = ledger.approve_request(
            approval["id"],
            {"reason": "Looks good", "decided_by": "reviewer"},
        )

        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["decision"]["status"], "approved")
        self.assertEqual(approved["decision"]["reason"], "Looks good")
        self.assertEqual(approved["decided_by"], "reviewer")
        self.assertEqual(approved["audit_history"][-1]["event"], "approved")
        self.assertTrue(approved["audit_history"][-1]["timestamp"])

    def test_reject_pending_request_records_decision_and_audit(self):
        path = self.make_temporary_ledger()
        approval = self.create_pending_request(path)
        ledger = ApprovalLedger(path)

        rejected = ledger.reject_request(
            approval["id"],
            reason="Needs revision",
            decided_by="reviewer",
        )

        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["decision"]["status"], "rejected")
        self.assertEqual(rejected["reason"], "Needs revision")
        self.assertEqual(rejected["audit_history"][-1]["event"], "rejected")

    def test_repeated_approval_does_not_execute_twice(self):
        path = self.make_temporary_ledger()
        approval = self.create_pending_request(path)
        ledger = ApprovalLedger(path)

        ledger.approve_request(approval["id"])

        with self.assertRaises(Exception):
            ledger.approve_request(approval["id"])
        stored = ledger.get_request(approval["id"])
        self.assertEqual(stored["status"], "approved")
        self.assertEqual(
            len([event for event in stored["audit_history"] if event["event"] == "approved"]),
            1,
        )

    def test_repeated_rejection_does_not_execute_twice(self):
        path = self.make_temporary_ledger()
        approval = self.create_pending_request(path)
        ledger = ApprovalLedger(path)

        ledger.reject_request(approval["id"])

        with self.assertRaises(Exception):
            ledger.reject_request(approval["id"])
        stored = ledger.get_request(approval["id"])
        self.assertEqual(stored["status"], "rejected")
        self.assertEqual(
            len([event for event in stored["audit_history"] if event["event"] == "rejected"]),
            1,
        )

    def test_approved_request_cannot_be_rejected(self):
        path = self.make_temporary_ledger()
        approval = self.create_pending_request(path)
        ledger = ApprovalLedger(path)

        ledger.approve_request(approval["id"])

        with self.assertRaises(Exception):
            ledger.reject_request(approval["id"])

    def test_snapshots_preserved_through_approval(self):
        path = self.make_temporary_ledger()
        approval = self.create_pending_request(path)
        ledger = ApprovalLedger(path)

        approved = ledger.approve_request(approval["id"])

        self.assertEqual(approved["weekly_pulse"]["report"], "immutable pulse")
        self.assertEqual(approved["fee_explainer"]["title"], "immutable fee")
        self.assertEqual(approved["snapshot"]["weekly_pulse"]["report"], "immutable pulse")
        self.assertEqual(approved["snapshot"]["fee_explainer"]["title"], "immutable fee")

    def test_decision_for_nonexistent_request_raises(self):
        path = self.make_temporary_ledger()
        ledger = ApprovalLedger(path)

        with self.assertRaises(Exception) as context:
            ledger.approve_request("missing-id")
        self.assertIn("does not exist", str(context.exception))

        with self.assertRaises(Exception) as context:
            ledger.reject_request("missing-id")
        self.assertIn("does not exist", str(context.exception))


class ApprovalDecisionApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.original_path = main.APPROVALS_FILE

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name) / "approvals.json"
        main.APPROVALS_FILE = self.temp_path

    def tearDown(self):
        main.APPROVALS_FILE = self.original_path
        self.temp_dir.cleanup()

    def create_request(self, title="API decision"):
        response = self.client.post("/api/approvals", json={"title": title})
        self.assertEqual(response.status_code, 200)
        return response.json()["id"]

    def test_api_approve_pending_request(self):
        approval_id = self.create_request()
        response = self.client.post(
            f"/api/approvals/{approval_id}/approve",
            json={"reason": "Approved", "decided_by": "api-reviewer"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "approved")
        self.assertEqual(body["decision"]["reason"], "Approved")

    def test_api_reject_pending_request(self):
        approval_id = self.create_request()
        response = self.client.post(
            f"/api/approvals/{approval_id}/reject",
            json={"reason": "Rejected"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "rejected")

    def test_api_repeated_approval_returns_conflict(self):
        approval_id = self.create_request()
        first = self.client.post(f"/api/approvals/{approval_id}/approve")
        second = self.client.post(f"/api/approvals/{approval_id}/approve")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)

    def test_api_repeated_rejection_returns_conflict(self):
        approval_id = self.create_request()
        first = self.client.post(f"/api/approvals/{approval_id}/reject")
        second = self.client.post(f"/api/approvals/{approval_id}/reject")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)

    def test_api_transition_after_approval_returns_conflict(self):
        approval_id = self.create_request()
        self.client.post(f"/api/approvals/{approval_id}/approve")
        response = self.client.post(f"/api/approvals/{approval_id}/reject")

        self.assertEqual(response.status_code, 409)

    def test_api_nonexistent_request_returns_not_found(self):
        approve_response = self.client.post("/api/approvals/missing-id/approve")
        reject_response = self.client.post("/api/approvals/missing-id/reject")

        self.assertEqual(approve_response.status_code, 404)
        self.assertEqual(reject_response.status_code, 404)

    def test_api_empty_decision_body_works(self):
        approval_id = self.create_request()
        response = self.client.post(f"/api/approvals/{approval_id}/approve")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "approved")


if __name__ == "__main__":
    unittest.main()
