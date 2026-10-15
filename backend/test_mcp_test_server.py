import asyncio
import json
import sys
import unittest
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

SERVER_PATH = Path(__file__).resolve().with_name("mcp_test_server.py")


class SafeMcpServerTests(unittest.TestCase):
    def _run_client(self, callback):
        async def main():
            server_params = StdioServerParameters(
                command=sys.executable,
                args=[str(SERVER_PATH)],
            )
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await callback(session)

        return asyncio.run(main())

    def test_lists_exactly_two_safe_tools(self):
        async def callback(session):
            result = await session.list_tools()
            return {tool.name for tool in result.tools}

        names = self._run_client(callback)
        self.assertEqual(
            names,
            {"create_gmail_draft", "create_or_update_google_doc"},
        )

    def test_calls_mock_gmail_draft_tool(self):
        async def callback(session):
            result = await session.call_tool(
                "create_gmail_draft",
                {
                    "subject": "Test subject",
                    "body": "Test body",
                    "to": ["person@example.com"],
                },
            )
            return result

        result = self._run_client(callback)
        self.assertFalse(result.is_error)
        text = result.content[0].text if result.content else ""
        payload = json.loads(text)
        self.assertEqual(payload["tool"], "create_gmail_draft")
        self.assertEqual(payload["draft_id"], "mock-mcp-draft-1")
        self.assertEqual(payload["status"], "draft")
        self.assertFalse(payload["sent"])

    def test_calls_mock_google_doc_tool(self):
        async def callback(session):
            result = await session.call_tool(
                "create_or_update_google_doc",
                {
                    "title": "Test doc",
                    "content": "Test content",
                },
            )
            return result

        result = self._run_client(callback)
        self.assertFalse(result.is_error)
        text = result.content[0].text if result.content else ""
        payload = json.loads(text)
        self.assertEqual(payload["tool"], "create_or_update_google_doc")
        self.assertEqual(payload["document_id"], "mock-mcp-doc-1")
        self.assertIn("docs.mock.example", payload["url"])


if __name__ == "__main__":
    unittest.main()
