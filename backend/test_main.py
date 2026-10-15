import io
import unittest

from fastapi.testclient import TestClient

from main import app


class ReviewUploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def upload(self, filename, data, content_type="text/csv"):
        return self.client.post(
            "/api/reviews/upload",
            files={"file": (filename, io.BytesIO(data), content_type)},
        )

    def test_valid_csv_upload(self):
        data = (
            b"date,review,rating\n"
            b"2024-01-01,Great product,5\n"
            b"2024-01-02,Needs improvement,3\n"
        )
        response = self.upload("reviews.csv", data)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["filename"], "reviews.csv")
        self.assertEqual(body["total_reviews"], 2)
        self.assertEqual(len(body["preview"]), 2)
        self.assertEqual(body["preview"][0]["review"], "Great product")
        self.assertIn("message", body)

    def test_invalid_file_extension(self):
        data = b"date,review,rating\n2024-01-01,Great product,5\n"
        response = self.upload("reviews.txt", data)

        self.assertEqual(response.status_code, 400)

    def test_missing_required_column(self):
        data = b"date,comment,rating\n2024-01-01,Great product,5\n"
        response = self.upload("reviews.csv", data)

        self.assertEqual(response.status_code, 400)
        self.assertIn("review", response.json()["detail"])

    def test_empty_file(self):
        response = self.upload("reviews.csv", b"")

        self.assertEqual(response.status_code, 400)

    def test_no_review_rows(self):
        data = b"date,review,rating\n2024-01-01,,5\n\n"
        response = self.upload("reviews.csv", data)

        self.assertEqual(response.status_code, 400)

    def test_invalid_utf8(self):
        data = b"date,review,rating\n2024-01-01,\xff,5\n"
        response = self.upload("reviews.csv", data)

        self.assertEqual(response.status_code, 400)

    def test_oversized_file(self):
        data = b"x" * (5 * 1024 * 1024 + 10)
        response = self.upload("reviews.csv", data)

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
