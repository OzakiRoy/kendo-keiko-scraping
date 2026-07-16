import unittest

from kendo_keiko.models import Organization
from kendo_keiko.scrapers.tokyo import (
    find_latest_schedule_pdf_url,
    parse_joint_practice_events,
)


class TokyoScraperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.organization = Organization(
            organization_id="tokyo-kendo",
            name="東京都剣道連盟",
            area="東京都",
            website_url=(
                "https://www.tokyo-kendo.or.jp/"
                "keiko/keikokai-index.html"
            ),
            source_type="official_site",
            scraper_type="tokyo",
            scraper_enabled=True,
            event_type="federation_keiko",
            notes=None,
        )

    def test_finds_latest_schedule_pdf(self) -> None:
        html = """
        <a href="/keiko/data-images/
        suiyo-keikokai-nitei-202504-09.pdf">
          令和7年度日程
        </a>
        <a href="/keiko/data-images/
        2026kendokeikokainitteihyo.pdf">
          令和8年4月～令和9年3月
          剣道合同稽古会・剣道稽古会日程表
        </a>
        """

        result = find_latest_schedule_pdf_url(
            html,
            self.organization.website_url,
        )

        self.assertEqual(
            "https://www.tokyo-kendo.or.jp/"
            "keiko/data-images/"
            "2026kendokeikokainitteihyo.pdf",
            result,
        )

    def test_parses_only_main_dojo_events(self) -> None:
        text = """
        4月8日 水 第二武道場
        6月17日 水 第二武道場
        9月13日 日 大武道場
        17:30～19:30

        4月19日 日 大武道場
        17:30～19:30
        7月1日 水 第二武道場

        8月31日 月 大武道場
        18:00～20:00
        9月2日 水 第二武道場

        10月7日 水 第二武道場
        12月6日 日 大武道場
        17:30～19:30
        2月17日 水 第二武道場

        1月25日 月 大武道場
        18:00～20:00
        1月27日 水 第二武道場

        東京都剣道連盟剣道稽古会・
        合同稽古会日程表
        令和8年4月～令和8年9月
        令和8年10月～令和9年3月
        """

        events = parse_joint_practice_events(
            text,
            self.organization,
            "https://example.com/schedule.pdf",
        )

        self.assertEqual(
            [
                "2026-04-19",
                "2026-08-31",
                "2026-09-13",
                "2026-12-06",
                "2027-01-25",
            ],
            [event.date for event in events],
        )

        august_event = next(
            event
            for event in events
            if event.date == "2026-08-31"
        )
        self.assertEqual(
            "18:00",
            august_event.start_time,
        )
        self.assertEqual(
            "20:00",
            august_event.end_time,
        )
        self.assertEqual(
            "東京武道館 大武道場",
            august_event.venue,
        )
        self.assertIn(
            "参加費: 800円",
            august_event.note or "",
        )


if __name__ == "__main__":
    unittest.main()
