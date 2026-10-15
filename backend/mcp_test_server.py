"""Minimal safe MCP server for local development and tests.

This server exposes exactly two mock tools. Neither tool contacts Google or any
other external service. It exists only to validate MCP client/server wiring.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("insyra-safe-mock-mcp")


@mcp.tool()
def create_gmail_draft(
    subject: str,
    body: str,
    to: list[str] | None = None,
) -> dict:
    """Create a safe local mock Gmail draft. No email is sent."""
    recipients = to or []
    return {
        "provider": "safe-mock-mcp",
        "tool": "create_gmail_draft",
        "draft_id": "mock-mcp-draft-1",
        "subject": subject,
        "body_preview": body[:120],
        "recipients": recipients,
        "status": "draft",
        "sent": False,
    }


@mcp.tool()
def create_or_update_google_doc(
    title: str,
    content: str,
    document_id: str | None = None,
) -> dict:
    """Create or update a safe local mock Google Doc. No Google API is called."""
    return {
        "provider": "safe-mock-mcp",
        "tool": "create_or_update_google_doc",
        "document_id": document_id or "mock-mcp-doc-1",
        "title": title,
        "content_preview": content[:120],
        "updated": document_id is not None,
        "url": f"https://docs.mock.example/{document_id or 'mock-mcp-doc-1'}",
    }


if __name__ == "__main__":
    mcp.run()