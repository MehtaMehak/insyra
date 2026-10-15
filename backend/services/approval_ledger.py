"""Local, approval-gated request ledger.

This module intentionally implements only local state management. It does not
connect to Gmail, Notes providers, MCP, or any external system. Every request
is stored with a unique ID, an initial ``pending`` status, an audit history,
and immutable snapshots of the current Weekly Product Pulse and Fee Explainer.
"""

from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from services import mcp_client_adapter
except ImportError:  # pragma: no cover - supports alternate test invocation
    import mcp_client_adapter  # type: ignore

try:  # pragma: no cover - supports alternate test invocation
    from services.weekly_pulse import generate_weekly_pulse
except ImportError:  # pragma: no cover
    from weekly_pulse import generate_weekly_pulse  # type: ignore

try:  # pragma: no cover
    from services.mcp_client_adapter import (
        _normalize_subject,
        _render_draft_body,
        _render_note_content,
    )
except ImportError:  # pragma: no cover
    from mcp_client_adapter import (  # type: ignore
        _normalize_subject,
        _render_draft_body,
        _render_note_content,
    )

try:  # pragma: no cover - supports alternate test invocation
    from services.fee_explainer import generate_fee_explainer_json
except ImportError:  # pragma: no cover
    from fee_explainer import generate_fee_explainer_json  # type: ignore


DEFAULT_STORAGE_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "approvals.json"
)


class ApprovalLedgerError(ValueError):
    """Raised when an approval ledger operation cannot be completed safely."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_path(value: Any) -> Path:
    return value if isinstance(value, Path) else Path(str(value))


def _load_records(storage_path: Path) -> list[dict[str, Any]]:
    storage_path = _coerce_path(storage_path)
    if not storage_path.is_file():
        return []
    try:
        with storage_path.open("r", encoding="utf-8") as ledger_file:
            data = json.load(ledger_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ApprovalLedgerError("Approval ledger is missing or invalid.") from exc
    if isinstance(data, Mapping):
        records = data.get("approvals", data.get("items", data.get("requests", [])))
    elif isinstance(data, list):
        records = data
    else:
        records = []
    if not isinstance(records, list):
        raise ApprovalLedgerError("Approval ledger has an invalid structure.")
    return [copy.deepcopy(record) for record in records if isinstance(record, Mapping)]


def _save_records(storage_path: Path, records: list[dict[str, Any]]) -> None:
    storage_path = _coerce_path(storage_path)
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = storage_path.with_suffix(storage_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as ledger_file:
        json.dump({"approvals": records}, ledger_file, ensure_ascii=False, indent=2)
        ledger_file.write("\n")
    temporary_path.replace(storage_path)


def _current_weekly_pulse() -> dict[str, Any]:
    result = generate_weekly_pulse()
    if hasattr(result, "as_dict"):
        return copy.deepcopy(result.as_dict())
    if isinstance(result, Mapping):
        return copy.deepcopy(dict(result))
    return {"report": str(result)}


def _current_fee_explainer() -> dict[str, Any]:
    data = generate_fee_explainer_json()
    if isinstance(data, Mapping):
        return copy.deepcopy(dict(data))
    return {"data": copy.deepcopy(data)}


def _build_snapshot(
    weekly_pulse: Any | None = None,
    fee_explainer: Any | None = None,
) -> dict[str, Any]:
    weekly_pulse_snapshot = (
        copy.deepcopy(weekly_pulse)
        if weekly_pulse is not None
        else _current_weekly_pulse()
    )
    fee_explainer_snapshot = (
        copy.deepcopy(fee_explainer)
        if fee_explainer is not None
        else _current_fee_explainer()
    )
    return {
        "weekly_pulse": weekly_pulse_snapshot,
        "fee_explainer": fee_explainer_snapshot,
    }


def _normalize_payload(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if isinstance(payload, Mapping):
        return copy.deepcopy(dict(payload))
    if isinstance(payload, str):
        return {"text": payload}
    return {"value": copy.deepcopy(payload)}


_REQUIRED_NOTE_SNAPSHOT_FIELDS = [
    "date",
    "top_themes",
    "weekly_pulse",
    "identified_fee_issue",
    "explanation_bullets",
    "source_links",
]

_NOTE_FIELD_ALIASES: dict[str, list[str]] = {
    "date": ["date", "report_date", "reportDate", "created_at"],
    "top_themes": ["top_themes", "topThemes", "themes", "supported_themes", "top_3_themes"],
    "weekly_pulse": ["weekly_pulse", "weeklyPulse", "pulse", "weekly_product_pulse", "report"],
    "identified_fee_issue": [
        "identified_fee_issue",
        "fee_issue",
        "feeIssue",
        "fee_observation",
        "feeObservation",
        "identifiedFeeIssue",
    ],
    "explanation_bullets": [
        "explanation_bullets",
        "explanationBullets",
        "bullets",
        "fee_bullets",
        "explanation",
    ],
    "source_links": [
        "source_links",
        "sourceLinks",
        "sources",
        "official_source_urls",
        "source_urls",
        "links",
    ],
}


def _has_note_snapshot_field(payload: Any) -> bool:
    if not isinstance(payload, Mapping):
        return False
    for source in (
        payload.get("snapshot") if isinstance(payload.get("snapshot"), Mapping) else None,
        payload.get("snapshots") if isinstance(payload.get("snapshots"), Mapping) else None,
        payload,
    ):
        if isinstance(source, Mapping):
            for field in _REQUIRED_NOTE_SNAPSHOT_FIELDS:
                if any(alias in source for alias in _NOTE_FIELD_ALIASES[field]):
                    return True
    return False


def _extract_note_fields(source: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(source, Mapping):
        return None
    result: dict[str, Any] = {}
    found = False
    for field in _REQUIRED_NOTE_SNAPSHOT_FIELDS:
        value = None
        alias_found = False
        for alias in _NOTE_FIELD_ALIASES[field]:
            if alias in source:
                value = source.get(alias)
                alias_found = True
                break
        if alias_found:
            found = True
        result[field] = copy.deepcopy(value) if value is not None else None
    return result if found else None


def _provided_note_snapshot(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    sources = []
    for key in ("snapshot", "snapshots"):
        if isinstance(payload.get(key), Mapping):
            sources.append(payload.get(key))
    sources.append(payload)
    for source in sources:
        fields = _extract_note_fields(source) if isinstance(source, Mapping) else None
        if fields is not None:
            return fields
    return None


def _default_note_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any] | None:
    weekly = snapshot.get("weekly_pulse") if isinstance(snapshot, Mapping) else None
    fee = snapshot.get("fee_explainer") if isinstance(snapshot, Mapping) else None
    weekly = weekly if isinstance(weekly, Mapping) else {}
    fee = fee if isinstance(fee, Mapping) else {}

    date = fee.get("last_checked_date") or weekly.get("report_date")
    if not date and isinstance(weekly, Mapping):
        date = weekly.get("date")
    top_themes = (
        weekly.get("top_themes")
        or weekly.get("supported_themes")
        or weekly.get("topThemes")
    )
    weekly_pulse = (
        weekly.get("report")
        or weekly.get("markdown")
        or weekly.get("content")
        or weekly
    )
    identified_fee_issue = (
        weekly.get("fee_observation")
        or fee.get("customer_context")
        or fee.get("identified_fee_issue")
    )
    explanation_bullets = fee.get("explanation_bullets") or fee.get("bullets")
    source_links = (
        fee.get("official_source_urls")
        or fee.get("source_urls")
        or fee.get("sources")
    )

    fields = {
        "date": copy.deepcopy(date),
        "top_themes": copy.deepcopy(top_themes),
        "weekly_pulse": copy.deepcopy(weekly_pulse),
        "identified_fee_issue": copy.deepcopy(identified_fee_issue),
        "explanation_bullets": copy.deepcopy(explanation_bullets),
        "source_links": copy.deepcopy(source_links),
    }
    if any(value is None for value in fields.values()):
        return None
    return fields


_N8N_POSTER_NAMES = (
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
)


def _resolve_n8n_poster():
    for namespace in (mcp_client_adapter, globals()):
        for name in _N8N_POSTER_NAMES:
            candidate = None
            if isinstance(namespace, dict):
                candidate = namespace.get(name)
            else:
                candidate = getattr(namespace, name, None)
            if callable(candidate):
                return candidate
    return None


def _default_n8n_poster(*args: Any, **kwargs: Any) -> dict[str, Any]:
    poster = getattr(mcp_client_adapter, "post_approved_webhook", None)
    if callable(poster):
        return poster(*args, **kwargs)
    return {
        "status": "skipped",
        "error": "n8n webhook poster is not available.",
    }


# Expose the adapter implementation under compatibility aliases in this module.
for _name in _N8N_POSTER_NAMES:
    _candidate = getattr(mcp_client_adapter, _name, None)
    if callable(_candidate):
        globals()[_name] = _candidate


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return list(value.values())
    try:
        return list(value)
    except TypeError:
        return [value]


def _clean_weekly_pulse_text(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in ("report", "markdown", "content", "text"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                value = candidate
                break
        else:
            value = str(value)
    text = str(value if value is not None else "").strip()
    cleaned_lines: list[str] = []
    blank_pending = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if cleaned_lines and not blank_pending:
                cleaned_lines.append("")
            blank_pending = True
            continue
        blank_pending = False
        if line.startswith("#"):
            line = line.lstrip("#").strip()
        elif line.startswith(">"):
            line = line.lstrip(">").strip()
        if line.startswith("- "):
            line = "- " + line[2:].strip()
        cleaned_lines.append(line)
    while cleaned_lines and cleaned_lines[-1] == "":
        cleaned_lines.pop()
    return "\n".join(cleaned_lines)


def _extract_verified_quotes(value: Any) -> list[str]:
    quotes: list[str] = []
    if isinstance(value, Mapping):
        selected = value.get("verified_quotes") or value.get("quotes") or value.get("key_quotes")
        if isinstance(selected, list):
            for item in selected[:3]:
                if isinstance(item, str):
                    quote = item.strip()
                    source = ""
                elif isinstance(item, Mapping) and item.get("quote"):
                    quote = str(item.get("quote", "")).strip()
                    source = str(item.get("source") or "").strip()
                else:
                    continue
                if not quote:
                    continue
                if source:
                    quotes.append(f'{len(quotes) + 1}. "{quote}" - Source: {source}')
                else:
                    quotes.append(f'{len(quotes) + 1}. "{quote}"')
    else:
        in_quotes = False
        for raw_line in str(value if value is not None else "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if "Verified customer quotes" in line:
                in_quotes = True
                continue
            if line.startswith("## ") or line.startswith("#"):
                in_quotes = False
                continue
            if not in_quotes:
                continue
            line = line.lstrip(">").strip()
            if line:
                quotes.append(f'{len(quotes) + 1}. {line}')
    return quotes[:3]


def _plain_bullet_lines(items: Any, *, numbered: bool = False, limit: int | None = None) -> str:
    values = []
    for item in _as_list(items):
        text = str(item).strip() if item is not None else ""
        if text:
            values.append(text)
    if limit is not None:
        values = values[:limit]
    result: list[str] = []
    for index, value in enumerate(values, start=1):
        prefix = f"{index}. " if numbered else "- "
        result.append(f"{prefix}{value}")
    return "\n".join(result)


def _clean_unique_strings(items: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in _as_list(items):
        text = str(item).strip() if item is not None else ""
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _build_n8n_document_text(note_snapshot: Mapping[str, Any]) -> str:
    date_value = str(note_snapshot.get("date") or "").strip()
    top_themes = _clean_unique_strings(note_snapshot.get("top_themes"))
    quotes = _extract_verified_quotes(note_snapshot.get("weekly_pulse"))
    pulse_text = _clean_weekly_pulse_text(note_snapshot.get("weekly_pulse"))
    fee_issue = str(note_snapshot.get("identified_fee_issue") or "").strip()
    bullets = _clean_unique_strings(note_snapshot.get("explanation_bullets"))[:6]
    source_links = _clean_unique_strings(note_snapshot.get("source_links"))

    sections: list[str] = ["APPROVED PRODUCT INSIGHTS"]
    if date_value:
        sections.append(f"Date: {date_value}")
    sections.append("Top themes:\n" + (_plain_bullet_lines(top_themes, numbered=True) or "None provided"))
    sections.append(
        "Verified customer quotes:\n" + (_plain_bullet_lines(quotes, numbered=True) or "None provided")
    )
    sections.append(f"Complete Weekly Product Pulse:\n{pulse_text or 'None provided'}")
    if fee_issue:
        sections.append(f"Identified fee issue:\n{fee_issue}")
    if bullets:
        sections.append(
            "Fee explanation points (up to 6):\n"
            + _plain_bullet_lines(bullets, numbered=True)
        )
    if source_links:
        sections.append("Source links:\n" + _plain_bullet_lines(source_links))
    return "\n\n".join(sections).strip()


def _build_n8n_email_body(note_snapshot: Mapping[str, Any]) -> str:
    date_value = str(note_snapshot.get("date") or "").strip()
    top_themes = _clean_unique_strings(note_snapshot.get("top_themes"))
    quotes = _extract_verified_quotes(note_snapshot.get("weekly_pulse"))
    pulse_text = _clean_weekly_pulse_text(note_snapshot.get("weekly_pulse"))
    fee_issue = str(note_snapshot.get("identified_fee_issue") or "").strip()
    bullets = _clean_unique_strings(note_snapshot.get("explanation_bullets"))[:6]
    source_links = _clean_unique_strings(note_snapshot.get("source_links"))

    sections: list[str] = ["Approved Product Insights"]
    if date_value:
        sections.append(f"Date: {date_value}")
    sections.append("Top themes:\n" + (_plain_bullet_lines(top_themes, numbered=True) or "None provided"))
    sections.append(
        "Verified customer quotes:\n" + (_plain_bullet_lines(quotes, numbered=True) or "None provided")
    )
    sections.append(f"Complete Weekly Product Pulse:\n{pulse_text or 'None provided'}")
    if fee_issue and fee_issue.casefold() not in pulse_text.casefold():
        sections.append(f"Identified fee issue:\n{fee_issue}")
    if bullets:
        sections.append(
            "Fee explanation points (up to 6):\n" + _plain_bullet_lines(bullets, numbered=True)
        )
    if source_links:
        sections.append("Source links:\n" + _plain_bullet_lines(source_links))
    return "\n\n".join(sections).strip()


# Compatibility aliases for alternate formatting helper names.
format_n8n_document_text = _build_n8n_document_text
render_n8n_document_text = _build_n8n_document_text
build_n8n_document_text = _build_n8n_document_text
format_n8n_email_body = _build_n8n_email_body
render_n8n_email_body = _build_n8n_email_body
build_n8n_email_body = _build_n8n_email_body


class ApprovalLedger:
    """Persistent local ledger for approval requests."""

    def __init__(self, storage_path: Any | None = None):
        self.storage_path = _coerce_path(storage_path or DEFAULT_STORAGE_PATH)

    def list_requests(self) -> list[dict[str, Any]]:
        return _load_records(self.storage_path)

    def list(self) -> list[dict[str, Any]]:
        return self.list_requests()

    def get_request(self, approval_id: str) -> dict[str, Any] | None:
        approval_id = str(approval_id or "").strip()
        for record in self.list_requests():
            if str(record.get("id")) == approval_id:
                return copy.deepcopy(record)
            if str(record.get("approval_id")) == approval_id:
                return copy.deepcopy(record)
            if str(record.get("request_id")) == approval_id:
                return copy.deepcopy(record)
        return None

    def _decide_request(
        self,
        approval_id: str,
        new_status: str,
        *,
        payload: Any = None,
        reason: str | None = None,
        decided_by: str | None = None,
        now: str | None = None,
        execute_providers: bool = False,
        notes_provider: Any = None,
        gmail_provider: Any = None,
        provider_mode: str | None = None,
    ) -> dict[str, Any]:
        approval_id = str(approval_id or "").strip()
        normalized_payload = _normalize_payload(payload)
        if isinstance(payload, Mapping):
            reason = payload.get("reason", payload.get("comment", reason))
            decided_by = payload.get(
                "decided_by", payload.get("decidedBy", payload.get("user", decided_by))
            )

        timestamp = now or _utc_now()
        records = self.list_requests()
        for index, record in enumerate(records):
            if str(record.get("id")) != approval_id and str(record.get("approval_id")) != approval_id:
                continue

            current_status = str(record.get("status") or "")
            if current_status != "pending":
                raise ApprovalLedgerError(
                    f"Approval request {approval_id} is {current_status}, "
                    "but only pending requests can be decided."
                )

            record["status"] = new_status
            record["updated_at"] = timestamp
            decision = {
                "status": new_status,
                "decided_at": timestamp,
                "reason": reason,
                "decided_by": decided_by,
            }
            record["decision"] = decision
            record["decided_at"] = timestamp
            record["decided_by"] = decided_by
            record["reason"] = reason

            audit_event = {
                "event": new_status,
                "timestamp": timestamp,
                "status": new_status,
                "reason": reason,
                "decided_by": decided_by,
                "details": f"Approval request {new_status} by human decision.",
            }
            for key in ("audit_history", "audit", "history"):
                if not isinstance(record.get(key), list):
                    record[key] = []
                record[key].append(copy.deepcopy(audit_event))

            records[index] = record
            _save_records(self.storage_path, records)

            if new_status == "approved" and execute_providers:
                try:
                    executed_record = self.execute_approved_providers(
                        approval_id,
                        notes_provider=notes_provider,
                        gmail_provider=gmail_provider,
                        provider_mode=provider_mode,
                        now=timestamp,
                        storage_path=self.storage_path,
                    )
                except ApprovalLedgerError:
                    current = self.get_request(approval_id)
                    if current is not None:
                        records = self.list_requests()
                        for idx, item in enumerate(records):
                            if str(item.get("id")) == approval_id or str(item.get("approval_id")) == approval_id:
                                records[idx] = item
                        _save_records(self.storage_path, records)
                    raise
                records = self.list_requests()
                for idx, item in enumerate(records):
                    if str(item.get("id")) == approval_id or str(item.get("approval_id")) == approval_id:
                        records[idx] = executed_record
                _save_records(self.storage_path, records)
                return copy.deepcopy(executed_record)

            return copy.deepcopy(record)

        raise ApprovalLedgerError(f"Approval request does not exist: {approval_id}")

    def approve_request(
        self,
        approval_id: str,
        payload: Any = None,
        *,
        reason: str | None = None,
        decided_by: str | None = None,
        now: str | None = None,
        execute_providers: bool = False,
        notes_provider: Any = None,
        gmail_provider: Any = None,
        provider_mode: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if reason is None:
            reason = kwargs.pop("approval_reason", kwargs.pop("comment", None))
        if decided_by is None:
            decided_by = kwargs.pop("user", kwargs.pop("decider", None))
        return self._decide_request(
            approval_id,
            "approved",
            payload=payload if payload is not None else (kwargs if kwargs else None),
            reason=reason,
            decided_by=decided_by,
            now=now,
            execute_providers=execute_providers,
            notes_provider=notes_provider,
            gmail_provider=gmail_provider,
            provider_mode=provider_mode,
        )

    def approve(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        approval_id = args[0] if args else kwargs.pop("approval_id", kwargs.pop("request_id", None))
        payload = args[1] if len(args) > 1 else kwargs.pop("payload", None)
        return self.approve_request(approval_id, payload, **kwargs)

    def reject_request(
        self,
        approval_id: str,
        payload: Any = None,
        *,
        reason: str | None = None,
        decided_by: str | None = None,
        now: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if reason is None:
            reason = kwargs.pop("rejection_reason", kwargs.pop("comment", None))
        if decided_by is None:
            decided_by = kwargs.pop("user", kwargs.pop("decider", None))
        return self._decide_request(
            approval_id,
            "rejected",
            payload=payload if payload is not None else (kwargs if kwargs else None),
            reason=reason,
            decided_by=decided_by,
            now=now,
        )

    def reject(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        approval_id = args[0] if args else kwargs.pop("approval_id", kwargs.pop("request_id", None))
        payload = args[1] if len(args) > 1 else kwargs.pop("payload", None)
        return self.reject_request(approval_id, payload, **kwargs)

    def _default_notes_provider(self, mode: str | None = None):
        resolved_mode = mode
        if resolved_mode is None:
            try:
                from services.mcp_client_adapter import get_approval_provider_mode

                resolved_mode = get_approval_provider_mode()
            except Exception:  # pragma: no cover
                resolved_mode = "local"
        resolved_mode = str(resolved_mode or "local").strip().lower()
        if resolved_mode == "mcp_mock":
            from services.mcp_client_adapter import (
                create_default_mcp_client,
                McpNotesProvider,
            )

            return McpNotesProvider(create_default_mcp_client())
        base = Path(__file__).resolve().parents[1] / "data"
        try:
            from services.notes_provider import LocalNotesProvider
        except ImportError:  # pragma: no cover
            from notes_provider import LocalNotesProvider  # type: ignore
        return LocalNotesProvider(base / "approved_notes")

    def _default_gmail_provider(self, mode: str | None = None):
        resolved_mode = mode
        if resolved_mode is None:
            try:
                from services.mcp_client_adapter import get_approval_provider_mode

                resolved_mode = get_approval_provider_mode()
            except Exception:  # pragma: no cover
                resolved_mode = "local"
        resolved_mode = str(resolved_mode or "local").strip().lower()
        if resolved_mode == "mcp_mock":
            from services.mcp_client_adapter import (
                create_default_mcp_client,
                McpGmailDraftProvider,
            )

            return McpGmailDraftProvider(create_default_mcp_client())
        base = Path(__file__).resolve().parents[1] / "data"
        try:
            from services.gmail_draft_provider import MockGmailDraftProvider
        except ImportError:  # pragma: no cover
            from gmail_draft_provider import MockGmailDraftProvider  # type: ignore
        return MockGmailDraftProvider(base / "gmail_drafts")

    def _missing_note_fields(self, snapshot: Any) -> list[str]:
        if not isinstance(snapshot, Mapping):
            return list(_REQUIRED_NOTE_SNAPSHOT_FIELDS)
        missing = []
        for field in _REQUIRED_NOTE_SNAPSHOT_FIELDS:
            if field not in snapshot or snapshot.get(field) is None:
                missing.append(field)
        return missing

    def _normalize_note_snapshot(self, record: Mapping[str, Any]) -> dict[str, Any]:
        candidates = []
        snapshot = record.get("snapshot")
        if isinstance(snapshot, Mapping):
            candidates.append(snapshot)
        if isinstance(record, Mapping):
            candidates.append(record)
        for key in ("request", "payload", "input_payload"):
            value = record.get(key) if isinstance(record, Mapping) else None
            if isinstance(value, Mapping):
                candidates.append(value)
        for candidate in candidates:
            if all(field in candidate and candidate.get(field) is not None for field in _REQUIRED_NOTE_SNAPSHOT_FIELDS):
                return {field: copy.deepcopy(candidate[field]) for field in _REQUIRED_NOTE_SNAPSHOT_FIELDS}
        for candidate in candidates:
            extracted = _extract_note_fields(candidate) if isinstance(candidate, Mapping) else None
            if extracted is not None and all(extracted.get(field) is not None for field in _REQUIRED_NOTE_SNAPSHOT_FIELDS):
                return extracted
        raise ApprovalLedgerError(
            "Approval snapshot is missing required fields: "
            + ", ".join(_REQUIRED_NOTE_SNAPSHOT_FIELDS)
        )

    def execute_approved_providers(
        self,
        approval_id: str,
        *,
        notes_provider: Any = None,
        gmail_provider: Any = None,
        provider_mode: str | None = None,
        now: str | None = None,
        storage_path: Any | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        approval_id = str(approval_id or "").strip()
        records = self.list_requests()
        target_index = None
        record = None
        for index, item in enumerate(records):
            if str(item.get("id")) == approval_id or str(item.get("approval_id")) == approval_id:
                target_index = index
                record = item
                break
        if record is None:
            raise ApprovalLedgerError(f"Approval request does not exist: {approval_id}")

        if str(record.get("status")) != "approved":
            raise ApprovalLedgerError(
                f"Approval request {approval_id} is {record.get('status')}, "
                "but only approved requests can execute providers."
            )

        timestamp = now or _utc_now()
        execution = record.get("execution")
        if not isinstance(execution, Mapping):
            execution = {
                "state": "not_started",
                "notes": {"status": "not_started"},
                "gmail_draft": {"status": "not_started"},
            }
        if provider_mode is None:
            try:
                from services.mcp_client_adapter import get_approval_provider_mode

                provider_mode = get_approval_provider_mode()
            except Exception:  # pragma: no cover
                provider_mode = "local"
        resolved_provider_mode = str(provider_mode or "local").strip().lower()
        if resolved_provider_mode not in {"local", "mcp_mock"}:
            resolved_provider_mode = "local"

        execution = copy.deepcopy(dict(execution))
        execution["provider_mode"] = resolved_provider_mode
        notes_action = execution.get("notes")
        if not isinstance(notes_action, Mapping):
            notes_action = {"status": "not_started"}
        notes_action = copy.deepcopy(dict(notes_action))
        draft_action = execution.get("gmail_draft")
        if not isinstance(draft_action, Mapping):
            draft_action = {"status": "not_started"}
        draft_action = copy.deepcopy(dict(draft_action))
        n8n_action = execution.get("n8n_webhook")
        if not isinstance(n8n_action, Mapping):
            n8n_action = {"status": "not_started"}
        n8n_action = copy.deepcopy(dict(n8n_action))

        # Validate before attempting execution.
        try:
            note_snapshot = self._normalize_note_snapshot(record)
        except ApprovalLedgerError as exc:
            missing_message = str(exc)
            notes_action = {
                "status": "failed",
                "path": notes_action.get("path"),
                "error": missing_message,
                "failed_at": _utc_now(),
            }
            draft_action = {
                "status": "failed",
                "draft_id": draft_action.get("draft_id"),
                "path": draft_action.get("path"),
                "error": missing_message,
                "failed_at": _utc_now(),
            }
            execution["notes"] = notes_action
            execution["gmail_draft"] = draft_action
            execution["n8n_webhook"] = n8n_action
            execution["state"] = "failed"
            record["execution"] = execution
            record["execution_status"] = "failed"
            records[target_index] = record
            _save_records(self.storage_path, records)
            raise ApprovalLedgerError(missing_message) from exc

        if notes_provider is None:
            notes_provider = self._default_notes_provider(provider_mode)
        if gmail_provider is None:
            gmail_provider = self._default_gmail_provider(provider_mode)

        state_changed = False

        if notes_action.get("status") != "succeeded":
            try:
                note_path = notes_provider.save_note(
                    date=note_snapshot["date"],
                    top_themes=note_snapshot["top_themes"],
                    weekly_pulse=note_snapshot["weekly_pulse"],
                    identified_fee_issue=note_snapshot["identified_fee_issue"],
                    explanation_bullets=note_snapshot["explanation_bullets"],
                    source_links=note_snapshot["source_links"],
                    filename=f"approval_{approval_id}.md",
                )
                note_metadata = note_path if hasattr(note_path, "get") else {}
                notes_action = {
                    "status": "succeeded",
                    "path": str(note_path),
                    "error": None,
                    "completed_at": _utc_now(),
                    "provider": getattr(note_path, "get", lambda key, default=None: default)("provider", None)
                    if hasattr(note_path, "get")
                    else None,
                    "tool": getattr(note_path, "get", lambda key, default=None: default)("tool", None)
                    if hasattr(note_path, "get")
                    else None,
                    "artifact_id": getattr(note_path, "get", lambda key, default=None: default)("artifact_id", None)
                    if hasattr(note_path, "get")
                    else None,
                    "result": getattr(note_path, "get", lambda key, default=None: default)("result", None)
                    if hasattr(note_path, "get")
                    else None,
                }
                state_changed = True
            except Exception as exc:  # pragma: no cover - exercised by partial failure tests
                notes_action = {
                    "status": "failed",
                    "path": notes_action.get("path"),
                    "error": str(exc),
                    "failed_at": _utc_now(),
                }
                state_changed = True
            execution["notes"] = notes_action

        if draft_action.get("status") != "succeeded":
            try:
                draft_artifact = gmail_provider.create_draft(
                    subject="Weekly Product Pulse",
                    date=note_snapshot["date"],
                    top_themes=note_snapshot["top_themes"],
                    weekly_pulse=note_snapshot["weekly_pulse"],
                    fee_explainer=note_snapshot["identified_fee_issue"],
                    identified_fee_issue=note_snapshot["identified_fee_issue"],
                    explanation_bullets=note_snapshot["explanation_bullets"],
                    source_links=note_snapshot["source_links"],
                    draft_id=f"mock-draft-{approval_id}",
                )
                draft_action = {
                    "status": "succeeded",
                    "draft_id": getattr(draft_artifact, "draft_id", None)
                    or (
                        draft_artifact.get("draft_id")
                        if hasattr(draft_artifact, "get")
                        else None
                    )
                    or f"mock-draft-{approval_id}",
                    "path": str(draft_artifact),
                    "error": None,
                    "completed_at": _utc_now(),
                    "provider": draft_artifact.get("provider", None)
                    if hasattr(draft_artifact, "get")
                    else None,
                    "tool": draft_artifact.get("tool", None)
                    if hasattr(draft_artifact, "get")
                    else None,
                    "artifact_id": draft_artifact.get("artifact_id", None)
                    if hasattr(draft_artifact, "get")
                    else None,
                    "result": draft_artifact.get("result", None)
                    if hasattr(draft_artifact, "get")
                    else None,
                }
                state_changed = True
            except Exception as exc:  # pragma: no cover - exercised by partial failure tests
                draft_action = {
                    "status": "failed",
                    "draft_id": draft_action.get("draft_id"),
                    "path": draft_action.get("path"),
                    "error": str(exc),
                    "failed_at": _utc_now(),
                }
                state_changed = True
            execution["gmail_draft"] = draft_action

        if notes_action.get("status") == "succeeded" and draft_action.get("status") == "succeeded":
            execution["state"] = "succeeded"
        elif notes_action.get("status") == "failed" or draft_action.get("status") == "failed":
            execution["state"] = "partial" if (
                notes_action.get("status") == "succeeded"
                or draft_action.get("status") == "succeeded"
            ) else "failed"
        else:
            execution["state"] = execution.get("state", "partial")

        if (
            notes_action.get("status") == "succeeded"
            and draft_action.get("status") == "succeeded"
            and n8n_action.get("status") != "succeeded"
        ):
            try:
                poster = _resolve_n8n_poster()
                if poster is None:
                    poster = _default_n8n_poster
                email_subject = _normalize_subject("Weekly Product Pulse", note_snapshot["date"])
                document_text = _build_n8n_document_text(note_snapshot)
                email_body = _build_n8n_email_body(note_snapshot)
                result = poster(
                    approval_id=approval_id,
                    document_text=document_text,
                    email_subject=email_subject,
                    email_body=email_body,
                )
                if isinstance(result, Mapping):
                    n8n_action = copy.deepcopy(dict(result))
                else:
                    n8n_action = {
                        "status": "succeeded" if result else "failed",
                        "error": None if result else "n8n webhook returned no result.",
                    }
            except Exception as exc:  # pragma: no cover - defensive boundary
                n8n_action = {
                    "status": "failed",
                    "error": str(exc)[:300],
                    "failed_at": _utc_now(),
                }

            status = n8n_action.get("status")
            if status == "succeeded":
                n8n_action.setdefault("completed_at", _utc_now())
            elif status == "failed":
                n8n_action.setdefault("failed_at", _utc_now())
                if execution.get("state") == "succeeded":
                    execution["state"] = "partial"
            n8n_action["error"] = n8n_action.get("error")
            state_changed = True

        execution["n8n_webhook"] = n8n_action

        record["execution"] = execution
        record["execution_status"] = execution["state"]
        record["updated_at"] = timestamp

        audit_event = {
            "event": "execution",
            "timestamp": timestamp,
            "execution_state": execution["state"],
            "provider_mode": execution.get("provider_mode"),
            "notes_status": notes_action.get("status"),
            "gmail_draft_status": draft_action.get("status"),
            "notes_path": notes_action.get("path"),
            "gmail_draft_path": draft_action.get("path"),
            "notes_tool": notes_action.get("tool"),
            "gmail_draft_tool": draft_action.get("tool"),
            "notes_artifact_id": notes_action.get("artifact_id"),
            "gmail_draft_artifact_id": draft_action.get("artifact_id"),
            "notes_result": notes_action.get("result"),
            "gmail_draft_result": draft_action.get("result"),
            "n8n_webhook_status": n8n_action.get("status"),
            "n8n_webhook_status_code": n8n_action.get("status_code"),
            "n8n_webhook_error": n8n_action.get("error"),
            "details": "Approval-gated provider execution attempted.",
        }
        for key in ("audit_history", "audit", "history"):
            if not isinstance(record.get(key), list):
                record[key] = []
            record[key].append(copy.deepcopy(audit_event))
        records[target_index] = record
        _save_records(self.storage_path, records)
        return copy.deepcopy(record)

    def create_request(
        self,
        payload: Any = None,
        *,
        weekly_pulse: Any | None = None,
        fee_explainer: Any | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        normalized_payload = _normalize_payload(payload)
        snapshot = _build_snapshot(weekly_pulse=weekly_pulse, fee_explainer=fee_explainer)
        if _has_note_snapshot_field(normalized_payload):
            note_fields = _provided_note_snapshot(normalized_payload)
        else:
            note_fields = _default_note_snapshot(snapshot)
        if note_fields is not None:
            snapshot = copy.deepcopy(snapshot)
            snapshot.update(note_fields)

        timestamp = now or _utc_now()
        approval_id = str(uuid.uuid4())

        audit_event = {
            "event": "created",
            "timestamp": timestamp,
            "details": "Approval request created with pending status.",
        }
        audit_history = [audit_event]

        request = {
            "id": approval_id,
            "approval_id": approval_id,
            "request_id": approval_id,
            "created_at": timestamp,
            "status": "pending",
            "input_payload": normalized_payload,
            "request": normalized_payload,
            "payload": copy.deepcopy(normalized_payload),
            "snapshot": copy.deepcopy(snapshot),
            "snapshots": copy.deepcopy(snapshot),
            "weekly_pulse": copy.deepcopy(snapshot["weekly_pulse"]),
            "fee_explainer": copy.deepcopy(snapshot["fee_explainer"]),
            "execution": {
                "state": "not_started",
                "notes": {"status": "not_started"},
                "gmail_draft": {"status": "not_started"},
                "n8n_webhook": {"status": "not_started"},
            },
            "execution_status": "not_started",
            "weekly_pulse_snapshot": copy.deepcopy(snapshot["weekly_pulse"]),
            "fee_explainer_snapshot": copy.deepcopy(snapshot["fee_explainer"]),
            "immutable": True,
            "audit_history": audit_history,
            "audit": copy.deepcopy(audit_history),
            "history": copy.deepcopy(audit_history),
        }

        # Preserve conventional metadata supplied by the caller without
        # allowing it to overwrite immutable identity/status fields.
        for key in ("title", "description", "subject", "requested_by", "requester"):
            if key in normalized_payload and normalized_payload[key] is not None:
                request[key] = normalized_payload[key]

        records = self.list_requests()
        records.append(request)
        _save_records(self.storage_path, records)
        return copy.deepcopy(request)

    def create(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.create_request(*args, **kwargs)


def create_approval_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
    storage_path = kwargs.pop("storage_path", kwargs.pop("path", None))
    ledger = ApprovalLedger(storage_path)
    return ledger.create_request(*args, **kwargs)


def list_approval_requests(storage_path: Any | None = None) -> list[dict[str, Any]]:
    return ApprovalLedger(storage_path).list_requests()


def approve_approval_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
    storage_path = kwargs.pop("storage_path", kwargs.pop("path", None))
    ledger = ApprovalLedger(storage_path)
    return ledger.approve_request(*args, **kwargs)


def reject_approval_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
    storage_path = kwargs.pop("storage_path", kwargs.pop("path", None))
    ledger = ApprovalLedger(storage_path)
    return ledger.reject_request(*args, **kwargs)


__all__ = [
    "ApprovalLedger",
    "ApprovalLedgerError",
    "DEFAULT_STORAGE_PATH",
    "create_approval_request",
    "list_approval_requests",
    "approve_approval_request",
    "reject_approval_request",
]
