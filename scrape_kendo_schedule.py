#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
kent / 剣究会 / 剣睦会 稽古予定スクレイピング

デフォルト動作:
  - kent / 剣究会 / 剣睦会 の公開Webページから稽古予定を取得
  - JST基準で「今日以降」の稽古だけ出力
  - JSON形式で出力

使い方:
  python scrape_kendo_schedule_with_kenbokukai_v2.py
  python scrape_kendo_schedule_with_kenbokukai_v2.py --format json
  python scrape_kendo_schedule_with_kenbokukai_v2.py --format text
  python scrape_kendo_schedule_with_kenbokukai_v2.py --format json --output keiko_schedule.json

今日以降ではなく、特定日以降にしたい場合:
  python scrape_kendo_schedule_with_kenbokukai_v2.py --from-date 2026-07-15

過去分も含めたい場合:
  python scrape_kendo_schedule_with_kenbokukai_v2.py --include-past

団体を絞りたい場合:
  python scrape_kendo_schedule_with_kenbokukai_v2.py --group kent
  python scrape_kendo_schedule_with_kenbokukai_v2.py --group kenkyukai
  python scrape_kendo_schedule_with_kenbokukai_v2.py --group kenbokukai

デバッグ:
  python scrape_kendo_schedule_with_kenbokukai_v2.py --group kenbokukai --format text --debug

必要パッケージ:
  pip install requests beautifulsoup4
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import asdict
from typing import Iterable, Optional

import requests

from kendo_keiko.models import Organization, RawScrapedEvent
from kendo_keiko.scrapers.common import (
    JST,
    fetch,
    html_to_text,
    parse_events_from_text,
)
from kendo_keiko.scrapers.kenbokukai import (
    parse_kenbokukai_events_from_text,
    scrape as scrape_kenbokukai_for_org,
)
from kendo_keiko.scrapers.kenkyukai import (
    scrape as scrape_kenkyukai_for_org,
)


SITES = {
    "kent": {
        "name": "社会人剣道サークルkent",
        "url": "https://kendonetwork.com/",
        "event_type": "open_keiko",
    },
    "kenkyukai": {
        "name": "剣究会",
        "url": "https://kenkyukai-kendo.com/",
        "event_type": "open_keiko",
    },
    "kenbokukai": {
        "name": "剣睦会",
        "url": "https://kenbokukai.com/",
        "event_type": "open_keiko",
    },
}

def debug_print(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[DEBUG] {message}", file=sys.stderr)


def event_score(e: RawScrapedEvent) -> int:
    """
    同一イベントが複数ソースから取れたとき、情報量が多い方を残すためのスコア。
    """
    score = 0
    for value in (
        e.title,
        e.weekday,
        e.start_time,
        e.end_time,
        e.venue,
        e.access,
        e.note,
        e.source_url,
    ):
        if value:
            score += 1
    return score


def dedupe_events(events: Iterable[RawScrapedEvent]) -> list[RawScrapedEvent]:
    """
    同一イベントらしきものを重複排除する。
    venueが取れたり取れなかったりしても重複扱いできるよう、venueはkeyから外す。
    同一keyでは情報量の多いイベントを残す。
    """
    best: dict[tuple, RawScrapedEvent] = {}

    for e in events:
        key = (
            e.group,
            e.event_type,
            e.date,
            e.start_time,
            e.end_time,
        )

        if key not in best or event_score(e) > event_score(best[key]):
            best[key] = e

    return sorted(best.values(), key=lambda x: (x.date, x.start_time or "", x.group))


def filter_events_from_date(
    events: Iterable[RawScrapedEvent],
    from_date: dt.date,
) -> list[RawScrapedEvent]:
    """
    from_date 以降の稽古だけ残す。
    今日を含めたいので >= で判定する。
    """
    result: list[RawScrapedEvent] = []

    for e in events:
        try:
            event_date = dt.date.fromisoformat(e.date)
        except ValueError:
            continue

        if event_date >= from_date:
            result.append(e)

    return sorted(result, key=lambda x: (x.date, x.start_time or "", x.group))


def scrape_kent() -> list[RawScrapedEvent]:
    """
    kentのトップページから稽古予定を取得する。
    """
    site = SITES["kent"]
    raw = fetch(site["url"])
    text = html_to_text(raw)

    return parse_events_from_text(
        group=site["name"],
        event_type=site["event_type"],
        text=text,
        source_url=site["url"],
    )


def scrape_kenkyukai(
    debug: bool = False,
) -> list[RawScrapedEvent]:
    """
    旧CLIとの互換性を保つための
    剣究会スクレイパーラッパー。
    """
    site = SITES["kenkyukai"]

    organization = Organization(
        organization_id="kenkyukai",
        name=site["name"],
        area="東京都",
        website_url=site["url"],
        source_type="official_site",
        scraper_type="kenkyukai",
        scraper_enabled=True,
        event_type=site["event_type"],
        notes=None,
    )

    return scrape_kenkyukai_for_org(
        organization,
        debug=debug,
    )


def scrape_kenbokukai(
    debug: bool = False,
) -> list[RawScrapedEvent]:
    """旧CLIとの互換性を保つための剣睦会スクレイパーラッパー。"""
    site = SITES["kenbokukai"]
    organization = Organization(
        organization_id="kenbokukai",
        name=site["name"],
        area="東京都",
        website_url=site["url"],
        source_type="official_site",
        scraper_type="kenbokukai",
        scraper_enabled=True,
        event_type=site["event_type"],
        notes=None,
    )
    return scrape_kenbokukai_for_org(organization, debug=debug)

def format_text(events: list[RawScrapedEvent]) -> str:
    """
    テキスト形式で見やすく整形する。
    """
    if not events:
        return "該当する稽古予定は見つかりませんでした。"

    lines: list[str] = []
    current_group = None

    for e in events:
        if e.group != current_group:
            if lines:
                lines.append("")
            lines.append(f"## {e.group}")
            current_group = e.group

        time_part = ""
        if e.start_time and e.end_time:
            time_part = f" {e.start_time}-{e.end_time}"

        venue_part = f" @ {e.venue}" if e.venue else ""
        access_part = f"（{e.access}）" if e.access else ""
        title_part = f" / {e.title}" if e.title else ""
        note_part = f" / {e.note}" if e.note else ""

        lines.append(
            f"- {e.date}({e.weekday}){time_part}{venue_part}{access_part}{title_part}{note_part}"
        )

    return "\n".join(lines)


def parse_from_date(value: Optional[str]) -> dt.date:
    """
    --from-date が指定されていればその日付、
    未指定ならJSTの今日を返す。
    """
    if value:
        try:
            return dt.date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                "--from-date は YYYY-MM-DD 形式で指定してください。例: 2026-07-09"
            ) from exc

    return dt.datetime.now(JST).date()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="kent / 剣究会 / 剣睦会の稽古予定をスクレイピングしてJSONまたはテキストで出力します。"
    )
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="出力形式。default: json",
    )
    parser.add_argument(
        "--output",
        help="出力先ファイル。未指定なら標準出力",
    )
    parser.add_argument(
        "--group",
        choices=["all", "kent", "kenkyukai", "kenbokukai"],
        default="all",
        help="取得対象。default: all",
    )
    parser.add_argument(
        "--from-date",
        help="この日付以降の稽古だけ出力する。例: 2026-07-09。未指定なら今日 JST",
    )
    parser.add_argument(
        "--include-past",
        action="store_true",
        help="過去の稽古も含める",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="デバッグ情報をstderrに出力する",
    )

    args = parser.parse_args()

    events: list[RawScrapedEvent] = []

    try:
        if args.group in ("all", "kent"):
            kent_events = scrape_kent()
            debug_print(args.debug, f"kent parsed events: {len(kent_events)}")
            events.extend(kent_events)

        if args.group in ("all", "kenkyukai"):
            events.extend(scrape_kenkyukai(debug=args.debug))

        if args.group in ("all", "kenbokukai"):
            events.extend(scrape_kenbokukai(debug=args.debug))

    except requests.RequestException as e:
        print(f"[ERROR] Webページの取得に失敗しました: {e}", file=sys.stderr)
        return 1

    debug_print(args.debug, f"events before dedupe: {len(events)}")
    events = dedupe_events(events)
    debug_print(args.debug, f"events after dedupe: {len(events)}")

    filter_from_date = None
    if not args.include_past:
        try:
            filter_from_date = parse_from_date(args.from_date)
        except ValueError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            return 1

        debug_print(args.debug, f"filter from date: {filter_from_date.isoformat()}")
        events = filter_events_from_date(events, filter_from_date)
        debug_print(args.debug, f"events after date filter: {len(events)}")

    if args.format == "json":
        output_obj = {
            "scraped_at": dt.datetime.now(JST).isoformat(timespec="seconds"),
            "timezone": "Asia/Tokyo",
            "group": args.group,
            "include_past": args.include_past,
            "from_date": filter_from_date.isoformat() if filter_from_date else None,
            "count": len(events),
            "events": [asdict(e) for e in events],
        }
        output = json.dumps(output_obj, ensure_ascii=False, indent=2)
    else:
        output = format_text(events)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output + "\n")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
