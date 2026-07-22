from __future__ import annotations

import unittest
from unittest.mock import patch

import list_sources_handler
import publisher_handler
from kendo_keiko.models import Organization


class FakeContext:
    aws_request_id = "request-123"


class ListSourcesHandlerTests(unittest.TestCase):
    def test_lists_only_enabled_sources(self) -> None:
        enabled = Organization(
            organization_id="enabled",
            name="有効団体",
            area="東京都",
            website_url="https://example.com/enabled",
            source_type="official_site",
            scraper_type="enabled",
            scraper_enabled=True,
            event_type="open_keiko",
        )
        disabled = Organization(
            organization_id="disabled",
            name="無効団体",
            area="東京都",
            website_url="https://example.com/disabled",
            source_type="official_site",
            scraper_type="disabled",
            scraper_enabled=False,
            event_type="open_keiko",
        )

        with patch.object(
            list_sources_handler,
            "load_organizations",
            return_value=[enabled, disabled],
        ):
            result = list_sources_handler.lambda_handler(
                {
                    "from_date": "2026-07-22",
                    "events_bucket": "example-bucket",
                },
                FakeContext(),
            )

        self.assertEqual("request-123", result["run_id"])
        self.assertEqual(
            [{"organization_id": "enabled"}],
            result["sources"],
        )
        self.assertEqual("example-bucket", result["events_bucket"])


class PublisherHandlerTests(unittest.TestCase):
    def test_skips_publish_when_all_sources_failed(self) -> None:
        with self.assertRaises(publisher_handler.AllSourcesFailedError):
            publisher_handler.lambda_handler(
                {
                    "scrape_results": [
                        {"organization_id": "a", "status": "failure"},
                        {"organization_id": "b", "status": "failure"},
                    ]
                },
                None,
            )

    def test_rejects_unknown_status(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown scrape result status"):
            publisher_handler.lambda_handler(
                {
                    "scrape_results": [
                        {"organization_id": "a", "status": "unknown"}
                    ]
                },
                None,
            )

    def test_publishes_when_at_least_one_source_did_not_fail(self) -> None:
        publish_result = {
            "s3_published": True,
            "event_count": 10,
            "index_published": True,
            "sitemap_published": True,
        }
        with patch.object(
            publisher_handler,
            "publish_public_site",
            return_value=publish_result,
        ) as publish:
            result = publisher_handler.lambda_handler(
                {
                    "run_id": "run-1",
                    "table_name": "KendoKeikoEvents",
                    "region": "ap-northeast-1",
                    "from_date": "2026-07-22",
                    "events_bucket": "example-bucket",
                    "scrape_results": [
                        {"organization_id": "a", "status": "success"},
                        {"organization_id": "b", "status": "warning"},
                        {"organization_id": "c", "status": "failure"},
                    ],
                },
                None,
            )

        self.assertEqual(1, result["success_count"])
        self.assertEqual(1, result["warning_count"])
        self.assertEqual(1, result["failure_count"])
        self.assertTrue(result["s3_published"])
        publish.assert_called_once()


if __name__ == "__main__":
    unittest.main()
