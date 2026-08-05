import unittest
from pathlib import Path

from kendo_keiko.models import Organization
from kendo_keiko.scrapers.saitama import (
    build_month_url,
    extract_monthly_practice_links,
    normalize_event_url,
    parse_event_detail,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"


class SaitamaScraperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.organization = Organization(
            organization_id="saitama",
            name="埼玉県剣道連盟",
            area="埼玉県",
            website_url=(
                "https://www.saitama-kendo.or.jp/"
                "plugin/calendars/index/11/229"
            ),
            source_type="official_site",
            scraper_type="saitama",
            scraper_enabled=True,
            event_type="federation_keiko",
        )

    def test_builds_month_url(self) -> None:
        self.assertEqual(
            "https://www.saitama-kendo.or.jp/"
            "plugin/calendars/index/11/229"
            "?year229=2026&month229=10",
            build_month_url(2026, 10),
        )

    def test_collects_only_target_links_from_primary_frame(self) -> None:
        html = (
            FIXTURE_DIR / "saitama_october_calendar.html"
        ).read_text(encoding="utf-8")

        self.assertEqual(
            [
                "https://www.saitama-kendo.or.jp/"
                "plugin/calendars/show/11/229/2624",
                "https://www.saitama-kendo.or.jp/"
                "plugin/calendars/show/11/229/2627",
            ],
            extract_monthly_practice_links(html),
        )

    def test_normalizes_frame_query_and_fragment(self) -> None:
        self.assertEqual(
            "https://www.saitama-kendo.or.jp/"
            "plugin/calendars/show/11/229/2627",
            normalize_event_url(
                "https://www.saitama-kendo.or.jp/"
                "plugin/calendars/show/11/22/2627"
                "?frame=22#frame-22"
            ),
        )

    def test_parses_regular_monthly_practice(self) -> None:
        html = (
            FIXTURE_DIR / "saitama_regular_event.html"
        ).read_text(encoding="utf-8")

        event = parse_event_detail(
            html=html,
            source_url=(
                "https://www.saitama-kendo.or.jp/"
                "plugin/calendars/show/11/229/2554#frame-229"
            ),
            organization=self.organization,
        )

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual("月例稽古", event.title)
        self.assertEqual("2026-08-06", event.date)
        self.assertEqual("木", event.weekday)
        self.assertEqual("19:00", event.start_time)
        self.assertEqual("20:00", event.end_time)
        self.assertEqual("リプロ武道館 主道場", event.venue)
        self.assertEqual("anyone", event.participation_type)
        self.assertIn("参加費: 無料", event.note or "")
        self.assertIn("中学生以上", event.note or "")

    def test_parses_additional_event_without_regular_conditions(self) -> None:
        html = (
            FIXTURE_DIR / "saitama_additional_event.html"
        ).read_text(encoding="utf-8")

        event = parse_event_detail(
            html=html,
            source_url=(
                "https://www.saitama-kendo.or.jp/"
                "plugin/calendars/show/11/22/2627?frame=22"
            ),
            organization=self.organization,
        )

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual("追加 月例稽古会", event.title)
        self.assertEqual("2026-10-22", event.date)
        self.assertEqual("19:00", event.start_time)
        self.assertEqual("20:00", event.end_time)
        self.assertEqual("ぐるる宮代", event.venue)
        self.assertEqual("unknown", event.participation_type)
        self.assertNotIn("参加費: 無料", event.note or "")
        self.assertIn("参加条件", event.note or "")

    def test_ignores_unrelated_event_detail(self) -> None:
        html = """
        <dl class="row">
          <dt>タイトル</dt><dd>剣道七段審査会</dd>
          <dt>開始日時</dt><dd>2026-10-11 09:00</dd>
          <dt>終了日時</dt><dd>2026-10-11 17:00</dd>
          <dt>場所</dt><dd>リプロ武道館</dd>
        </dl>
        """

        self.assertIsNone(
            parse_event_detail(
                html=html,
                source_url=(
                    "https://www.saitama-kendo.or.jp/"
                    "plugin/calendars/show/11/229/2600"
                ),
                organization=self.organization,
            )
        )


if __name__ == "__main__":
    unittest.main()
