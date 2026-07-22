from __future__ import annotations

import unittest
from unittest.mock import patch

import lambda_function
import kendo_keiko.publication as publication


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: list[dict] = []

    def put_object(self, **kwargs) -> None:
        self.objects.append(kwargs)


class LambdaStaticPublishTests(unittest.TestCase):
    def test_publishes_events_index_and_sitemap(self) -> None:
        fake_s3 = FakeS3Client()
        events = [
            {
                "event_id": "event-1",
                "organization_id": "tokyo",
                "organization_name": "東京都剣道連盟",
                "title": "剣道合同稽古会",
                "event_date": "2026-08-03",
                "weekday": "月",
                "start_time": "18:00",
                "end_time": "20:00",
                "venue": "東京武道館",
                "area": "東京都",
                "source_url": "https://www.tokyo-kendo.or.jp/",
            }
        ]

        with (
            patch.object(
                lambda_function,
                "run_export_events_main",
                return_value={"exit_code": 0, "stdout": "", "stderr": ""},
            ),
            patch.object(
                publication,
                "query_events_from_dynamodb",
                return_value=events,
            ),
            patch.object(
                publication.boto3,
                "client",
                return_value=fake_s3,
            ),
        ):
            response = lambda_function.lambda_handler(
                {
                    "publish_to_s3": True,
                    "publish_index_html": True,
                    "events_bucket": "example-bucket",
                    "from_date": "2026-07-21",
                },
                None,
            )

        objects = {item["Key"]: item for item in fake_s3.objects}
        self.assertEqual(
            {"events.json", "index.html", "sitemap.xml"},
            set(objects),
        )
        self.assertEqual(
            "application/json; charset=utf-8",
            objects["events.json"]["ContentType"],
        )
        self.assertEqual(
            "text/html; charset=utf-8",
            objects["index.html"]["ContentType"],
        )
        index_html = objects["index.html"]["Body"].decode("utf-8")
        self.assertIn("2026-08-03(月)", index_html)
        self.assertIn('"@type": "WebSite"', index_html)
        sitemap = objects["sitemap.xml"]["Body"].decode("utf-8")
        self.assertIn("https://kendo-keiko.com/", sitemap)
        self.assertTrue(response["s3_published"])
        self.assertTrue(response["index_published"])
        self.assertTrue(response["sitemap_published"])


if __name__ == "__main__":
    unittest.main()
