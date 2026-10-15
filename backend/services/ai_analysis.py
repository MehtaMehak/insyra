"""Evidence-grounded AI analysis prepared from validated review samples.

The service uses review text only as evidence for themes, quotes, and fee-related
observations. It does not invent customer feedback and verifies every returned
quote against the original review text.

No analysis is run at import time. The service accepts an optional Groq client
so tests can mock the model boundary without making network calls.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from services.review_preprocessing import matched_fee_terms

try:
    from services.groq_client import GroqClient, GroqClientError
except ImportError:  # pragma: no cover - supports alternate test invocation
    from groq_client import GroqClient, GroqClientError  # type: ignore

try:
    from services.review_preprocessing import ReviewRecord
except ImportError:  # pragma: no cover
    from review_preprocessing import ReviewRecord  # type: ignore


DEFAULT_MAX_THEMES = 5
DEFAULT_MAX_QUOTES = 3
MAX_PROMPT_REVIEW_CHARS = 160
MAX_PROMPT_REVIEWS = 30


class AIAnalysisError(Exception):
    """Raised when AI analysis cannot be produced or validated safely."""


@dataclass(frozen=True)
class ReviewEvidence:
    """A normalized review used as AI evidence."""

    date: str
    review: str
    rating: str
    source: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ReviewEvidence":
        return cls(
            date=str(value.get("date", "") or ""),
            review=str(value.get("review", "") or ""),
            rating=str(value.get("rating", "") or ""),
            source=str(value.get("source", "") or ""),
        )

    def compact(self) -> dict[str, str]:
        return {
            "date": self.date,
            "review": self.review,
            "rating": self.rating,
            "source": self.source,
        }


@dataclass
class FeeConfusionResult:
    """Deterministic fee/confusion signal derived from public review text."""

    detected: bool
    candidate_count: int
    unique_candidate_texts: int
    candidates: list[dict[str, Any]] = field(default_factory=list)
    severity: str = "low"
    explanation: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "candidate_count": self.candidate_count,
            "unique_candidate_texts": self.unique_candidate_texts,
            "candidates": self.candidates,
            "severity": self.severity,
            "explanation": self.explanation,
        }


@dataclass
class AnalysisResult:
    """Structured, evidence-grounded analysis output."""

    summary: str
    themes: list[dict[str, Any]]
    verified_quotes: list[dict[str, Any]]
    fee_confusion: dict[str, Any]
    review_count: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "themes": self.themes,
            "verified_quotes": self.verified_quotes,
            "quotes": self.verified_quotes,
            "key_quotes": self.verified_quotes,
            "fee_confusion": self.fee_confusion,
            "review_count": self.review_count,
            "metadata": self.metadata,
        }


class EvidenceGroundedReviewAnalyzer:
    """Analyze review evidence with a Groq model while verifying citations."""

    def __init__(
        self,
        client: Any | None = None,
        max_themes: int = DEFAULT_MAX_THEMES,
        max_quotes: int = DEFAULT_MAX_QUOTES,
        model: str | None = None,
    ) -> None:
        self._client = client
        self.max_themes = max(0, int(max_themes))
        self.max_quotes = max(0, int(max_quotes))
        self.model = model

    def get_client(self) -> Any:
        if self._client is not None:
            return self._client
        client = GroqClient.from_env()
        if self.model and hasattr(client, "config"):
            client.config.model = self.model  # type: ignore[attr-defined]
        self._client = client
        return self._client

    def detect_fee_confusion(
        self,
        records: Iterable[Any],
        max_examples: int = 5,
    ) -> FeeConfusionResult:
        evidence = [_coerce_review(record) for record in records]
        candidates: list[dict[str, Any]] = []
        seen_texts: set[str] = set()
        for record in evidence:
            if not record.review.strip():
                continue
            terms = matched_fee_terms(record.review)
            if not terms:
                continue
            candidates.append(
                {
                    "date": record.date,
                    "review": record.review,
                    "rating": record.rating,
                    "source": record.source,
                    "matched_terms": terms,
                }
            )
            seen_texts.add(record.review)

        total = len(evidence)
        ratio = (len(candidates) / total) if total else 0.0
        negative_feedback = [c for c in candidates if str(c["rating"]).strip() in {"1", "2", "3"}]
        negative_ratio = (len(negative_feedback) / len(candidates)) if candidates else 0.0

        if not candidates:
            severity = "none"
        elif ratio >= 0.2 or negative_ratio >= 0.5:
            severity = "high"
        elif ratio >= 0.1 or negative_ratio >= 0.33:
            severity = "medium"
        else:
            severity = "low"

        explanation = (
            "Fee-related terms were used only as candidates for possible fee confusion. "
            "Matches may appear in positive, neutral, or questioning contexts and are "
            "not assumed to be genuine fee complaints."
        )
        return FeeConfusionResult(
            detected=bool(candidates),
            candidate_count=len(candidates),
            unique_candidate_texts=len(seen_texts),
            candidates=candidates[:max(0, max_examples)],
            severity=severity,
            explanation=explanation,
        )

    def verify_quotes(
        self,
        records: Iterable[Any],
        quote_candidates: Iterable[Any],
        max_quotes: int | None = None,
    ) -> list[dict[str, Any]]:
        evidence = [_coerce_review(record) for record in records]
        limit = self.max_quotes if max_quotes is None else max(0, int(max_quotes))
        verified: list[dict[str, Any]] = []
        used_quotes: set[str] = set()

        for candidate in quote_candidates:
            text = _quote_text(candidate)
            if not text or text in used_quotes:
                continue
            for record in evidence:
                matched_quote = _find_verified_quote(record.review, text)
                if matched_quote is not None:
                    verified.append(
                        {
                            "quote": matched_quote,
                            "date": record.date,
                            "rating": record.rating,
                            "source": record.source,
                            "review": record.review,
                            "verified": True,
                        }
                    )
                    used_quotes.add(text)
                    break
            if len(verified) >= limit:
                break
        return verified

    def build_prompt(
        self,
        records: Sequence[ReviewEvidence],
        fee_result: FeeConfusionResult,
    ) -> list[dict[str, str]]:
        prompt_records = list(records)[:MAX_PROMPT_REVIEWS]
        rendered_reviews: list[str] = []
        for index, record in enumerate(prompt_records, start=1):
            review_text = record.review.replace("\n", " ").strip()
            if len(review_text) > MAX_PROMPT_REVIEW_CHARS:
                review_text = review_text[:MAX_PROMPT_REVIEW_CHARS] + "..."
            rendered_reviews.append(
                f"{index}. rating={record.rating or 'unknown'} date={record.date or 'unknown'} "
                f"source={record.source or 'unknown'} review={review_text!r}"
            )

        system = (
            "You are an evidence-grounded analyst. Return only valid JSON. "
            "Do not invent reviews, quotes, or facts. Themes and conclusions must "
            "be supported by the supplied review text. Quotes must be exact, "
            "verbatim substrings copied from the supplied reviews without "
            "ellipses, paraphrasing, or abbreviation. Produce at most "
            f"{self.max_themes} themes and no more than {self.max_quotes} quotes."
        )
        user = (
            "Analyze the following customer reviews and return JSON with this schema:\n"
            "{\n"
            '  "summary": "short grounded summary",\n'
            '  "themes": [{"theme": "...", "description": "...", '
            '"sentiment": "positive|negative|mixed|neutral", '
            '"supporting_sources": ["source..."]}],\n'
            '  "quotes": ["exact verbatim review substring with no ellipsis"],\n'
            '  "fee_confusion_summary": "short grounded explanation"\n'
            "}\n\n"
            f"Review count: {len(records)}\n"
            f"Fee-keyword candidate count: {fee_result.candidate_count}\n"
            f"Fee-keyword severity: {fee_result.severity}\n"
            f"Reviews shown below: {len(prompt_records)} of {len(records)}\n\n"
            "Never abbreviate a quote with ellipsis (\"...\"). "
            "Copy quotes exactly or omit them.\n\n"
            "Reviews:\n" + "\n".join(rendered_reviews)
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def _analyze(
        self,
        records: Iterable[Any],
        *,
        groq_client: Any | None = None,
        **_ignored: Any,
    ) -> AnalysisResult:
        evidence = [_coerce_review(record) for record in records]
        non_empty = [record for record in evidence if record.review.strip()]
        fee_result = self.detect_fee_confusion(non_empty)

        client = groq_client if groq_client is not None else self.get_client()
        messages = self.build_prompt(non_empty, fee_result)
        try:
            raw_response = client.chat_completion(
                messages,
                temperature=0.0,
                max_tokens=1536,
                response_format={"type": "json_object"},
                reasoning_effort="low",
            )
        except GroqClientError as exc:
            raise AIAnalysisError(f"Unable to complete AI analysis request: {exc}") from None

        content = _response_text(raw_response)
        parsed = _parse_json_response(content)

        ai_themes = parsed.get("themes", [])
        if not isinstance(ai_themes, list):
            ai_themes = []
        themes: list[dict[str, Any]] = []
        for item in ai_themes[: self.max_themes]:
            if not isinstance(item, Mapping):
                continue
            theme_name = str(item.get("theme") or item.get("name") or item.get("title") or "").strip()
            if not theme_name:
                continue
            source_memory = item.get("supporting_sources")
            if not isinstance(source_memory, list):
                source_memory = []
            themes.append(
                {
                    "theme": theme_name,
                    "description": str(item.get("description") or item.get("summary") or "").strip(),
                    "sentiment": str(item.get("sentiment") or "unknown").strip(),
                    "supporting_sources": [str(value) for value in source_memory],
                }
            )

        quote_candidates = parsed.get("quotes", [])
        if not isinstance(quote_candidates, list):
            quote_candidates = []
        quotes = self.verify_quotes(non_empty, quote_candidates)

        summary = str(parsed.get("summary", "") or "").strip()
        if not summary:
            summary = (
                f"Grounded analysis of {len(non_empty)} reviews. "
                f"Fee-related keyword candidates: {fee_result.candidate_count}."
            )

        fee_confusion = fee_result.as_dict()
        if parsed.get("fee_confusion_summary"):
            fee_confusion["ai_summary"] = str(parsed["fee_confusion_summary"]).strip()

        return AnalysisResult(
            summary=summary,
            themes=themes,
            verified_quotes=quotes,
            fee_confusion=fee_confusion,
            review_count=len(non_empty),
            metadata={
                "max_themes": self.max_themes,
                "max_quotes": self.max_quotes,
                "total_input_reviews": len(evidence),
                "non_empty_reviews": len(non_empty),
                "model": getattr(client, "model", None),
            },
        )

    def analyze(self, records: Iterable[Any], **kwargs: Any) -> dict[str, Any]:
        groq_client = kwargs.pop("groq_client", kwargs.pop("client", None))
        if "max_themes" in kwargs:
            self.max_themes = max(0, int(kwargs.pop("max_themes")))
        if "max_quotes" in kwargs:
            self.max_quotes = max(0, int(kwargs.pop("max_quotes")))
        result = self._analyze(records, groq_client=groq_client)
        return result.as_dict()

    def analyze_records(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.analyze(*args, **kwargs)

    def analyze_reviews(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.analyze(*args, **kwargs)

    def analyze_sample(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.analyze(*args, **kwargs)

    def analyze_with_client(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.analyze(*args, **kwargs)

    def run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.analyze(*args, **kwargs)

    def __call__(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.analyze(*args, **kwargs)

    def analyze_file(self, path: str | Path, **kwargs: Any) -> dict[str, Any]:
        records = _load_review_file(Path(path))
        return self.analyze(records, **kwargs)

    @property
    def fee_confusion(self) -> Any:
        return self.detect_fee_confusion


# Module-level convenience functions.
def _coerce_review(value: Any) -> ReviewEvidence:
    if isinstance(value, ReviewEvidence):
        return value
    if isinstance(value, Mapping):
        return ReviewEvidence.from_mapping(value)
    if isinstance(value, str):
        raise AIAnalysisError("Review value must be a mapping or ReviewEvidence.")
    # Support mapping-like review preprocessing records.
    if hasattr(value, "date") and hasattr(value, "review"):
        return ReviewEvidence(
            date=str(getattr(value, "date", "") or ""),
            review=str(getattr(value, "review", "") or ""),
            rating=str(getattr(value, "rating", "") or ""),
            source=str(getattr(value, "source", "") or ""),
        )
    raise AIAnalysisError(f"Unsupported review value: {type(value)!r}")


def _quote_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        for key in ("quote", "text", "value"):
            if key in value and isinstance(value[key], str):
                return value[key]
    return ""


def _ascii_quotes(value: str) -> str:
    return (
        value.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )


def _strip_ellipsis(value: str) -> str:
    value = value.strip()
    for suffix in ("...", "…"):
        if value.endswith(suffix):
            value = value[: -len(suffix)].rstrip()
    return value


def _find_verified_quote(review: str, quote: str) -> str | None:
    """Return an exact review substring supporting an AI-generated quote."""
    if not quote or not review:
        return None
    if quote in review:
        return quote

    ascii_review = _ascii_quotes(review)
    ascii_quote = _ascii_quotes(quote)
    if ascii_quote in ascii_review:
        start = ascii_review.find(ascii_quote)
        return review[start : start + len(ascii_quote)]

    core = _strip_ellipsis(ascii_quote)
    if len(core) >= 12 and core in ascii_review:
        start = ascii_review.find(core)
        return review[start : start + len(core)]

    return None


def _response_text(raw_response: Any) -> str:
    if raw_response is None:
        return ""
    if isinstance(raw_response, str):
        return raw_response
    if hasattr(raw_response, "content"):
        return str(raw_response.content or "")
    if hasattr(raw_response, "choices"):
        try:
            return str(raw_response.choices[0].message.content or "")
        except Exception:
            pass
    if isinstance(raw_response, Mapping) and "content" in raw_response:
        return str(raw_response["content"] or "")
    return str(raw_response)


def _parse_json_response(content: str) -> Mapping[str, Any]:
    text = content.strip()
    if not text:
        raise AIAnalysisError("AI response was empty.")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise AIAnalysisError("AI response was not valid JSON.")
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            raise AIAnalysisError("AI response was not valid JSON.") from None
    if not isinstance(parsed, Mapping):
        raise AIAnalysisError("AI response JSON must be an object.")
    return parsed


def _load_review_file(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise AIAnalysisError(f"Review file does not exist: {path}")
    with path.open("r", encoding="utf-8", newline="") as csv_file:
        import csv

        reader = csv.DictReader(csv_file)
        if not reader.fieldnames or not {"date", "review", "rating", "source"}.issubset(
            set(reader.fieldnames)
        ):
            raise AIAnalysisError("Review file is missing required columns.")
        return [dict(row) for row in reader]


def analyze_reviews(records: Iterable[Any], **kwargs: Any) -> dict[str, Any]:
    analyzer = EvidenceGroundedReviewAnalyzer(
        client=kwargs.pop("groq_client", kwargs.pop("client", None)),
        max_themes=kwargs.pop("max_themes", DEFAULT_MAX_THEMES),
        max_quotes=kwargs.pop("max_quotes", DEFAULT_MAX_QUOTES),
    )
    max_themes = kwargs.pop("max_themes", None)
    max_quotes = kwargs.pop("max_quotes", None)
    if max_themes is not None:
        analyzer.max_themes = max(0, int(max_themes))
    if max_quotes is not None:
        analyzer.max_quotes = max(0, int(max_quotes))
    return analyzer.analyze(records, **kwargs)


def analyze_review_sample(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return analyze_reviews(*args, **kwargs)


def build_evidence_grounded_analysis(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return analyze_reviews(*args, **kwargs)


def detect_fee_confusion(records: Iterable[Any], **kwargs: Any) -> dict[str, Any]:
    analyzer = EvidenceGroundedReviewAnalyzer()
    return analyzer.detect_fee_confusion(records, **kwargs).as_dict()


def verify_quotes(records: Iterable[Any], quote_candidates: Iterable[Any], **kwargs: Any) -> list[dict[str, Any]]:
    analyzer = EvidenceGroundedReviewAnalyzer()
    return analyzer.verify_quotes(records, quote_candidates, **kwargs)


def analyze_sample(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return analyze_reviews(*args, **kwargs)


def analyze_file(path: str | Path, **kwargs: Any) -> dict[str, Any]:
    records = _load_review_file(Path(path))
    return analyze_reviews(records, **kwargs)


def run_analysis(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return analyze_reviews(*args, **kwargs)


analyze = analyze_reviews
run = analyze_reviews


# Class/function compatibility aliases.
GroqReviewAnalyzer = EvidenceGroundedReviewAnalyzer
ReviewAnalysisService = EvidenceGroundedReviewAnalyzer
AIAnalysisService = EvidenceGroundedReviewAnalyzer
AnalysisService = EvidenceGroundedReviewAnalyzer
ReviewAnalyzer = EvidenceGroundedReviewAnalyzer
AIEvidenceService = EvidenceGroundedReviewAnalyzer
EvidenceGroundedAnalyzer = EvidenceGroundedReviewAnalyzer