from __future__ import annotations

from collections.abc import Callable

from kendo_keiko.models import Organization, RawScrapedEvent
from kendo_keiko.scrapers.ajkf import scrape as scrape_ajkf
from kendo_keiko.scrapers.kenbokukai import scrape as scrape_kenbokukai
from kendo_keiko.scrapers.kenkyukai import scrape as scrape_kenkyukai
from kendo_keiko.scrapers.kent import scrape as scrape_kent


Scraper = Callable[
    [Organization, bool],
    list[RawScrapedEvent],
]


SCRAPER_REGISTRY: dict[str, Scraper] = {
    "ajkf": scrape_ajkf,
    "kent": scrape_kent,
    "kenkyukai": scrape_kenkyukai,
    "kenbokukai": scrape_kenbokukai,
}


__all__ = ["SCRAPER_REGISTRY", "Scraper"]
