from __future__ import annotations

import datetime as dt
import sys

from kendo_keiko.models import Organization, RawScrapedEvent
from kendo_keiko.scrapers.common import (
    JST,
    fetch,
    html_to_text,
    normalize_title,
    parse_events_from_text,
    parse_wp_posts,
)


def _debug_print(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[DEBUG] {message}", file=sys.stderr)


def scrape(
    organization: Organization,
    debug: bool = False,
) -> list[RawScrapedEvent]:
    """
    剣究会の新着情報から稽古予定を取得する。

    WordPress REST APIを優先し、取得に失敗した場合は
    公式サイトのHTMLへフォールバックする。
    """
    events: list[RawScrapedEvent] = []

    try:
        posts = parse_wp_posts(
            organization.website_url,
            per_page=10,
        )
        _debug_print(
            debug,
            f"剣究会 WP posts: {len(posts)}",
        )

        for post in posts:
            title = normalize_title(
                post.get("title", {}).get(
                    "rendered",
                    "",
                )
            )
            link = (
                post.get("link")
                or organization.website_url
            )

            post_date_raw = post.get("date", "")
            try:
                base_date = dt.date.fromisoformat(
                    post_date_raw[:10]
                )
            except ValueError:
                base_date = dt.datetime.now(JST).date()

            body_html = (
                post.get("content", {}).get(
                    "rendered",
                    "",
                )
                or post.get("excerpt", {}).get(
                    "rendered",
                    "",
                )
            )
            text = (
                title
                + "\n"
                + html_to_text(body_html)
            )

            events.extend(
                parse_events_from_text(
                    group=organization.name,
                    event_type=organization.event_type,
                    text=text,
                    source_url=link,
                    base_date=base_date,
                )
            )

    except Exception as exc:
        print(
            "[WARN] 剣究会のWordPress API取得に"
            "失敗しました。"
            f"HTML fallbackします: {exc}",
            file=sys.stderr,
        )

        raw_html = fetch(
            organization.website_url
        )
        text = html_to_text(raw_html)

        events.extend(
            parse_events_from_text(
                group=organization.name,
                event_type=organization.event_type,
                text=text,
                source_url=organization.website_url,
            )
        )

    _debug_print(
        debug,
        f"剣究会 parsed events: {len(events)}",
    )
    return events
