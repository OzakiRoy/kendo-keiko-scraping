import datetime as dt
import unittest
from pathlib import Path

from kendo_keiko.models import Organization
from kendo_keiko.pipeline import filter_events_from_date
from kendo_keiko.scrapers.kanagawa import (
    classify_summary,
    parse_joint_practice_events,
)


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "kanagawa_calendar.ics"
)


class KanagawaScraperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.organization = Organization(
            organization_id="kanagawa",
            name="神奈川県剣道連盟",
            area="神奈川県",
            website_url=(
                "https://kanagawa-kenren.com/"
                "taikai_cal/calender"
            ),
            source_type="official_site",
            scraper_type="kanagawa",
            scraper_enabled=True,
            event_type="federation_keiko",
            notes=None,
        )
        self.ics_text = FIXTURE_PATH.read_text(
            encoding="utf-8"
        )

    def test_classifies_only_target_summaries(self) -> None:
        self.assertEqual(
            "一般合同稽古会",
            classify_summary(
                "【剣道】 剣道一般合同稽古会"
            ),
        )
        self.assertEqual(
            "女子合同稽古会",
            classify_summary(
                "【剣道】剣道女子合同稽古会"
            ),
        )
        self.assertIsNone(
            classify_summary(
                "韓国剣道選手団との交流稽古会"
            )
        )

    def test_parses_targets_and_converts_utc_to_jst(self) -> None:
        events = parse_joint_practice_events(
            self.ics_text,
            self.organization,
        )

        self.assertEqual(3, len(events))
        self.assertEqual(
            [
                "2027-02-04",
                "2027-02-09",
                "2027-03-09",
            ],
            [event.date for event in events],
        )

        general_event = next(
            event
            for event in events
            if event.date == "2027-02-09"
        )
        self.assertEqual(
            "19:00",
            general_event.start_time,
        )
        self.assertEqual(
            "21:00",
            general_event.end_time,
        )
        self.assertEqual(
            "火",
            general_event.weekday,
        )
        self.assertEqual(
            "神奈川県立武道館",
            general_event.venue,
        )
        self.assertEqual(
            "一般合同稽古会",
            general_event.title,
        )
        self.assertIn(
            "参加費: 500円",
            general_event.note or "",
        )
        self.assertIn(
            "満18歳以上",
            general_event.note or "",
        )
        self.assertEqual(
            self.organization.website_url,
            general_event.source_url,
        )

        women_event = next(
            event
            for event in events
            if event.date == "2027-02-04"
        )
        self.assertEqual(
            "10:00",
            women_event.start_time,
        )
        self.assertEqual(
            "12:00",
            women_event.end_time,
        )
        self.assertEqual(
            "女子合同稽古会",
            women_event.title,
        )

    def test_excludes_cancelled_and_unrelated_events(self) -> None:
        events = parse_joint_practice_events(
            self.ics_text,
            self.organization,
        )

        titles = [event.title for event in events]
        dates = [event.date for event in events]

        self.assertNotIn("2027-02-10", dates)
        self.assertNotIn(
            "韓国剣道選手団との交流稽古会",
            titles,
        )

    def test_pipeline_date_filter_removes_past_events(self) -> None:
        events = parse_joint_practice_events(
            self.ics_text,
            self.organization,
        )

        filtered = filter_events_from_date(
            events,
            dt.date(2027, 2, 9),
        )

        self.assertEqual(
            ["2027-02-09", "2027-03-09"],
            [event.date for event in filtered],
        )


if __name__ == "__main__":
    unittest.main()
