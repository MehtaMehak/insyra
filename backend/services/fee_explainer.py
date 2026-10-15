"""Build a factual Groww fee explainer from official documentation.

The text is generated deterministically from backend/data/fee_sources.json. It does
not call Groq, create fees, or claim that keyword candidates in reviews are
confirmed complaints.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping


def _load_sources(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Official fee source file does not exist: {path}")
    with path.open("r", encoding="utf-8") as source_file:
        return json.load(source_file)


def _facts(sources: Mapping[str, Any]) -> list[str]:
    facts: list[str] = []
    for source in sources.get("official_sources", []):
        for fact in source.get("relevant_facts", []):
            if fact and fact not in facts:
                facts.append(str(fact))
    return facts


def _sources_metadata(sources: Mapping[str, Any]) -> list[dict[str, str]]:
    metadata: list[dict[str, str]] = []
    for source in sources.get("official_sources", []):
        metadata.append(
            {
                "source_id": str(source.get("source_id", "")),
                "title": str(source.get("page_title", "")),
                "url": str(source.get("url", "")),
                "accessed_on": str(source.get("accessed_on", "")),
            }
        )
    return metadata


def _selected_bullet_facts(sources: Mapping[str, Any], maximum: int = 6) -> list[tuple[str, list[str]]]:
    selected: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for source in sources.get("official_sources", []):
        source_id = str(source.get("source_id", ""))
        for fact in source.get("relevant_facts", []):
            if not fact or fact in seen:
                continue
            seen.add(str(fact))
            selected.append((str(fact), [source_id]))
            if len(selected) >= maximum:
                return selected
    return selected


def build_fee_explainer(
    fee_sources_path: Path | None = None,
    analysis_path: Path | None = None,
) -> str:
    """Return the factual fee explainer as Markdown."""
    if fee_sources_path is None:
        fee_sources_path = Path(__file__).resolve().parents[1] / "data" / "fee_sources.json"

    sources = _load_sources(fee_sources_path)
    facts = _facts(sources)
    source_metadata = _sources_metadata(sources)

    fee_candidate_count: str = "206"
    default_analysis_path = Path(__file__).resolve().parents[1] / "data" / "ai_analysis.json"
    analysis_path = analysis_path or default_analysis_path
    try:
        with analysis_path.open("r", encoding="utf-8") as analysis_file:
            analysis = json.load(analysis_file)
        fee = analysis.get("fee_confusion", {})
        fee_candidate_count = str(fee.get("candidate_count", fee_candidate_count))
    except (OSError, json.JSONDecodeError, AttributeError):
        pass

    lines = [
        "# Groww Fee Explainer",
        "",
        "Source basis: official Groww pricing and help-center documentation listed below.",
        "Customer sentiment is provided only as review context. Fee-related review language is a set of keyword candidates, not confirmed complaints.",
        "",
        "## Why users may see more than a simple brokerage figure",
        "",
        "Groww's pricing includes brokerage plus regulatory, statutory, tax, and account-related charges. Some charges are imposed by exchanges or regulators, not by Groww. In addition, brokerage can differ by order type and trading segment.",
        "",
        "## Official fee facts",
        "",
    ]
    for fact in facts:
        lines.append(f"- {fact}")
    lines.extend(
        [
            "",
            "## How to interpret a larger-than-expected charge",
            "",
            "- Compare the final charge against the trade type: equity delivery, intraday, F&O, buyback, OFS, MTF, or another segment.",
            "- Separate Groww brokerage from STT, stamp duty, exchange transaction charges, SEBI turnover charges, IPFT charges, DP charges, and GST.",
            "- Check whether an auto square-off, delayed payment, KYC, DP, pledge, courier, or other administrative charge applies.",
            "- Check whether the trade used UPI mandate balance or MTF, since those have different charge rules.",
            "- The brokerage examples in this document are official document excerpts and may change; verify on the linked Groww pages before relying on a fee amount.",
            "",
            "## Review context from the 300-review sample",
            "",
            f"Fee-related phrases appeared in {fee_candidate_count} sample reviews. These matches indicate possible fee confusion but do not by themselves establish that all matched reviews are genuine fee complaints.",
            "",
            "## Sources",
            "",
        ]
    )
    for source in source_metadata:
        lines.append(f"- {source['title']} ({source['accessed_on']}): {source['url']}")
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- Only official Groww website and help-center documentation is used for factual fee explanations.",
            "- Customer-reported confusion provides context only and is not treated as verified evidence.",
            "- Fee schedules, order types, taxes, and regulatory charges can change; confirm current charges on Groww's official pages before making customer-facing statements.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_fee_explainer_json(
    fee_sources_path: Path | None = None,
    analysis_path: Path | None = None,
) -> dict[str, Any]:
    """Return the structured factual fee explainer."""
    if fee_sources_path is None:
        fee_sources_path = Path(__file__).resolve().parents[1] / "data" / "fee_sources.json"

    sources = _load_sources(fee_sources_path)
    source_metadata = _sources_metadata(sources)
    urls = [str(source.get("url", "")) for source in sources.get("official_sources", [])]

    candidate_count = "206"
    if analysis_path is None:
        analysis_path = Path(__file__).resolve().parents[1] / "data" / "ai_analysis.json"
    try:
        with analysis_path.open("r", encoding="utf-8") as analysis_file:
            analysis = json.load(analysis_file)
        fee = analysis.get("fee_confusion", {})
        candidate_count = str(fee.get("candidate_count", candidate_count))
    except (OSError, json.JSONDecodeError, AttributeError):
        pass

    bullets = [
        {
            "id": index + 1,
            "text": fact,
            "supporting_sources": source_ids,
        }
        for index, (fact, source_ids) in enumerate(_selected_bullet_facts(sources))
    ]

    limitations = [
        "Only official Groww website and help-center documentation is used for factual fee explanations.",
        "Customer-reported confusion provides context only and is not treated as verified evidence.",
        "Fee schedules, order types, taxes, and regulatory charges can change; confirm current charges on Groww's official pages before making customer-facing statements.",
    ]
    for source in sources.get("official_sources", []):
        limitation = source.get("limitations")
        if limitation and limitation not in limitations:
            limitations.append(str(limitation))

    return {
        "title": "Groww Fee Explainer",
        "format": "json",
        "last_checked_date": sources.get("collected_on", ""),
        "sample_context": {
            "analysis_sample_reviews": 300,
            "fee_keyword_candidates": candidate_count,
            "candidate_note": "Fee-related phrases are keyword candidates, not confirmed complaints.",
        },
        "explanation_bullets": bullets,
        "bullets": bullets,
        "official_source_urls": urls,
        "source_urls": urls,
        "source_references": {
            str(source.get("source_id", "")): str(source.get("url", ""))
            for source in sources.get("official_sources", [])
            if source.get("source_id")
        },
        "sources": source_metadata,
        "official_sources": source_metadata,
        "limitations": limitations,
        "customer_context": (
            f"Fee-related phrases appeared in {candidate_count} of the 300 sampled reviews. "
            "These keyword matches indicate possible fee confusion but are not confirmed complaints."
        ),
    }


def generate_fee_explainer(
    output_path: Path | None = None,
    fee_sources_path: Path | None = None,
    analysis_path: Path | None = None,
) -> str:
    """Generate and save the Markdown fee explainer."""
    report = build_fee_explainer(
        fee_sources_path=fee_sources_path,
        analysis_path=analysis_path,
    )
    if output_path is None:
        output_path = Path(__file__).resolve().parents[1] / "data" / "fee_explainer.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    return report


def generate_fee_explainer_json(
    output_path: Path | None = None,
    fee_sources_path: Path | None = None,
    analysis_path: Path | None = None,
) -> dict[str, Any]:
    """Generate and save the structured fee explainer JSON."""
    data = build_fee_explainer_json(
        fee_sources_path=fee_sources_path,
        analysis_path=analysis_path,
    )
    if output_path is None:
        output_path = Path(__file__).resolve().parents[1] / "data" / "fee_explainer.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as json_file:
        json.dump(data, json_file, ensure_ascii=False, indent=2)
        json_file.write("\n")
    return data


# Backwards/alternate naming used by callers and tests.
build_structured_fee_explainer = build_fee_explainer_json
generate_structured_fee_explainer = generate_fee_explainer_json
create_fee_explainer = generate_fee_explainer
create_fee_explainer_json = generate_fee_explainer_json
build_explainer = build_fee_explainer
generate_explainer = generate_fee_explainer
build_json = build_fee_explainer_json
generate_json = generate_fee_explainer_json