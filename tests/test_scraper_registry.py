import unittest
from unittest.mock import Mock, patch

from kendo_keiko.pipeline import scrape_by_org
from kendo_keiko.models import Organization
from kendo_keiko.scrapers import SCRAPER_REGISTRY


class ScraperRegistryTests(unittest.TestCase):
    def make_organization(
        self,
        *,
        scraper_type: str,
        scraper_enabled: bool = True,
    ) -> Organization:
        return Organization(
            organization_id="test-org",
            name="テスト団体",
            area="東京都",
            website_url="https://example.com/",
            source_type="official_site",
            scraper_type=scraper_type,
            scraper_enabled=scraper_enabled,
            event_type="open_keiko",
            notes=None,
        )

    def test_contains_all_current_scrapers(self) -> None:
        self.assertEqual(
            {
                "ajkf",
                "kent",
                "kenkyukai",
                "kenbokukai",
            },
            set(SCRAPER_REGISTRY),
        )

    def test_dispatches_to_registered_scraper(self) -> None:
        organization = self.make_organization(
            scraper_type="test-scraper",
        )
        scraper = Mock(return_value=[])

        with patch.dict(
            SCRAPER_REGISTRY,
            {"test-scraper": scraper},
        ):
            result = scrape_by_org(
                organization,
                debug=True,
            )

        self.assertEqual([], result)
        scraper.assert_called_once_with(
            organization,
            debug=True,
        )

    def test_does_not_call_disabled_scraper(self) -> None:
        organization = self.make_organization(
            scraper_type="test-scraper",
            scraper_enabled=False,
        )
        scraper = Mock(return_value=[])

        with patch.dict(
            SCRAPER_REGISTRY,
            {"test-scraper": scraper},
        ):
            result = scrape_by_org(
                organization,
                debug=False,
            )

        self.assertEqual([], result)
        scraper.assert_not_called()


if __name__ == "__main__":
    unittest.main()
