import csv
import io
import os
import tempfile
import unittest

try:
    from services.review_preprocessing import (
        ReviewRecord,
        deduplicate_exact_texts,
        is_fee_keyword_candidate,
        matched_fee_terms,
        load_reviews,
        prepare_sample,
        stratified_sample,
    )
except ImportError:  # pragma: no cover - supports alternate test invocation
    from review_preprocessing import (  # type: ignore
        ReviewRecord,
        deduplicate_exact_texts,
        is_fee_keyword_candidate,
        matched_fee_terms,
        load_reviews,
        prepare_sample,
        stratified_sample,
    )


def make_record(review: str, rating: str = "5", date: str = "2026-10-01", source: str = "src-1") -> ReviewRecord:
    return ReviewRecord(date=date, review=review, rating=rating, source=source)


class ReviewPreprocessingTests(unittest.TestCase):
    def test_deduplication_removes_exact_duplicate_text(self):
        rows = [
            make_record("Great app", source="src-1"),
            make_record("Great app", source="src-2"),
            make_record("Needs work", source="src-3"),
        ]
        unique = deduplicate_exact_texts(rows)
        self.assertEqual(len(unique), 2)
        self.assertEqual([record.review for record in unique], ["Great app", "Needs work"])

    def test_fee_keyword_detection_is_transparent(self):
        self.assertTrue(is_fee_keyword_candidate("Brokerage and hidden cost are very high"))
        terms = matched_fee_terms("Charges include AMC, stamp duty, and GST")
        self.assertIn("charges", terms)
        self.assertIn("amc", terms)
        self.assertIn("stamp duty", terms)
        self.assertIn("gst", terms)
        self.assertFalse(is_fee_keyword_candidate("The app is fast and simple"))

    def test_stratified_sample_respects_limit(self):
        rows = []
        for rating in ("1", "2", "3", "4", "5"):
            for index in range(80):
                rows.append(make_record(f"Review {rating}-{index}", rating=rating, source=f"{rating}-{index}"))
        sample = stratified_sample(rows, max_size=30)
        self.assertEqual(len(sample), 30)
        self.assertEqual(len({record.review for record in sample}), 30)
        self.assertTrue(all(record.rating in {"1", "2", "3", "4", "5"} for record in sample))

    def test_stratified_sample_prioritizes_low_ratings(self):
        rows = []
        for rating in ("1", "2", "3", "4", "5"):
            for index in range(40):
                rows.append(make_record(f"Review {rating}-{index}", rating=rating, source=f"{rating}-{index}"))
        sample = stratified_sample(rows, max_size=40)
        low_count = sum(1 for record in sample if record.rating in {"1", "2", "3"})
        high_count = sum(1 for record in sample if record.rating in {"4", "5"})
        self.assertGreater(low_count, high_count)

    def test_date_and_rating_are_preserved(self):
        rows = [
            make_record("Fee complaint", rating="1", date="2026-09-20", source="id-1"),
            make_record("Positive feedback", rating="5", date="2026-10-01", source="id-2"),
        ]
        sample = stratified_sample(rows, max_size=2)
        by_source = {record.source: record for record in sample}
        self.assertEqual(by_source["id-1"].date, "2026-09-20")
        self.assertEqual(by_source["id-1"].rating, "1")
        self.assertEqual(by_source["id-2"].date, "2026-10-01")
        self.assertEqual(by_source["id-2"].rating, "5")

    def test_prepare_sample_is_reproducible(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = os.path.join(temp_dir, "input.csv")
            output_one = os.path.join(temp_dir, "one.csv")
            output_two = os.path.join(temp_dir, "two.csv")

            fieldnames = ["date", "review", "rating", "source"]
            data = [
                {"date": "2026-10-01", "review": "Brokerage is too high", "rating": "1", "source": "r1"},
                {"date": "2026-10-01", "review": "Brokerage is too high", "rating": "1", "source": "r2"},
                {"date": "2026-10-02", "review": "Good mutual fund experience", "rating": "5", "source": "r3"},
                {"date": "2026-10-03", "review": "AMC charge increased", "rating": "2", "source": "r4"},
            ]
            with open(input_path, "w", encoding="utf-8", newline="") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=fieldnames, lineterminator="\n")
                writer.writeheader()
                writer.writerows(data)

            first = prepare_sample(input_path, output_one, max_size=10)
            second = prepare_sample(input_path, output_two, max_size=10)

            self.assertEqual(
                {key: value for key, value in first.items() if key != "output_path"},
                {key: value for key, value in second.items() if key != "output_path"},
            )
            with open(output_one, encoding="utf-8", newline="") as f1:
                with open(output_two, encoding="utf-8", newline="") as f2:
                    self.assertEqual(f1.read(), f2.read())

            with open(output_one, encoding="utf-8", newline="") as csv_file:
                reader = csv.DictReader(csv_file)
                self.assertEqual(reader.fieldnames, ["date", "review", "rating", "source"])
                rows = list(reader)
                self.assertEqual(len(rows), 3)
                self.assertEqual(len({row["review"] for row in rows}), 3)

    def test_load_reviews_requires_source_columns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = os.path.join(temp_dir, "bad.csv")
            with open(input_path, "w", encoding="utf-8", newline="") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=["date", "review"], lineterminator="\n")
                writer.writeheader()
            with self.assertRaises(ValueError):
                load_reviews(input_path)


if __name__ == "__main__":
    unittest.main()
