import unittest
from pathlib import Path
from unittest.mock import patch

from kendo_keiko.models import Organization
from kendo_keiko.scrapers.kent import scrape


class KentScraperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.organization = Organization(
            organization_id="kent",
            name="社会人剣道サークルkent",
            area="東京都",
            website_url="https://kendonetwork.com/",
            source_type="official_site",
            scraper_type="kent",
            scraper_enabled=True,
            event_type="open_keiko",
            notes=None,
        )

    @patch("kendo_keiko.scrapers.kent.fetch")
    def test_scrapes_schedule_from_official_site(
        self,
        mock_fetch,
    ) -> None:
        mock_fetch.return_value = """
        <html>
          <body>
            <p>2026年7月</p>

            <p>『第285回剣道練習会』</p>
            <p>日時：7月18日（土）15:30～18:00</p>
            <p>会場：</p>
            <p>文京スポーツセンター</p>

            <p>『第286回剣道練習会』</p>
            <p>日時：7月19日（日）15:00～18:00</p>
            <p>会場：池袋スポーツセンター</p>
          </body>
        </html>
        """

        events = scrape(self.organization)

        self.assertEqual(2, len(events))

        self.assertEqual("2026-07-18", events[0].date)
        self.assertEqual("文京スポーツセンター", events[0].venue)
        self.assertEqual("第285回剣道練習会", events[0].title)

        self.assertEqual("2026-07-19", events[1].date)
        self.assertEqual("池袋スポーツセンター", events[1].venue)

        mock_fetch.assert_called_once_with(
            "https://kendonetwork.com/"
        )

    @patch("kendo_keiko.scrapers.kent.fetch")
    def test_scrapes_span_split_october_and_november_schedule(
        self,
        mock_fetch,
    ) -> None:
        fixture = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "kent_schedule_october_november.html"
        )
        mock_fetch.return_value = fixture.read_text(encoding="utf-8")

        events = scrape(self.organization)

        self.assertEqual(3, len(events))
        self.assertEqual(
            [
                (
                    "第289回剣道練習会",
                    "2026-10-03",
                    "土",
                    "15:00",
                    "18:00",
                    "池袋スポーツセンター",
                ),
                (
                    "第290回剣道練習会",
                    "2026-10-11",
                    "日",
                    "15:00",
                    "18:00",
                    "池袋スポーツセンター",
                ),
                (
                    "第291回剣道練習会",
                    "2026-11-21",
                    "土",
                    "15:00",
                    "18:00",
                    "池袋スポーツセンター",
                ),
            ],
            [
                (
                    event.title,
                    event.date,
                    event.weekday,
                    event.start_time,
                    event.end_time,
                    event.venue,
                )
                for event in events
            ],
        )


if __name__ == "__main__":
    unittest.main()
