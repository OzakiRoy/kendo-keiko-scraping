import unittest
from unittest.mock import patch

from kendo_keiko.models import Organization
from kendo_keiko.scrapers.kenkyukai import scrape


class KenkyukaiScraperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.organization = Organization(
            organization_id="kenkyukai",
            name="剣究会",
            area="東京都",
            website_url=(
                "https://kenkyukai-kendo.com/"
            ),
            source_type="official_site",
            scraper_type="kenkyukai",
            scraper_enabled=True,
            event_type="open_keiko",
            notes=None,
        )

    @patch(
        "kendo_keiko.scrapers."
        "kenkyukai.parse_wp_posts"
    )
    def test_scrapes_wordpress_posts(
        self,
        mock_parse_wp_posts,
    ) -> None:
        mock_parse_wp_posts.return_value = [
            {
                "date": "2026-08-01T10:00:00",
                "link": (
                    "https://kenkyukai-kendo.com/"
                    "archives/577"
                ),
                "title": {
                    "rendered": (
                        "<b>2026年8月&amp;"
                        "9月稽古情報</b>"
                    )
                },
                "content": {
                    "rendered": (
                        "<p>2026年8月</p>"
                        "<p>8/23(日)"
                        "12:30～15:00</p>"
                        "<p>@文京区"
                        "スポーツセンター</p>"
                        "<p>（茗荷谷駅 "
                        "徒歩3分）</p>"
                    )
                },
                "excerpt": {
                    "rendered": ""
                },
            }
        ]

        events = scrape(self.organization)

        self.assertEqual(1, len(events))
        self.assertEqual(
            "2026-08-23",
            events[0].date,
        )
        self.assertEqual(
            "文京区スポーツセンター",
            events[0].venue,
        )
        self.assertEqual(
            "茗荷谷駅 徒歩3分",
            events[0].access,
        )
        self.assertEqual(
            "2026年8月&9月稽古情報",
            events[0].title,
        )

        mock_parse_wp_posts.assert_called_once_with(
            "https://kenkyukai-kendo.com/",
            per_page=10,
        )

    @patch(
        "kendo_keiko.scrapers."
        "kenkyukai.fetch"
    )
    @patch(
        "kendo_keiko.scrapers."
        "kenkyukai.parse_wp_posts"
    )
    def test_falls_back_to_homepage_html(
        self,
        mock_parse_wp_posts,
        mock_fetch,
    ) -> None:
        mock_parse_wp_posts.side_effect = (
            RuntimeError("API unavailable")
        )
        mock_fetch.return_value = """
        <p>2026年9月</p>
        <p>9/23(日)12:30～15:00</p>
        <p>@文京区スポーツセンター</p>
        <p>（茗荷谷駅 徒歩3分）</p>
        """

        events = scrape(self.organization)

        self.assertEqual(1, len(events))
        self.assertEqual(
            "2026-09-23",
            events[0].date,
        )
        self.assertEqual(
            "文京区スポーツセンター",
            events[0].venue,
        )

        mock_fetch.assert_called_once_with(
            "https://kenkyukai-kendo.com/"
        )


if __name__ == "__main__":
    unittest.main()
