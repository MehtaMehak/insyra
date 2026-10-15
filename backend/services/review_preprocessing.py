"""Prepare a reproducible, traceable review sample for future AI analysis.

This module intentionally performs only data preparation. It does not call Groq
or produce any AI conclusions. The original review data is read but never
modified; duplicate removal and filtering are applied only to the analysis
sample written to backend/data/analysis_sample.csv.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SOURCE_HEADERS = ["date", "review", "rating", "source"]
SAMPLE_HEADERS = ["date", "review", "rating", "source"]
DEFAULT_INPUT = Path(__file__).resolve().parents[1] / "data" / "groww_reviews.csv"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "analysis_sample.csv"
DEFAULT_MAX_SAMPLE = 300
DEFAULT_SEED = 42

# Transparent lexical markers used to identify possible fee/charge feedback.
# A match is only a candidate: the term may appear in a positive, neutral, or
# questioning context and must be interpreted separately in later analysis.
FEE_KEYWORDS: tuple[str, ...] = (
    "fee",
    "fees",
    "charge",
    "charges",
    "brokerage",
    "deduction",
    "deducted",
    "deduct",
    "amc",
    "annual maintenance charge",
    "account maintenance",
    "commission",
    "hidden cost",
    "hidden charge",
    "platform fee",
    "platform charge",
    "stamp duty",
    "gst",
    "tax",
    "penalty",
    "inactivity",
    "subscription",
    "transaction charge",
    "cost",
)

# A small generic informative signal. Reviews are not discarded for being
# short, but longer text is preferred during stratified selection.
MIN_INFORMATIVE_LENGTH = 1


@dataclass(frozen=True)
class ReviewRecord:
    """A normalized, traceable review row."""

    date: str
    review: str
    rating: str
    source: str

    def as_dict(self) -> dict[str, str]:
        return {
            "date": self.date,
            "review": self.review,
            "rating": self.rating,
            "source": self.source,
        }


def normalize_rating(value: Any) -> str:
    """Normalize a rating to a stable string while preserving the original."""
    if value is None:
        return ""
    return str(value).strip()


def load_reviews(input_path: Path) -> list[ReviewRecord]:
    """Load and validate the source review CSV."""
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input review file does not exist: {input_path}")

    with input_path.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        fieldnames = reader.fieldnames or []
        missing = [column for column in SOURCE_HEADERS if column not in fieldnames]
        if missing:
            raise ValueError(
                "Input CSV is missing required columns: " + ", ".join(missing)
            )
        rows = [
            ReviewRecord(
                date=row.get("date") or "",
                review=row.get("review") or "",
                rating=row.get("rating") or "",
                source=row.get("source") or "",
            )
            for row in reader
        ]

    # Preserve original textual values except for the empty-review filter, which
    # is handled by callers. Do not trim review text here because that would
    # alter the customer wording.
    return rows


def is_empty_review(record: ReviewRecord) -> bool:
    """A review is empty only when its text contains no non-whitespace text."""
    return not record.review.strip()


def deduplicate_exact_texts(records: Iterable[ReviewRecord]) -> list[ReviewRecord]:
    """Remove exact duplicate review texts, keeping the first occurrence."""
    unique: list[ReviewRecord] = []
    seen: set[str] = set()
    for record in records:
        if record.review in seen:
            continue
        seen.add(record.review)
        unique.append(record)
    return unique


def matched_fee_terms(text: str) -> list[str]:
    """Return fee-related terms found in a review, transparently."""
    normalized = text.casefold()
    terms: list[str] = []
    for term in FEE_KEYWORDS:
        if " " in term:
            if term in normalized:
                terms.append(term)
        else:
            # Word boundaries keep this lexical and explainable.
            if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", normalized):
                terms.append(term)
    return terms


def is_fee_keyword_candidate(text: str) -> bool:
    return bool(matched_fee_terms(text))


def informative_length(record: ReviewRecord) -> int:
    return len(record.review.strip())


def rating_group(record: ReviewRecord) -> str:
    """Bucket a rating into a stable stratification group."""
    rating = normalize_rating(record.rating)
    if rating in {"1", "2", "3", "4", "5"}:
        return rating
    return "other"


def _sort_key(record: ReviewRecord) -> tuple:
    fee_flag = 0 if is_fee_keyword_candidate(record.review) else 1
    length = informative_length(record)
    # Higher length and fee relevance are preferred; source/date provide
    # deterministic tie-breaking.
    return (fee_flag, -length, record.source, record.date, record.review)


def stratified_sample(
    records: Iterable[ReviewRecord],
    max_size: int = DEFAULT_MAX_SAMPLE,
) -> list[ReviewRecord]:
    """Build a deterministic, stratified sample across rating groups.

    Ratings 1-3 receive roughly twice the per-group share of ratings 4-5, and
    fee-keyword candidates are preferred within each rating group. Any leftover
    slots are filled in rating order 1, 2, 3, 4, 5, which keeps lower-rated
    feedback additionally represented when data is available.
    """
    if max_size < 0:
        raise ValueError("max_size cannot be negative")
    if max_size == 0:
        return []

    candidates = list(records)
    if not candidates:
        return []

    # Deterministic grouping and ordering make the sample reproducible.
    groups: dict[str, list[ReviewRecord]] = defaultdict(list)
    for record in candidates:
        groups[rating_group(record)].append(record)

    for group_records in groups.values():
        group_records.sort(key=_sort_key)

    standard_groups = ["1", "2", "3", "4", "5"]
    # 3 low-star groups receive 2 shares; 2 high-star groups receive 1 share.
    shares = {
        "1": 2,
        "2": 2,
        "3": 2,
        "4": 1,
        "5": 1,
    }
    total_shares = sum(shares[group] for group in standard_groups)
    base_unit = max_size // total_shares
    quotas: dict[str, int] = {
        group: base_unit * shares[group] for group in standard_groups
    }
    quotas["5"] += max_size - sum(quotas.values())

    # Include non-standard ratings only after the primary 1-5 stratification.
    other_available = len(groups.get("other", []))
    other_quota = min(other_available, max(0, max_size // 10))
    quotas["other"] = other_quota
    # Keep the primary rating quotas authoritative by reducing the small
    # "other" allocation from the highest rating group if needed.
    if sum(quotas.values()) > max_size:
        quotas["5"] -= sum(quotas.values()) - max_size

    selected: list[ReviewRecord] = []
    selected_keys: set[tuple[str, str, str, str]] = set()

    def add_record(record: ReviewRecord) -> bool:
        key = (record.date, record.review, record.rating, record.source)
        if key in selected_keys or len(selected) >= max_size:
            return False
        selected.append(record)
        selected_keys.add(key)
        return True

    # Fill each rating group up to its quota.
    for group in standard_groups + ["other"]:
        for record in groups.get(group, []):
            if len(selected) >= max_size:
                break
            if len([r for r in selected if rating_group(r) == group]) >= quotas.get(group, 0):
                break
            add_record(record)

    # Fill any remaining slots, prioritizing low ratings and then all groups.
    if len(selected) < max_size:
        fill_order = ["1", "2", "3", "other", "4", "5"]
        for group in fill_order:
            for record in groups.get(group, []):
                if len(selected) >= max_size:
                    break
                add_record(record)

    return selected


def filter_non_empty(records: Iterable[ReviewRecord]) -> list[ReviewRecord]:
    return [record for record in records if not is_empty_review(record)]


def prepare_sample(
    input_path: Path = DEFAULT_INPUT,
    output_path: Path = DEFAULT_OUTPUT,
    max_size: int = DEFAULT_MAX_SAMPLE,
) -> dict[str, Any]:
    """Prepare and write the analysis sample, returning summary statistics."""
    input_path = Path(input_path)
    output_path = Path(output_path)
    all_reviews = load_reviews(input_path)
    non_empty = filter_non_empty(all_reviews)
    unique_texts = deduplicate_exact_texts(non_empty)
    fee_candidates = [record for record in non_empty if is_fee_keyword_candidate(record.review)]
    sample = stratified_sample(unique_texts, max_size=max_size)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=SAMPLE_HEADERS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(record.as_dict() for record in sample)

    sample_rating_distribution = Counter(record.rating for record in sample)
    all_source_ratings = Counter(record.rating for record in non_empty)

    return {
        "input_path": str(input_path),
        "output_path": str(output_path),
        "total_rows": len(all_reviews),
        "empty_reviews": len(all_reviews) - len(non_empty),
        "non_empty_rows": len(non_empty),
        "unique_review_texts": len(unique_texts),
        "duplicate_texts_removed": len(non_empty) - len(unique_texts),
        "fee_keyword_candidates": len(fee_candidates),
        "sample_count": len(sample),
        "sample_rating_distribution": dict(sample_rating_distribution),
        "source_rating_distribution": dict(all_source_ratings),
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare a reproducible review sample for future AI analysis."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-size", type=int, default=DEFAULT_MAX_SAMPLE)
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    try:
        summary = prepare_sample(args.input, args.output, args.max_size)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"Failed to prepare analysis sample: {exc}", file=sys.stderr)
        return 1

    print(f"Total rows read: {summary['total_rows']}")
    print(f"Empty reviews excluded: {summary['empty_reviews']}")
    print(f"Non-empty review rows: {summary['non_empty_rows']}")
    print(f"Unique review texts: {summary['unique_review_texts']}")
    print(f"Exact duplicate texts removed for sample: {summary['duplicate_texts_removed']}")
    print(f"Fee-keyword candidate reviews: {summary['fee_keyword_candidates']}")
    print(f"Sample count: {summary['sample_count']}")
    print(f"Sample rating distribution: {summary['sample_rating_distribution']}")
    print(f"Source rating distribution (non-empty): {summary['source_rating_distribution']}")
    print(f"Sample written to: {summary['output_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
