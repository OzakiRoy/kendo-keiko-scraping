from __future__ import annotations

import re

from kendo_keiko.models import Organization, RawScrapedEvent
from kendo_keiko.scrapers.common import (
    fetch,
    html_to_text,
    parse_events_from_text,
)


_KENT_SCHEDULE_FRAGMENT_RE = re.compile(
    r"^[\d\s年月日時分秒曜日（）、()/:~〜～\-ー：]+$"
)
_KENT_TIME_RANGE_RE = re.compile(
    r"\d{1,2}:\d{2}\s*[~\-ー]\s*\d{1,2}:\d{2}"
)
_KENT_DATE_LINE_RE = re.compile(r"^\d{1,2}\s*月\s*\d{1,2}\s*日")


def normalize_kent_schedule_text(text: str) -> str:
    """
    kentのSCHEDULE固有のspan分割を、解析前に1行へ戻す。

    公式HTMLでは曜日や日付がspan要素に分割されることがあり、
    ``html_to_text``の結果が次のようになる。

    ``日時：10月11日（`` / ``日`` / ``）15:00~18:00``
    ``日時：`` / ``11月21日（土）`` / ``15:00~18:00``

    共通のHTML変換・テキスト解析は他団体も利用するため変更せず、
    kentのスクレイパー入口だけで日付時刻の断片を結合する。
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    normalized: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        if line.startswith("日時") or _KENT_DATE_LINE_RE.match(line):
            combined = line
            while (
                index + 1 < len(lines)
                and not _KENT_TIME_RANGE_RE.search(combined)
            ):
                next_line = lines[index + 1]
                if not _KENT_SCHEDULE_FRAGMENT_RE.fullmatch(next_line):
                    break
                combined += next_line
                index += 1
            normalized.append(combined)
        else:
            normalized.append(line)
        index += 1

    return "\n".join(normalized)


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
    text = normalize_kent_schedule_text(html_to_text(raw_html))

    return parse_events_from_text(
        group=organization.name,
        event_type=organization.event_type,
        text=text,
        source_url=organization.website_url,
    )
