from __future__ import annotations

import datetime as dt
import unittest
from unittest.mock import Mock, patch

import requests

from kendo_keiko.models import Organization, ServiceEvent
from kendo_keiko.worker import (
    ScraperTransientError,
    run_scraper_worker,
)


class ScraperWorkerTests(unittest.TestCase):
    def make_organization(self) -> Organization:
        return Organization(
            organization_id="test-org",
            name="テスト団体",
            area="東京都",
            website_url="https://example.com/",
            source_type="official_site",
            scraper_type="test-scraper",
            scraper_enabled=True,
            event_type="open_keiko",
        )

    def make_event(self) -> ServiceEvent:
        return ServiceEvent(
            event_id="test-org-20260801-1900-12345678",
            organization_id="test-org",
            organization_name="テスト団体",
            event_type="open_keiko",
            title="通常稽古",
            event_date="2026-08-01",
            weekday="土",
            start_time="19:00",
            end_time="20:30",
            venue="テスト武道館",
            area="東京都",
            address=None,
            access=None,
            fee=None,
            application_required=False,
            source_url="https://example.com/",
            source_type="official_site",
            last_scraped_at="2026-07-22T17:00:00+09:00",
            status="active",
            raw_note=None,
            update_mode="automatic",
            participation_type="unknown",
            verified_at=None,
            gsi1_pk="EVENT",
            gsi1_sk=(
                "2026-08-01#19:00#test-org#"
                "test-org-20260801-1900-12345678"
            ),
        )

    def test_returns_success_and_saves_events(self) -> None:
        organization = self.make_organization()
        events = [self.make_event()]

        with (
            patch(
                "kendo_keiko.worker.load_organizations",
                return_value=[organization],
            ),
            patch(
                "kendo_keiko.worker.run_pipeline",
                return_value=events,
            ) as run_pipeline,
            patch("kendo_keiko.worker.save_dynamodb") as save_dynamodb,
            patch(
                "kendo_keiko.worker.time.perf_counter",
                side_effect=[10.0, 10.125],
            ),
        ):
            result = run_scraper_worker(
                organization_id="test-org",
                table_name="KendoKeikoEvents",
                region_name="ap-northeast-1",
                from_date="2026-07-22",
                run_id="run-1",
            )

        self.assertEqual("success", result["status"])
        self.assertEqual(1, result["event_count"])
        self.assertEqual(125, result["duration_ms"])
        self.assertIsNone(result["error_type"])
        run_pipeline.assert_called_once()
        self.assertEqual(
            dt.date(2026, 7, 22),
            run_pipeline.call_args.kwargs["from_date"],
        )
        save_dynamodb.assert_called_once_with(
            events=events,
            table_name="KendoKeikoEvents",
            region="ap-northeast-1",
        )

    def test_returns_warning_for_empty_result(self) -> None:
        organization = self.make_organization()

        with (
            patch(
                "kendo_keiko.worker.load_organizations",
                return_value=[organization],
            ),
            patch("kendo_keiko.worker.run_pipeline", return_value=[]),
            patch("kendo_keiko.worker.save_dynamodb") as save_dynamodb,
        ):
            result = run_scraper_worker(
                organization_id="test-org",
                table_name="KendoKeikoEvents",
                region_name="ap-northeast-1",
                from_date="2026-07-22",
                run_id="run-2",
            )

        self.assertEqual("warning", result["status"])
        self.assertEqual(0, result["event_count"])
        self.assertEqual("empty_result", result["error_type"])
        save_dynamodb.assert_called_once_with(
            events=[],
            table_name="KendoKeikoEvents",
            region="ap-northeast-1",
        )

    def test_converts_request_error_to_transient_error(self) -> None:
        organization = self.make_organization()

        with (
            patch(
                "kendo_keiko.worker.load_organizations",
                return_value=[organization],
            ),
            patch(
                "kendo_keiko.worker.run_pipeline",
                side_effect=requests.Timeout("timed out"),
            ),
        ):
            with self.assertRaises(ScraperTransientError):
                run_scraper_worker(
                    organization_id="test-org",
                    table_name="KendoKeikoEvents",
                    region_name="ap-northeast-1",
                    from_date="2026-07-22",
                    run_id="run-3",
                )


if __name__ == "__main__":
    unittest.main()
