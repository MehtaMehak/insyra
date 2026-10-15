# Groww Review Collector

Collects genuine public Android app reviews for Groww from Google Play.

## Verified app

- App: Groww Stocks, Mutual Fund, IPO
- Google Play package ID: `com.nextbillion.groww`
- Listing: https://play.google.com/store/apps/details?id=com.nextbillion.groww

## Install

From the project root:

```bash
python -m pip install google-play-scraper
```

## Run

```bash
python backend/scripts/collect_reviews.py
```

Optional examples:

```bash
python backend/scripts/collect_reviews.py --weeks 12
python backend/scripts/collect_reviews.py --output backend/data/groww_reviews.csv
python backend/scripts/collect_reviews.py --max-reviews 500
```

Output:

```text
backend/data/groww_reviews.csv
```

CSV columns:

```text
date,review,rating,source
```

## Access limitations

- The collector reads only publicly visible reviews and does not bypass login,
  paywalls, or other restrictions.
- Google Play is not a stable public data API. If Google changes the page,
  protection, or availability, collection may fail.
- Automated collection may be subject to Google Play's terms and rate limits.
  Collection uses delayed, best-effort requests and stops gracefully on errors.
- Reviews are not altered, rewritten, paraphrased, or fabricated. Empty review
  text is removed and duplicate records are skipped.
- If network access is unavailable, the command will fail and no fake reviews will
  be generated.