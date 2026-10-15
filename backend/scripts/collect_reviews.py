#!/usr/bin/env python3
"""Collect genuine public Groww Android app reviews from Google Play.

This script uses the public Google Play listing for the Groww Android app. It
reads publicly visible reviews, prioritizes the most recent ones, removes exact
duplicates and empty text, and writes a UTF-8 CSV. It does not invent, rewrite,
or alter review text.

App ID verified for the public Google Play listing:
    com.nextbillion.groww
Listing URL:
    https://play.google.com/store/apps/details?id=com.nextbillion.groww

Access notes:
    * This script only reads publicly accessible reviews. It does not log in,
      bypass paywalls, unlock hidden reviews, or otherwise circumvent Google
      Play restrictions.
    * Google Play is not a stable data API. The underlying library may stop
      working if Google changes its pages or protections. Results depend on
      network access and Google Play availability.
    * Automated collection may be subject to Google Play's Terms of Service and
      rate limits. Use modest request rates and review those terms before
      running this script at scale.
    * If collection fails, the script reports the error and does not create
      synthetic review data.

Installation:
    python -m pip install google-play-scraper

Execution (from the project root):
    python backend/scripts/collect_reviews.py

Optional arguments:
    python backend/scripts/collect_reviews.py --weeks 12
    python backend/scripts/collect_reviews.py --output backend/data/groww_reviews.csv
    python backend/scripts/collect_reviews.py --max-reviews 500

The script automatically writes backend/data/groww_reviews.csv by default.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


APP_ID = "com.nextbillion.groww"
APP_URL = f"https://play.google.com/store/apps/details?id={APP_ID}"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "groww_reviews.csv"
CSV_HEADERS = ["date", "review", "rating", "source"]

PAGE_SIZE = 100
MAX_RETRIES = 5
BASE_RETRY_DELAY_SECONDS = 2.0
PAGE_DELAY_SECONDS = 1.0
MAX_RETRY_DELAY_SECONDS = 60.0


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect genuine public Groww Android reviews from Google Play."
    )
    parser.add_argument(
        "--app-id",
        default=APP_ID,
        help="Google Play application ID (default: com.nextbillion.groww).",
    )
    parser.add_argument(
        "--lang",
        default="en",
        help="Language code used for the Google Play request (default: en).",
    )
    parser.add_argument(
        "--country",
        default="in",
        help="Country code used for the Google Play request (default: in).",
    )
    parser.add_argument(
        "--weeks",
        type=int,
        default=12,
        help="Only keep reviews from this many recent weeks (default: 12).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output CSV path (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--max-reviews",
        type=int,
        default=0,
        help="Optional maximum number of reviews to write; 0 means no limit (default: 0).",
    )
    return parser.parse_args(argv)


def retry_delay(attempt: int) -> float:
    """Exponential backoff with jitter, capped for politeness and retry safety."""
    delay = min(MAX_RETRY_DELAY_SECONDS, BASE_RETRY_DELAY_SECONDS * (2 ** attempt))
    return delay + random.uniform(0.0, 1.0)


def load_google_play_scraper():
    """Import the optional dependency with a clear, actionable error message."""
    try:
        from google_play_scraper import Sort, reviews  # noqa: WPS433

        return Sort, reviews
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency 'google-play-scraper'. "
            "Install it with: python -m pip install google-play-scraper"
        ) from exc


def fetch_page(
    reviews_func,
    app_id: str,
    lang: str,
    country: str,
    sort,
    continuation_token: Any,
) -> tuple[list[dict[str, Any]], Any]:
    """Fetch one page of reviews, retrying transient/network failures."""
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            result, token = reviews_func(
                app_id,
                lang=lang,
                country=country,
                sort=sort,
                count=PAGE_SIZE,
                continuation_token=continuation_token,
            )
            if not isinstance(result, list):
                raise RuntimeError("Unexpected Google Play response format.")
            return result, token
        except Exception as exc:  # Network, parsing, HTTP, and library errors.
            last_error = exc
            if attempt + 1 < MAX_RETRIES:
                delay = retry_delay(attempt)
                print(
                    f"Request failed ({exc!r}); retrying in {delay:.1f}s "
                    f"({attempt + 2}/{MAX_RETRIES})...",
                    file=sys.stderr,
                )
                time.sleep(delay)
    raise RuntimeError(f"Unable to fetch Google Play reviews: {last_error!r}") from last_error


def normalize_date(value: Any) -> datetime:
    """Convert review dates to timezone-aware datetimes without changing intent."""
    if isinstance(value, datetime):
        review_at = value
    else:
        raise ValueError(f"Review is missing a valid date: {value!r}")
    if review_at.tzinfo is None:
        review_at = review_at.replace(tzinfo=timezone.utc)
    return review_at


def dedupe_key(item: dict[str, Any], normalized_text: str) -> tuple[str, ...]:
    """Use the stable Google Play review ID; fall back to an exact record key."""
    review_id = item.get("reviewId")
    if review_id:
        return ("id", str(review_id))
    review_at = normalize_date(item.get("at"))
    return (
        "record",
        review_at.isoformat(),
        str(item.get("score")),
        normalized_text,
    )


def collect_reviews(args: argparse.Namespace) -> list[dict[str, Any]]:
    Sort, reviews_func = load_google_play_scraper()
    sort_newest = Sort.NEWEST

    cutoff = datetime.now(timezone.utc) - timedelta(weeks=args.weeks)
    print(
        f"Collecting public {args.app_id} reviews newer than "
        f"{cutoff.date().isoformat()} (last {args.weeks} weeks).",
        file=sys.stderr,
    )

    collected: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    token: Any = None
    reached_cutoff = False

    while not reached_cutoff:
        batch, token = fetch_page(
            reviews_func,
            args.app_id,
            args.lang,
            args.country,
            sort_newest,
            token,
        )

        if not batch:
            break

        in_range_count = 0
        for item in batch:
            raw_content = item.get("content")
            content = raw_content if isinstance(raw_content, str) else ""
            if not content.strip():
                continue

            try:
                review_at = normalize_date(item.get("at"))
            except (TypeError, ValueError):
                continue

            if review_at < cutoff:
                reached_cutoff = True
                continue

            in_range_count += 1
            key = dedupe_key(item, content)
            if key in seen:
                continue
            seen.add(key)

            score = item.get("score")
            review_id = item.get("reviewId")
            source = APP_URL if not review_id else f"{APP_URL}&reviewId={review_id}"

            collected.append(
                {
                    "date": review_at.date().isoformat(),
                    "review": content,
                    "rating": score if score is not None else "",
                    "source": source,
                }
            )

            if args.max_reviews and len(collected) >= args.max_reviews:
                reached_cutoff = True
                break

        print(
            f"Fetched {len(batch)} reviews; kept {in_range_count} in range; "
            f"total unique kept: {len(collected)}.",
            file=sys.stderr,
        )

        if reached_cutoff or not token:
            break
        time.sleep(PAGE_DELAY_SECONDS)

    return collected


def write_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file, fieldnames=CSV_HEADERS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()

    if args.weeks <= 0:
        print("--weeks must be a positive integer.", file=sys.stderr)
        return 2
    if args.max_reviews < 0:
        print("--max-reviews cannot be negative.", file=sys.stderr)
        return 2

    collected_rows: list[dict[str, Any]] = []
    failed = False

    try:
        collected_rows = collect_reviews(args)
    except Exception as exc:  # Graceful handling for network/service failures.
        failed = True
        print(f"Review collection failed: {exc!r}", file=sys.stderr)

    if collected_rows:
        try:
            write_csv(collected_rows, args.output)
            print(
                f"Wrote {len(collected_rows)} genuine reviews to "
                f"{args.output.resolve()}"
            )
        except OSError as exc:
            print(f"Failed to write output CSV: {exc!r}", file=sys.stderr)
            return 1
    elif not failed:
        # Create a header-only file for a successful but empty collection.
        try:
            write_csv([], args.output)
            print(
                f"No reviews found in the last {args.weeks} weeks. "
                f"Wrote header-only CSV to {args.output.resolve()}"
            )
        except OSError as exc:
            print(f"Failed to write output CSV: {exc!r}", file=sys.stderr)
            return 1
    else:
        print("No reviews were written because collection failed.", file=sys.stderr)
        return 1

    if failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
