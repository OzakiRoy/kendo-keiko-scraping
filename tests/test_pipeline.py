import datetime as dt
import unittest
from unittest.mock import Mock, patch

from kendo_keiko.models import Organization, RawScrapedEvent
from kendo_keiko.pipeline import normalize_events, run_pipeline
from kendo_keiko.repository import load_organizations
from kendo_keiko.scrapers import SCRAPER_REGISTRY


class PipelineTests(unittest.TestCase):
    def test_runs_scrape_dedupe_filter_and_normalize(self) -> None:
        organization = Organization(
            organization_id="test-org",
            name="テスト団体",
            area="東京都",
            website_url="https://example.com/",
            source_type="official_site",
            scraper_type="test-scraper",
            scraper_enabled=True,
            event_type="open_keiko",
            notes=None,
        )

        past_event = RawScrapedEvent(
            group="テスト団体",
            title="過去の稽古会",
            date="2026-07-31",
            weekday="金",
            start_time="10:00",
            end_time="12:00",
            venue="過去会場",
            area=None,
            access=None,
            note=None,
            source_url="https://example.com/past",
            event_type="open_keiko",
        )
        sparse_event = RawScrapedEvent(
            group="テスト団体",
            title="稽古会",
            date="2026-08-01",
            weekday="土",
            start_time="13:00",
            end_time="15:00",
            venue=None,
            area=None,
            access=None,
            note=None,
            source_url="https://example.com/event",
            event_type="open_keiko",
        )
        detailed_event = RawScrapedEvent(
            group="テスト団体",
            title="稽古会",
            date="2026-08-01",
            weekday="土",
            start_time="13:00",
            end_time="15:00",
            venue="テスト武道館",
            area=None,
            access="テスト駅 徒歩5分",
            note="参加費: 500円 / 申込必須",
            source_url="https://example.com/event",
            event_type="open_keiko",
        )
        scraper = Mock(
            return_value=[
                past_event,
                sparse_event,
                detailed_event,
            ]
        )

        with patch.dict(
            SCRAPER_REGISTRY,
            {"test-scraper": scraper},
        ):
            events = run_pipeline(
                organizations=[organization],
                scraped_at="2026-07-16T09:00:00+09:00",
                from_date=dt.date(2026, 8, 1),
                debug=False,
            )

        self.assertEqual(1, len(events))
        event = events[0]
        self.assertEqual("test-org", event.organization_id)
        self.assertEqual("2026-08-01", event.event_date)
        self.assertEqual("テスト武道館", event.venue)
        self.assertEqual("東京都", event.area)
        self.assertEqual("500円 / 申込必須", event.fee)
        self.assertTrue(event.application_required)
        self.assertEqual("automatic", event.update_mode)
        self.assertEqual(
            "registration_required",
            event.participation_type,
        )
        self.assertIsNone(event.verified_at)
        self.assertTrue(event.event_id.startswith("test-org-20260801-1300-"))

        scraper.assert_called_once_with(
            organization,
            debug=False,
        )



    def test_uses_organization_participation_defaults(self) -> None:
        organization = Organization(
            organization_id="default-org",
            name="既定値団体",
            area="東京都",
            website_url="https://example.com/",
            source_type="official_site",
            scraper_type="test-scraper",
            scraper_enabled=True,
            event_type="open_keiko",
            default_participation_type="anyone",
            default_application_required=False,
        )
        raw_event = RawScrapedEvent(
            group="既定値団体",
            title="通常稽古",
            date="2026-08-01",
            weekday="土",
            start_time="13:00",
            end_time="15:00",
            venue="テスト武道館",
            area=None,
            access=None,
            note=None,
            source_url="https://example.com/event",
            event_type="open_keiko",
        )

        event = normalize_events(
            [raw_event],
            [organization],
            "2026-07-30T09:00:00+09:00",
        )[0]

        self.assertEqual("anyone", event.participation_type)
        self.assertFalse(event.application_required)
        self.assertIsNone(event.verified_at)

    def test_event_participation_type_overrides_organization_default(
        self,
    ) -> None:
        organization = Organization(
            organization_id="event-override-org",
            name="イベント個別条件団体",
            area="埼玉県",
            website_url="https://example.com/",
            source_type="official_site",
            scraper_type="test-scraper",
            scraper_enabled=True,
            event_type="federation_keiko",
            default_participation_type="unknown",
        )
        raw_event = RawScrapedEvent(
            group=organization.name,
            title="月例稽古",
            date="2026-08-06",
            weekday="木",
            start_time="19:00",
            end_time="20:00",
            venue="テスト武道館",
            area=None,
            access=None,
            note="参加費: 無料",
            source_url="https://example.com/event",
            event_type="federation_keiko",
            participation_type="anyone",
        )

        event = normalize_events(
            [raw_event],
            [organization],
            "2026-08-06T06:00:00+09:00",
        )[0]

        self.assertEqual("anyone", event.participation_type)
        self.assertIsNone(event.application_required)

    def test_event_application_text_overrides_organization_default(
        self,
    ) -> None:
        organization = Organization(
            organization_id="default-org",
            name="既定値団体",
            area="東京都",
            website_url="https://example.com/",
            source_type="official_site",
            scraper_type="test-scraper",
            scraper_enabled=True,
            event_type="open_keiko",
            default_participation_type="anyone",
            default_application_required=False,
        )
        raw_event = RawScrapedEvent(
            group="既定値団体",
            title="特別稽古",
            date="2026-08-01",
            weekday="土",
            start_time="13:00",
            end_time="15:00",
            venue="テスト武道館",
            area=None,
            access=None,
            note="申込必須",
            source_url="https://example.com/event",
            event_type="open_keiko",
        )

        event = normalize_events(
            [raw_event],
            [organization],
            "2026-07-30T09:00:00+09:00",
        )[0]

        self.assertEqual(
            "registration_required",
            event.participation_type,
        )
        self.assertTrue(event.application_required)

    def test_kent_and_kenkyukai_default_to_anyone(self) -> None:
        organizations = {
            organization.organization_id: organization
            for organization in load_organizations()
        }

        for organization_id in ("kent", "kenkyukai"):
            with self.subTest(organization_id=organization_id):
                organization = organizations[organization_id]
                self.assertEqual(
                    "anyone",
                    organization.default_participation_type,
                )
                self.assertFalse(
                    organization.default_application_required
                )

if __name__ == "__main__":
    unittest.main()
