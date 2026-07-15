from __future__ import annotations

from kendo_keiko.models import Organization, RawScrapedEvent
from scrape_kendo_schedule import (
    fetch,
    html_to_text,
    parse_events_from_text,
)


def scrape(
    organization: Organization,
    debug: bool = False,
) -> list[RawScrapedEvent]:
    """
    kent公式サイトのSCHEDULEから稽古予定を取得する。

    現時点では既存の共通解析処理を利用する。
    共通解析処理は後続のリファクタリングで別モジュールへ移動する。
    """
    del debug  # 現在kent固有のデバッグ出力はない

    raw_html = fetch(organization.website_url)
    text = html_to_text(raw_html)

    return parse_events_from_text(
        group=organization.name,
        event_type=organization.event_type,
        text=text,
        source_url=organization.website_url,
    )
