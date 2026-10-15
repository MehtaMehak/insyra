"""MCP client adapter for approval-gated mock MCP execution.

Only two MCP tools are allowed:
- create_gmail_draft
- create_or_update_google_doc

The adapter supports local stdio communication with backend/mcp_test_server.py
by default. It intentionally does not implement any send-email capability.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from services.notes_provider import ProviderArtifact

DEFAULT_MCP_SERVER_PATH = (
    Path(__file__).resolve().parents[1] / "mcp_test_server.py"
)

ALLOWED_MCP_TOOLS = frozenset(
    {
        "create_gmail_draft",
        "create_or_update_google_doc",
    }
)

ALLOWED_PROVIDER_MODES = frozenset({"local", "mcp_mock"})


class McpToolNotAllowedError(ValueError):
    """Raised when an MCP tool is not in the approval allowlist."""


class McpClientError(RuntimeError):
    """Raised when an MCP client call fails."""


class McpToolClient:
    """Minimal synchronous MCP stdio client with an allowlist."""

    def __init__(
        self,
        server_path: Any = None,
        *,
        command: str | None = None,
        args: list[str] | None = None,
        timeout: float = 30.0,
    ):
        self.server_path = Path(server_path) if server_path is not None else DEFAULT_MCP_SERVER_PATH
        self.command = command or sys.executable
        self.args = list(args) if args is not None else [str(self.server_path)]
        self.timeout = timeout

    def _server_params(self):
        from mcp.client.stdio import StdioServerParameters

        return StdioServerParameters(command=self.command, args=self.args)

    async def _list_tools_async(self) -> list[str]:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        async with stdio_client(self._server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [tool.name for tool in result.tools]

    async def _call_tool_async(self, tool_name: str, arguments: Mapping[str, Any]):
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        if tool_name not in ALLOWED_MCP_TOOLS:
            raise McpToolNotAllowedError(f"MCP tool is not allowed: {tool_name}")

        async with stdio_client(self._server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                available = {tool.name for tool in (await session.list_tools()).tools}
                if tool_name not in available:
                    raise McpClientError(f"MCP tool is not available on server: {tool_name}")
                result = await session.call_tool(tool_name, dict(arguments))
                if getattr(result, "is_error", False):
                    text = self._result_text(result)
                    raise McpClientError(text or f"MCP tool failed: {tool_name}")
                return self._extract_result(result)

    @staticmethod
    def _result_text(result: Any) -> str:
        content = getattr(result, "content", None)
        if not content:
            return ""
        parts = []
        for item in content:
            text = getattr(item, "text", None)
            if text is not None:
                parts.append(str(text))
        return "\n".join(parts)

    @staticmethod
    def _extract_result(result: Any) -> dict[str, Any]:
        structured = getattr(result, "structuredContent", None)
        if isinstance(structured, Mapping):
            return dict(structured)
        text = McpToolClient._result_text(result)
        if text:
            try:
                parsed = json.loads(text)
                if isinstance(parsed, Mapping):
                    return dict(parsed)
            except (TypeError, ValueError):
                pass
            return {"text": text}
        return {}

    def list_tools(self) -> list[str]:
        return asyncio.run(self._list_tools_async())

    def call_tool(self, tool_name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        try:
            return asyncio.run(self._call_tool_async(tool_name, arguments or {}))
        except RuntimeError as exc:
            if "cannot be called when another loop is running" in str(exc):
                raise McpClientError("MCP client cannot run inside an active event loop.") from exc
            raise

    def allowed_tools(self) -> set[str]:
        return set(ALLOWED_MCP_TOOLS)

    def assert_only_allowed_tools(self) -> None:
        available = set(self.list_tools())
        if not available.issubset(ALLOWED_MCP_TOOLS):
            raise McpToolNotAllowedError(
                "MCP server exposes tools outside the allowlist: "
                + ", ".join(sorted(available - ALLOWED_MCP_TOOLS))
            )


def get_approval_provider_mode(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    mode = str(source.get("APPROVAL_PROVIDER_MODE", "local")).strip().lower()
    if mode not in ALLOWED_PROVIDER_MODES:
        raise ValueError(
            "APPROVAL_PROVIDER_MODE must be one of: "
            + ", ".join(sorted(ALLOWED_PROVIDER_MODES))
        )
    return mode


def create_default_mcp_client(server_path: Any = None) -> McpToolClient:
    return McpToolClient(server_path=server_path)


class McpNotesProvider:
    """Approval provider backed by the allowlisted Google Doc MCP tool."""

    def __init__(self, client: McpToolClient | None = None):
        self.client = client or create_default_mcp_client()

    def save_note(
        self,
        *,
        date: Any = None,
        top_themes: Any = None,
        weekly_pulse: Any = None,
        identified_fee_issue: Any = None,
        explanation_bullets: Any = None,
        source_links: Any = None,
        filename: Any = None,
        **kwargs: Any,
    ) -> ProviderArtifact:
        title = f"Approved Product Insights - {date or 'undated'}"
        content = _render_note_content(
            date=date,
            top_themes=top_themes,
            weekly_pulse=weekly_pulse,
            identified_fee_issue=identified_fee_issue,
            explanation_bullets=explanation_bullets,
            source_links=source_links,
        )
        result = self.client.call_tool(
            "create_or_update_google_doc",
            {"title": title, "content": content},
        )
        artifact_id = result.get("document_id")
        uri = result.get("url") or f"mcp://google-doc/{artifact_id}"
        artifact = ProviderArtifact(
            uri,
            provider="mcp-mock",
            tool="create_or_update_google_doc",
            artifact_id=artifact_id,
            result=result,
        )
        artifact._tool_result = result
        return artifact

    create_note = save_note
    write_note = save_note
    save = save_note
    create = save_note
    save_notes = save_note


class McpGmailDraftProvider:
    """Approval provider backed by the allowlisted Gmail draft MCP tool."""

    REQUIRED_SUBJECT_PREFIX = "Weekly Product Pulse + Customer Clarification —"

    def __init__(self, client: McpToolClient | None = None):
        self.client = client or create_default_mcp_client()

    def create_draft(
        self,
        *,
        subject: Any = None,
        body: Any = None,
        to: Any = None,
        recipient: Any = None,
        recipients: Any = None,
        weekly_pulse: Any = None,
        fee_explainer: Any = None,
        date: Any = None,
        top_themes: Any = None,
        identified_fee_issue: Any = None,
        explanation_bullets: Any = None,
        source_links: Any = None,
        **kwargs: Any,
    ) -> ProviderArtifact:
        resolved_subject = _normalize_subject(subject, date)
        resolved_body = _render_draft_body(
            body=body,
            weekly_pulse=weekly_pulse,
            fee_explainer=fee_explainer,
            date=date,
            top_themes=top_themes,
            identified_fee_issue=identified_fee_issue,
            explanation_bullets=explanation_bullets,
            source_links=source_links,
        )
        resolved_recipients = _render_recipients(to, recipient, recipients, kwargs)
        result = self.client.call_tool(
            "create_gmail_draft",
            {
                "subject": resolved_subject,
                "body": resolved_body,
                "to": resolved_recipients,
            },
        )
        artifact_id = result.get("draft_id")
        uri = f"mcp://gmail-draft/{artifact_id}"
        artifact = ProviderArtifact(
            uri,
            provider="mcp-mock",
            tool="create_gmail_draft",
            artifact_id=artifact_id,
            subject=resolved_subject,
            result=result,
        )
        artifact._tool_result = result
        return artifact

    create = create_draft
    draft = create_draft
    save_draft = create_draft
    write_draft = create_draft


def create_default_approval_providers(mode: str | None = None):
    resolved_mode = get_approval_provider_mode() if mode is None else str(mode).strip().lower()
    if resolved_mode == "local":
        from services.notes_provider import LocalNotesProvider
        from services.gmail_draft_provider import MockGmailDraftProvider

        return LocalNotesProvider(), MockGmailDraftProvider()
    if resolved_mode == "mcp_mock":
        client = create_default_mcp_client()
        client.assert_only_allowed_tools()
        return McpNotesProvider(client), McpGmailDraftProvider(client)
    raise ValueError(f"Unsupported approval provider mode: {resolved_mode}")


def call_allowlisted_mcp_tool(client: McpToolClient, tool_name: str, arguments: Any = None):
    if tool_name not in ALLOWED_MCP_TOOLS:
        raise McpToolNotAllowedError(f"MCP tool is not allowed: {tool_name}")
    return client.call_tool(tool_name, arguments or {})


def _render_note_content(**fields: Any) -> str:
    lines = ["# Approved Product Insights", ""]
    if fields.get("date"):
        lines.append(f"Date: {_value(fields.get('date'))}")
        lines.append("")
    themes = _as_list(fields.get("top_themes"))
    if themes:
        lines.append("## Top Themes")
        lines.append("")
        for theme in themes:
            lines.append(f"- {_value(theme)}")
        lines.append("")
    if fields.get("weekly_pulse"):
        lines.append("## Weekly Product Pulse")
        lines.append("")
        lines.append(_value(fields.get("weekly_pulse")))
        lines.append("")
    if fields.get("identified_fee_issue"):
        lines.append("## Identified Fee Issue")
        lines.append("")
        lines.append(_value(fields.get("identified_fee_issue")))
        lines.append("")
    bullets = _as_list(fields.get("explanation_bullets"))
    if bullets:
        lines.append("## Explanation Bullets")
        lines.append("")
        for bullet in bullets:
            lines.append(f"- {_value(bullet)}")
        lines.append("")
    links = _as_list(fields.get("source_links"))
    if links:
        lines.append("## Source Links")
        lines.append("")
        for link in links:
            lines.append(f"- {_value(link)}")
        lines.append("")
    return "\n".join(lines)


def _render_draft_body(
    *,
    body: Any = None,
    weekly_pulse: Any = None,
    fee_explainer: Any = None,
    date: Any = None,
    top_themes: Any = None,
    identified_fee_issue: Any = None,
    explanation_bullets: Any = None,
    source_links: Any = None,
) -> str:
    if body is not None:
        base = str(body)
    else:
        base = ""
    if weekly_pulse is not None and "Weekly Product Pulse" not in base:
        base = _append(base, "## Weekly Product Pulse\n\n" + _value(weekly_pulse))
    if fee_explainer is not None and "Fee Explainer" not in base:
        base = _append(base, "## Factual Fee Explainer\n\n" + _value(fee_explainer))
    if identified_fee_issue and "Identified Fee Issue" not in base:
        base = _append(base, "## Identified Fee Issue\n\n" + _value(identified_fee_issue))
    if top_themes and "Top Themes" not in base:
        base = _append(
            base,
            "## Top Themes\n\n" + "\n".join(f"- {_value(item)}" for item in _as_list(top_themes)),
        )
    if explanation_bullets and "Explanation Bullets" not in base:
        base = _append(
            base,
            "## Explanation Bullets\n\n"
            + "\n".join(f"- {_value(item)}" for item in _as_list(explanation_bullets)),
        )
    if source_links and "Source Links" not in base:
        base = _append(
            base,
            "## Source Links\n\n" + "\n".join(f"- {_value(item)}" for item in _as_list(source_links)),
        )
    if date and "Date:" not in base:
        base = f"Date: {_value(date)}\n\n" + base
    return base.strip()


def _normalize_subject(subject: Any, date: Any = None) -> str:
    prefix = "Weekly Product Pulse + Customer Clarification —"
    raw = "" if subject is None else str(subject).strip()
    if not raw:
        raw = f"{prefix} Product Update"
    if not raw.startswith(prefix):
        raw = f"{prefix} {raw}".strip()
    return raw


def _render_recipients(to: Any, recipient: Any, recipients: Any, kwargs: Mapping[str, Any]) -> list[str]:
    values = []
    for item in (to, recipient, recipients):
        if item is not None:
            values.extend(_as_list(item))
    for key in ("to_list", "email", "emails", "recipient_list"):
        if kwargs.get(key) is not None:
            values.extend(_as_list(kwargs[key]))
    return [str(item).strip() for item in values if str(item).strip()]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _value(value: Any) -> str:
    if isinstance(value, Mapping):
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value)
    return str(value)


import urllib.error
import urllib.request

N8N_WEBHOOK_TIMEOUT_SECONDS = 5.0


def _sanitize_n8n_error(exc: Exception) -> str:
    detail = str(exc).strip()
    if len(detail) > 300:
        detail = detail[:300] + "..."
    if not detail:
        detail = type(exc).__name__
    return f"{type(exc).__name__}: {detail}"


def post_approved_webhook(
    approval_id: Any,
    document_text: Any = "",
    email_subject: Any = "",
    email_body: Any = "",
    *,
    environ: Mapping[str, str] | None = None,
    timeout: float = N8N_WEBHOOK_TIMEOUT_SECONDS,
    **kwargs: Any,
) -> dict[str, Any]:
    """POST approved report payload to an optional n8n webhook.

    Credentials come only from the process environment (or ``environ`` in
    tests). No values are returned, logged, or printed.
    """
    env = os.environ if environ is None else environ
    url = str(env.get("N8N_WEBHOOK_URL", "")).strip()
    token = str(env.get("N8N_WEBHOOK_TOKEN", "")).strip()

    if not url:
        return {
            "status": "skipped",
            "error": "N8N_WEBHOOK_URL is not configured.",
        }
    if not token:
        return {
            "status": "skipped",
            "error": "N8N_WEBHOOK_TOKEN is not configured.",
        }

    payload = {
        "approval_id": str(approval_id),
        "document_text": "" if document_text is None else str(document_text),
        "email_subject": "" if email_subject is None else str(email_subject),
        "email_body": "" if email_body is None else str(email_body),
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-Insyra-Token": token,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status_code = getattr(response, "status", None)
            if status_code is None:
                status_code = response.getcode() if hasattr(response, "getcode") else None
            return {
                "status": "succeeded",
                "status_code": status_code,
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        return {
            "status": "failed",
            "status_code": getattr(exc, "code", None),
            "error": _sanitize_n8n_error(exc),
        }
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return {
            "status": "failed",
            "error": _sanitize_n8n_error(exc),
        }


# Compatibility aliases for alternate caller names.
send_approved_webhook = post_approved_webhook
send_to_n8n = post_approved_webhook
post_to_n8n = post_approved_webhook
send_n8n_webhook = post_approved_webhook
post_n8n_webhook = post_approved_webhook
notify_n8n = post_approved_webhook
call_n8n_webhook = post_approved_webhook
trigger_n8n_webhook = post_approved_webhook
send_approved_report_to_n8n = post_approved_webhook


def _append(base: str, text: str) -> str:
    if not base.strip():
        return text
    return base.rstrip() + "\n\n" + text


# Compatibility aliases.
McpClient = McpToolClient
McpStdioClient = McpToolClient
InsyraMcpClient = McpToolClient
McpApprovalClient = McpToolClient
McpProviderAdapter = McpToolClient
McpDocumentProvider = McpNotesProvider
McpNotesMcpProvider = McpNotesProvider

__all__ = [
    "ALLOWED_MCP_TOOLS",
    "ALLOWED_PROVIDER_MODES",
    "McpToolClient",
    "McpClient",
    "McpStdioClient",
    "InsyraMcpClient",
    "McpApprovalClient",
    "McpProviderAdapter",
    "McpNotesProvider",
    "McpDocumentProvider",
    "McpNotesMcpProvider",
    "McpGmailDraftProvider",
    "create_default_mcp_client",
    "create_default_approval_providers",
    "call_allowlisted_mcp_tool",
    "get_approval_provider_mode",
    "post_approved_webhook",
    "send_approved_webhook",
    "send_to_n8n",
    "post_to_n8n",
    "send_n8n_webhook",
    "post_n8n_webhook",
    "notify_n8n",
    "call_n8n_webhook",
    "trigger_n8n_webhook",
    "send_approved_report_to_n8n",
    "N8N_WEBHOOK_TIMEOUT_SECONDS",
    "McpToolNotAllowedError",
    "McpClientError",
]
