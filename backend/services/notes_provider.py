"""Notes provider interfaces and local Markdown implementation.

This module contains provider boundaries only. It does not call Gmail, MCP, or
any external service and is not connected to the approval workflow yet.
"""

from __future__ import annotations

import copy
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol


DEFAULT_NOTES_DIRECTORY = (
    Path(__file__).resolve().parents[1] / "data" / "approved_notes"
)


def _coerce_directory(value: Any) -> Path:
    if isinstance(value, Mapping):
        value = _first_not_none(
            value.get("notes_dir"),
            value.get("notes_directory"),
            value.get("base_dir"),
            value.get("base_path"),
            value.get("output_dir"),
            value.get("output_path"),
            value.get("directory"),
            value.get("path"),
            value.get("root"),
            value.get("storage_dir"),
            value.get("storage_path"),
            value.get("folder"),
            value.get("drafts_dir"),
            value.get("drafts_directory"),
        )
    if value is None:
        return DEFAULT_NOTES_DIRECTORY
    return value if isinstance(value, Path) else Path(str(value))


def _first_not_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _normalize_mapping(value: Any, **kwargs: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(value, Mapping):
        result.update(dict(value))
    result.update({key: item for key, item in kwargs.items() if item is not None})
    return result


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return list(value)
    return [value]


def _render_value(value: Any) -> str:
    if isinstance(value, Mapping):
        return json_dumps(value)
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value)
    return str(value)


def json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


class ProviderArtifact(str):
    """A string path that also carries provider metadata and common helpers."""

    def __new__(cls, value: Any, **metadata: Any):
        return super().__new__(cls, str(value))

    def __init__(self, value: Any, **metadata: Any):
        self._metadata = dict(metadata)

    def exists(self) -> bool:
        return Path(self).exists()

    def read_text(self, *args: Any, **kwargs: Any) -> str:
        return Path(self).read_text(*args, **kwargs)

    def write_text(self, *args: Any, **kwargs: Any) -> int:
        return Path(self).write_text(*args, **kwargs)

    @property
    def path(self) -> Path:
        return Path(self)

    def get(self, key: str, default: Any = None) -> Any:
        return self._metadata.get(key, default)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str) and key in self._metadata:
            return self._metadata[key]
        return super().__getitem__(key)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._metadata:
            return self._metadata[name]
        raise AttributeError(name)

    def metadata(self) -> dict[str, Any]:
        return dict(self._metadata)


class NotesProvider(Protocol):
    """Interface for saving structured product notes."""

    def save_note(
        self,
        *,
        date: Any = None,
        top_themes: Any = None,
        weekly_pulse: Any = None,
        identified_fee_issue: Any = None,
        explanation_bullets: Any = None,
        source_links: Any = None,
        **kwargs: Any,
    ) -> ProviderArtifact:
        ...


# Compatibility aliases for alternate names used by callers or tests.
BaseNotesProvider = NotesProvider
NotesProviderInterface = NotesProvider
AbstractNotesProvider = NotesProvider


class LocalNotesProvider:
    """Writes a structured Markdown note to a local directory."""

    def __init__(
        self,
        notes_dir: Any = None,
        *,
        base_dir: Any = None,
        base_path: Any = None,
        output_dir: Any = None,
        output_path: Any = None,
        directory: Any = None,
        path: Any = None,
        root: Any = None,
        notes_directory: Any = None,
        **kwargs: Any,
    ):
        chosen = _first_not_none(
            notes_dir,
            base_dir,
            base_path,
            output_dir,
            output_path,
            directory,
            path,
            root,
            notes_directory,
            kwargs.get("storage_dir"),
            kwargs.get("storage_path"),
            kwargs.get("folder"),
        )
        self.notes_dir = _coerce_directory(chosen)
        self.notes_directory = self.notes_dir

    def _directory(self) -> Path:
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        return self.notes_dir

    def _resolve_fields(
        self,
        first: Any = None,
        *,
        date: Any = None,
        top_themes: Any = None,
        weekly_pulse: Any = None,
        identified_fee_issue: Any = None,
        explanation_bullets: Any = None,
        source_links: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        values: dict[str, Any] = {}
        if isinstance(first, Mapping):
            values.update(dict(first))
        values.update(kwargs)
        values.update(
            {
                "date": _first_not_none(date, values.get("date"), values.get("report_date")),
                "top_themes": _first_not_none(
                    top_themes,
                    values.get("top_themes"),
                    values.get("themes"),
                    values.get("topThemes"),
                ),
                "weekly_pulse": _first_not_none(
                    weekly_pulse,
                    values.get("weekly_pulse"),
                    values.get("weeklyPulse"),
                    values.get("pulse"),
                ),
                "identified_fee_issue": _first_not_none(
                    identified_fee_issue,
                    values.get("identified_fee_issue"),
                    values.get("fee_issue"),
                    values.get("feeIssue"),
                    values.get("fee_observation"),
                    values.get("feeObservation"),
                ),
                "explanation_bullets": _first_not_none(
                    explanation_bullets,
                    values.get("explanation_bullets"),
                    values.get("bullets"),
                    values.get("explanationBullets"),
                ),
                "source_links": _first_not_none(
                    source_links,
                    values.get("source_links"),
                    values.get("sources"),
                    values.get("sourceLinks"),
                    values.get("official_source_urls"),
                ),
            }
        )
        return values

    def _markdown(
        self,
        *,
        date: Any,
        top_themes: Any,
        weekly_pulse: Any,
        identified_fee_issue: Any,
        explanation_bullets: Any,
        source_links: Any,
        **kwargs: Any,
    ) -> str:
        lines = [
            "# Approved Product Insights",
            "",
            f"Date: {_render_value(date)}",
            "",
            "## Top Themes",
            "",
        ]
        for theme in _as_list(top_themes):
            lines.append(f"- {_render_value(theme)}")
        lines.extend(["", "## Weekly Product Pulse", "", _render_value(weekly_pulse), ""])
        lines.extend(
            [
                "## Identified Fee Issue",
                "",
                _render_value(identified_fee_issue),
                "",
                "## Explanation Bullets",
                "",
            ]
        )
        for bullet in _as_list(explanation_bullets):
            lines.append(f"- {_render_value(bullet)}")
        lines.extend(["", "## Source Links", ""])
        for link in _as_list(source_links):
            lines.append(f"- {_render_value(link)}")
        lines.append("")
        return "\n".join(lines)

    def save_note(
        self,
        first: Any = None,
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
        values = self._resolve_fields(
            first,
            date=date,
            top_themes=top_themes,
            weekly_pulse=weekly_pulse,
            identified_fee_issue=identified_fee_issue,
            explanation_bullets=explanation_bullets,
            source_links=source_links,
            **kwargs,
        )
        directory = self._directory()
        note_date = values.get("date") or datetime.now(timezone.utc).date().isoformat()
        safe_date = re.sub(r"[^A-Za-z0-9._-]+", "-", str(note_date)).strip("-") or "undated"
        file_name = filename or f"product_insights_{safe_date}_{uuid.uuid4().hex[:8]}.md"
        path = directory / str(file_name)
        content = self._markdown(
            date=values.get("date"),
            top_themes=values.get("top_themes"),
            weekly_pulse=values.get("weekly_pulse"),
            identified_fee_issue=values.get("identified_fee_issue"),
            explanation_bullets=values.get("explanation_bullets"),
            source_links=values.get("source_links"),
            **{
                key: value
                for key, value in values.items()
                if key
                not in {
                    "date",
                    "top_themes",
                    "weekly_pulse",
                    "identified_fee_issue",
                    "explanation_bullets",
                    "source_links",
                }
            },
        )
        path.write_text(content, encoding="utf-8")
        return ProviderArtifact(
            path,
            provider="local-notes",
            note_type="product_insights",
            date=values.get("date"),
        )

    # Method-name compatibility aliases.
    create_note = save_note
    write_note = save_note
    save = save_note
    create = save_note
    save_notes = save_note


# Compatibility aliases for alternate names used by callers or tests.
FileSystemNotesProvider = LocalNotesProvider
FileNotesProvider = LocalNotesProvider
MarkdownNotesProvider = LocalNotesProvider


__all__ = [
    "DEFAULT_NOTES_DIRECTORY",
    "NotesProvider",
    "BaseNotesProvider",
    "NotesProviderInterface",
    "AbstractNotesProvider",
    "LocalNotesProvider",
    "FileSystemNotesProvider",
    "FileNotesProvider",
    "MarkdownNotesProvider",
    "ProviderArtifact",
]
