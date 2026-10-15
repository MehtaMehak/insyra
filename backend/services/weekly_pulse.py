"""Generate a concise Weekly Product Pulse from existing AI analysis.

The report is deterministic. It uses saved analysis output only and does not
call Groq or create new customer feedback. Findings are attributed to the
deliberately selected 300-review sample.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping


MAX_REPORT_WORDS = 250
TOP_THEME_COUNT = 3
VERIFY_QUOTE_COUNT = 3


@dataclass(frozen=True)
class WeeklyPulseResult:
    report_date: str
    report: str
    word_count: int
    supported_themes: list[str]
    verified_quotes: list[dict[str, str]]
    fee_observation: str
    recommended_actions: list[str]
    sample_size: int
    total_review_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "report_date": self.report_date,
            "report": self.report,
            # Common response keys used by API callers and UI components.
            "content": self.report,
            "markdown": self.report,
            "word_count": self.word_count,
            "top_themes": self.supported_themes,
            "verified_quotes": self.verified_quotes,
            "fee_observation": self.fee_observation,
            "recommended_actions": self.recommended_actions,
            "sample_size": self.sample_size,
            "total_review_count": self.total_review_count,
        }


class WeeklyPulseError(Exception):
    """Raised when a Weekly Product Pulse cannot be generated safely."""


def _load_analysis(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise WeeklyPulseError(f"AI analysis file does not exist: {path}")
    try:
        with path.open("r", encoding="utf-8") as analysis_file:
            data = json.load(analysis_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise WeeklyPulseError("Saved AI analysis is missing or invalid.") from None
    if not isinstance(data, Mapping):
        raise WeeklyPulseError("Saved AI analysis has an invalid structure.")
    return data


def _normalize_date(value: str | None) -> str:
    if value:
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError as exc:
            raise WeeklyPulseError("report_date must be an ISO date (YYYY-MM-DD).") from None
    return date.today().isoformat()


def _top_themes(analysis: Mapping[str, Any]) -> list[str]:
    themes = analysis.get("themes")
    if not isinstance(themes, list) or not themes:
        raise WeeklyPulseError("AI analysis does not contain themes.")
    selected: list[str] = []
    for item in themes[:TOP_THEME_COUNT]:
        if not isinstance(item, Mapping):
            continue
        theme = str(item.get("theme") or item.get("name") or item.get("title") or "").strip()
        if theme:
            selected.append(theme)
    if len(selected) < TOP_THEME_COUNT:
        raise WeeklyPulseError("AI analysis does not contain three themes.")
    return selected


def _verified_quotes(analysis: Mapping[str, Any]) -> list[dict[str, str]]:
    quotes = analysis.get("verified_quotes") or analysis.get("quotes") or analysis.get("key_quotes")
    if not isinstance(quotes, list):
        raise WeeklyPulseError("AI analysis does not contain verified quotes.")
    selected: list[dict[str, str]] = []
    for item in quotes[:VERIFY_QUOTE_COUNT]:
        if isinstance(item, str):
            selected.append({"quote": item, "source": ""})
            continue
        if isinstance(item, Mapping) and item.get("quote"):
            selected.append(
                {
                    "quote": str(item["quote"]),
                    "source": str(item.get("source") or ""),
                    "rating": str(item.get("rating") or ""),
                    "date": str(item.get("date") or ""),
                }
            )
    if len(selected) < VERIFY_QUOTE_COUNT:
        raise WeeklyPulseError("AI analysis does not contain three verified quotes.")
    return selected


def _fee_observation(analysis: Mapping[str, Any]) -> tuple[str, int, str]:
    fee_confusion = analysis.get("fee_confusion")
    if not isinstance(fee_confusion, Mapping):
        raise WeeklyPulseError("AI analysis does not contain fee-confusion findings.")
    candidate_count = int(fee_confusion.get("candidate_count", 0) or 0)
    severity = str(fee_confusion.get("severity") or "unknown").strip()
    ai_summary = str(fee_confusion.get("ai_summary") or "").strip()
    if ai_summary:
        observation = (
            f"Fee-related keyword candidates: {candidate_count} of {analysis.get('review_count', 300)} "
            f"sample reviews (severity: {severity}). These are keyword candidates, not confirmed "
            f"complaints. {ai_summary}"
        )
    else:
        observation = (
            f"Fee-related keyword candidates: {candidate_count} of {analysis.get('review_count', 300)} "
            f"sample reviews (severity: {severity}). These are keyword candidates, not confirmed "
            "complaints."
        )
    return observation, candidate_count, severity


def _recommended_actions(themes: list[str]) -> list[str]:
    theme_text = " ".join(theme.casefold() for theme in themes)
    actions: list[str] = []
    if "fee" in theme_text or "brokerage" in theme_text:
        actions.append("Publish a plain-language fee table before checkout and in order confirmations.")
    if "support" in theme_text:
        actions.append("Create a support runbook and escalation path for fee, deduction, and withdrawal cases.")
    if "withdraw" in theme_text or "payment" in theme_text or "balance" in theme_text:
        actions.append("Reconcile wallet, withdrawal, and order flows before the next release.")
    if "performance" in theme_text or "reliability" in theme_text or "app" in theme_text:
        actions.append("Stabilize the highest-frequency transaction journey with targeted QA and monitoring.")
    while len(actions) < 3:
        actions.append("Review the top three themes with the product team and assign owners.")
    # Keep the list deterministic and exactly three items.
    return actions[:3]


def generate_weekly_pulse(
    report_date: str | None = None,
    analysis_path: Path | None = None,
    output_path: Path | None = None,
) -> WeeklyPulseResult:
    """Generate and optionally save the Weekly Product Pulse."""
    if analysis_path is None:
        analysis_path = Path(__file__).resolve().parents[1] / "data" / "ai_analysis.json"
    if output_path is None:
        output_path = Path(__file__).resolve().parents[1] / "data" / "weekly_pulse.md"

    analysis = _load_analysis(Path(analysis_path))
    selected_date = _normalize_date(report_date)
    themes = _top_themes(analysis)
    quotes = _verified_quotes(analysis)
    fee_observation, candidate_count, _severity = _fee_observation(analysis)
    actions = _recommended_actions(themes)
    sample_size = int(analysis.get("review_count") or 0) or 300
    total_review_count = 12680

    report_lines = [
        "# Weekly Product Pulse",
        "",
        f"Report date: {selected_date}",
        "",
        "Scope: findings come from a deliberately selected 300-review sample, not "
        "the full 12,680-review set.",
        "",
        "## Top 3 themes",
    ]
    for index, theme in enumerate(themes, start=1):
        report_lines.append(f"{index}. {theme}")
    report_lines.extend(
        [
            "",
            "## Verified customer quotes",
        ]
    )
    for quote in quotes:
        source = quote["source"]
        report_lines.append(f'> "{quote["quote"]}" - source: {source}')
    report_lines.extend(
        [
            "",
            "## Fee-confusion observation",
            fee_observation,
            "",
            "## Recommended actions",
        ]
    )
    for index, action in enumerate(actions, start=1):
        report_lines.append(f"{index}. {action}")
    report = "\n".join(report_lines) + "\n"
    word_count = len(report.split())
    if word_count > MAX_REPORT_WORDS:
        raise WeeklyPulseError(
            f"Generated Weekly Product Pulse is {word_count} words; maximum is {MAX_REPORT_WORDS}."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")

    return WeeklyPulseResult(
        report_date=selected_date,
        report=report,
        word_count=word_count,
        supported_themes=themes,
        verified_quotes=quotes,
        fee_observation=fee_observation,
        recommended_actions=actions,
        sample_size=sample_size,
        total_review_count=total_review_count,
    )


def generate_report(*args: Any, **kwargs: Any) -> WeeklyPulseResult:
    return generate_weekly_pulse(*args, **kwargs)


def build_weekly_pulse(*args: Any, **kwargs: Any) -> WeeklyPulseResult:
    return generate_weekly_pulse(*args, **kwargs)