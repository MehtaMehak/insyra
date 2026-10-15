"""Gmail draft provider interfaces and mock implementation.

Only draft creation is represented here. There is intentionally no send-email
method. Providers are not connected to the approval workflow in this step.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

try:
    from services.notes_provider import ProviderArtifact
except ImportError:  # pragma: no cover - supports alternate test invocation
    from notes_provider import ProviderArtifact  # type: ignore

DEFAULT_DRAFTS_DIRECTORY = (
    Path(__file__).resolve().parents[1] / "data" / "gmail_drafts"
)

REQUIRED_SUBJECT_PREFIX = "Weekly Product Pulse + Customer Clarification —"


def _coerce_directory(value: Any) -> Path:
    from services.notes_provider import _coerce_directory as coerce

    return coerce(value)


def _first_not_none(*values: Any) -> Any:
    from services.notes_provider import _first_not_none as first

    return first(*values)


def _as_list(value: Any) -> list[Any]:
    from services.notes_provider import _as_list as as_list

    return as_list(value)


def _render_value(value: Any) -> str:
    from services.notes_provider import _render_value as render

    return render(value)


class GmailDraftProvider(Protocol):
    """Interface for creating Gmail drafts only."""

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
        ...


BaseGmailDraftProvider = GmailDraftProvider
GmailDraftProviderInterface = GmailDraftProvider
AbstractGmailDraftProvider = GmailDraftProvider


class MockGmailDraftProvider:
    """Creates a local draft artifact; it never sends email."""

    def __init__(
        self,
        drafts_dir: Any = None,
        *,
        base_dir: Any = None,
        base_path: Any = None,
        output_dir: Any = None,
        output_path: Any = None,
        directory: Any = None,
        path: Any = None,
        root: Any = None,
        drafts_directory: Any = None,
        **kwargs: Any,
    ):
        chosen = _first_not_none(
            drafts_dir,
            base_dir,
            base_path,
            output_dir,
            output_path,
            directory,
            path,
            root,
            drafts_directory,
            kwargs.get("storage_dir"),
            kwargs.get("storage_path"),
            kwargs.get("folder"),
        )
        self.drafts_dir = _coerce_directory(chosen)
        self.drafts_directory = self.drafts_dir

    def _directory(self) -> Path:
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        return self.drafts_dir

    def _normalize_subject(self, subject: Any = None, date: Any = None) -> str:
        raw = "" if subject is None else str(subject).strip()
        if not raw:
            suffix = f" {date}" if date else ""
            raw = f"{REQUIRED_SUBJECT_PREFIX.strip()} Product Update{suffix}".strip()
        if not raw.startswith(REQUIRED_SUBJECT_PREFIX):
            raw = f"{REQUIRED_SUBJECT_PREFIX} {raw}".strip()
        return raw

    def _build_recipients(self, to: Any = None, recipient: Any = None, recipients: Any = None, **kwargs: Any) -> list[str]:
        values = []
        if to is not None:
            values.extend(_as_list(to))
        if recipient is not None:
            values.extend(_as_list(recipient))
        if recipients is not None:
            values.extend(_as_list(recipients))
        for key in ("to_list", "email", "emails", "recipient_list"):
            if key in kwargs and kwargs[key] is not None:
                values.extend(_as_list(kwargs[key]))
        return [str(item).strip() for item in values if str(item).strip()]

    def _render_weekly_pulse(self, weekly_pulse: Any = None, **kwargs: Any) -> str:
        value = _first_not_none(weekly_pulse, kwargs.get("weekly_pulse"), kwargs.get("pulse"))
        if value is None:
            return ""
        if isinstance(value, Mapping):
            parts = []
            for key in ("report", "markdown", "content"):
                if value.get(key):
                    parts.append(str(value.get(key)))
            if parts:
                return "\n\n".join(parts)
        return _render_value(value)

    def _render_fee_explainer(self, fee_explainer: Any = None, **kwargs: Any) -> str:
        value = _first_not_none(fee_explainer, kwargs.get("fee_explainer"), kwargs.get("feeExplainer"))
        if value is None:
            return ""
        if isinstance(value, Mapping):
            bullets = value.get("explanation_bullets", value.get("bullets"))
            if bullets:
                return "\n".join(f"- {_render_value(item)}" for item in _as_list(bullets))
        return _render_value(value)

    def _build_body(
        self,
        body: Any = None,
        *,
        weekly_pulse: Any = None,
        fee_explainer: Any = None,
        date: Any = None,
        top_themes: Any = None,
        identified_fee_issue: Any = None,
        explanation_bullets: Any = None,
        source_links: Any = None,
        **kwargs: Any,
    ) -> str:
        if body is not None:
            base = str(body)
        else:
            base = ""
        if "Weekly Product Pulse" not in base:
            pulse_text = self._render_weekly_pulse(weekly_pulse=weekly_pulse, **kwargs)
            if pulse_text:
                base = (base + "\n\n" if base.strip() else "") + "## Weekly Product Pulse\n\n" + pulse_text
        if "Fee Explainer" not in base:
            fee_text = self._render_fee_explainer(fee_explainer=fee_explainer, **kwargs)
            if fee_text:
                base = (base + "\n\n" if base.strip() else "") + "## Factual Fee Explainer\n\n" + fee_text
        if identified_fee_issue and "Identified Fee Issue" not in base:
            base = base + "\n\n## Identified Fee Issue\n\n" + _render_value(identified_fee_issue)
        if top_themes and "Top Themes" not in base:
            base = base + "\n\n## Top Themes\n\n" + "\n".join(f"- {_render_value(item)}" for item in _as_list(top_themes))
        if explanation_bullets and "Explanation Bullets" not in base:
            base = base + "\n\n## Explanation Bullets\n\n" + "\n".join(f"- {_render_value(item)}" for item in _as_list(explanation_bullets))
        if source_links and "Source Links" not in base:
            base = base + "\n\n## Source Links\n\n" + "\n".join(f"- {_render_value(item)}" for item in _as_list(source_links))
        if date and "Date:" not in base:
            base = f"Date: {_render_value(date)}\n\n" + base
        return base.strip()

    def _resolve_fields(self, first: Any = None, **kwargs: Any) -> dict[str, Any]:
        values: dict[str, Any] = {}
        if isinstance(first, Mapping):
            values.update(dict(first))
        values.update({key: item for key, item in kwargs.items() if item is not None})
        return values

    def create_draft(
        self,
        first: Any = None,
        *,
        subject: Any = None,
        body: Any = None,
        to: Any = None,
        recipient: Any = None,
        recipients: Any = None,
        title: Any = None,
        content: Any = None,
        message: Any = None,
        text: Any = None,
        weekly_pulse: Any = None,
        fee_explainer: Any = None,
        date: Any = None,
        top_themes: Any = None,
        identified_fee_issue: Any = None,
        explanation_bullets: Any = None,
        source_links: Any = None,
        **kwargs: Any,
    ) -> ProviderArtifact:
        values = self._resolve_fields(
            first,
            subject=subject,
            body=body,
            to=to,
            recipient=recipient,
            recipients=recipients,
            title=title,
            content=content,
            message=message,
            text=text,
            weekly_pulse=weekly_pulse,
            fee_explainer=fee_explainer,
            date=date,
            top_themes=top_themes,
            identified_fee_issue=identified_fee_issue,
            explanation_bullets=explanation_bullets,
            source_links=source_links,
            **kwargs,
        )

        resolved_subject_input = _first_not_none(
            values.get("subject"),
            values.get("title"),
        )
        resolved_subject = self._normalize_subject(resolved_subject_input, values.get("date"))
        resolved_body_input = _first_not_none(
            values.get("body"),
            values.get("content"),
            values.get("message"),
            values.get("text"),
        )
        resolved_body = self._build_body(
            resolved_body_input,
            weekly_pulse=_first_not_none(values.get("weekly_pulse"), values.get("pulse")),
            fee_explainer=_first_not_none(values.get("fee_explainer"), values.get("feeExplainer")),
            date=values.get("date"),
            top_themes=_first_not_none(values.get("top_themes"), values.get("themes")),
            identified_fee_issue=_first_not_none(
                values.get("identified_fee_issue"),
                values.get("fee_issue"),
                values.get("feeObservation"),
            ),
            explanation_bullets=_first_not_none(
                values.get("explanation_bullets"),
                values.get("bullets"),
            ),
            source_links=_first_not_none(
                values.get("source_links"),
                values.get("sources"),
                values.get("source_links"),
            ),
            **{
                key: val
                for key, val in values.items()
                if key
                not in {
                    "subject",
                    "title",
                    "body",
                    "content",
                    "message",
                    "text",
                    "weekly_pulse",
                    "pulse",
                    "fee_explainer",
                    "feeExplainer",
                    "date",
                    "top_themes",
                    "themes",
                    "identified_fee_issue",
                    "fee_issue",
                    "feeObservation",
                    "explanation_bullets",
                    "bullets",
                    "source_links",
                    "sources",
                }
            },
        )
        resolved_recipients = self._build_recipients(
            values.get("to"),
            values.get("recipient"),
            values.get("recipients"),
            **values,
        )

        directory = self._directory()
        import time

        explicit_draft_id = _first_not_none(
            values.get("draft_id"),
            values.get("draftId"),
            values.get("draft"),
            values.get("id"),
        )
        explicit_filename = values.get("filename")
        if explicit_draft_id is None and explicit_filename is not None:
            explicit_draft_id = Path(str(explicit_filename)).stem
        if explicit_draft_id is not None:
            draft_id = str(explicit_draft_id)
            if explicit_filename is not None:
                path = directory / str(explicit_filename)
            else:
                path = directory / f"{draft_id}.json"
        else:
            draft_id = f"mock-draft-{int(time.time() * 1000)}-{len(list(directory.glob('*.json')))}"
            path = directory / f"{draft_id}.json"
        artifact = {
            "draft_id": draft_id,
            "provider": "mock-gmail-draft",
            "status": "draft",
            "to": resolved_recipients,
            "subject": resolved_subject,
            "body": resolved_body,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "sent": False,
        }
        path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return ProviderArtifact(
            path,
            provider="mock-gmail-draft",
            draft_id=draft_id,
            subject=resolved_subject,
            recipients=resolved_recipients,
            sent=False,
        )

    # Method-name compatibility aliases.
    create = create_draft
    draft = create_draft
    save_draft = create_draft
    write_draft = create_draft


# Compatibility aliases for alternate names used by callers or tests.
LocalGmailDraftProvider = MockGmailDraftProvider
GmailDraftMockProvider = MockGmailDraftProvider
DummyGmailDraftProvider = MockGmailDraftProvider
FakeGmailDraftProvider = MockGmailDraftProvider


__all__ = [
    "DEFAULT_DRAFTS_DIRECTORY",
    "REQUIRED_SUBJECT_PREFIX",
    "GmailDraftProvider",
    "BaseGmailDraftProvider",
    "GmailDraftProviderInterface",
    "AbstractGmailDraftProvider",
    "MockGmailDraftProvider",
    "LocalGmailDraftProvider",
    "GmailDraftMockProvider",
    "DummyGmailDraftProvider",
    "FakeGmailDraftProvider",
    "ProviderArtifact",
]
