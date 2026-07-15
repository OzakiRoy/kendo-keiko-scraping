from __future__ import annotations

import datetime as dt
import html
import re
from typing import Optional
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from kendo_keiko.models import RawScrapedEvent


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; kendo-schedule-scraper/1.2; "
        "+https://example.com/local-script)"
    )
}

JST = ZoneInfo("Asia/Tokyo")

# kent / 剣究会向け:
# 例: 7月18日（土）15:30~18:00
DATE_TIME_RE = re.compile(
    r"""
    (?:日時[:：]\s*)?
    (?P<month>\d{1,2})
    \s*(?:/|月)\s*
    (?P<day>\d{1,2})
    \s*(?:日)?
    \s*[（(](?P<weekday>[^）)]+)[）)]
    \s*
    (?P<start>\d{1,2}:\d{2})
    \s*[~\-ー]\s*
    (?P<end>\d{1,2}:\d{2})
    """,
    re.VERBOSE,
)

YEAR_MONTH_RE = re.compile(r"(?P<year>\d{4})年\s*(?P<month>\d{1,2})月")

# 時刻の有無に関係なく、日付から始まる行をイベント境界として検出する。
# 例:
#   9/23(日)12:30~15:00
#   9/26(土)&9/27(日)
DATE_LINE_RE = re.compile(
    r"""
    ^
    \s*
    \d{1,2}
    \s*(?:/|月)\s*
    \d{1,2}
    \s*(?:日)?
    \s*[（(]
    """,
    re.VERBOSE,
)

def fetch(url: str, timeout: int = 15) -> str:
    """
    URLからHTMLまたはJSON文字列を取得する。
    """
    res = requests.get(url, headers=HEADERS, timeout=timeout)
    res.raise_for_status()
    res.encoding = res.apparent_encoding or res.encoding
    return res.text


def html_to_text(raw_html: str) -> str:
    """
    HTMLをスクレイピングしやすいプレーンテキストに変換する。
    """
    soup = BeautifulSoup(raw_html, "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text("\n")
    text = html.unescape(text)
    text = text.replace("\u3000", " ")
    text = text.replace("〜", "~").replace("～", "~")
    text = text.replace("－", "-").replace("−", "-")
    text = text.replace("＠", "@")

    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)

def normalize_weekday(value: Optional[str]) -> Optional[str]:
    if not value:
        return None

    value = value.strip()
    value = value.replace("曜日", "")
    return value[:1] if value else None

def build_month_year_map(text: str) -> dict[int, int]:
    """
    テキスト内の「2026年7月」のような記述から、
    月 -> 年 の対応を作る。
    """
    result: dict[int, int] = {}

    for m in YEAR_MONTH_RE.finditer(text):
        year = int(m.group("year"))
        month = int(m.group("month"))
        result[month] = year

    return result


def infer_event_year(
    event_month: int,
    base_year: int,
    base_month: int,
    month_year_map: dict[int, int],
) -> int:
    """
    イベントの日付に年がない場合に年を推定する。
    """
    if event_month in month_year_map:
        return month_year_map[event_month]

    # 例: 投稿が2026年12月、イベントが1月なら翌年と推定
    if event_month < base_month - 6:
        return base_year + 1

    # 例: 投稿が2026年1月、イベントが12月なら前年と推定
    if event_month > base_month + 6:
        return base_year - 1

    return base_year


def find_venue_and_access(
    lines: list[str],
    start_index: int,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    kent / 剣究会向け。
    日付行の直後数行から会場・アクセス・備考らしき情報を拾う。
    """
    venue = None
    access = None
    note = None

    for line in lines[start_index + 1 : start_index + 8]:
        if not line:
            continue

        # 時刻が書かれていない予定も含め、次の日付行で打ち切る
        if DATE_TIME_RE.search(line) or DATE_LINE_RE.search(line):
            break

        if line.startswith("@"):
            venue = line.lstrip("@").strip()
            continue

        if line.startswith("会場"):
            candidate = re.sub(r"^会場[:：]\s*", "", line).strip()
            if candidate:
                venue = candidate
            continue

        if line.startswith("場所"):
            candidate = re.sub(r"^場所[:：]\s*", "", line).strip()
            if candidate:
                venue = candidate
            continue

        if "体育館" in line or "スポーツセンター" in line or "武道場" in line:
            # アクセス文ではなく会場名っぽい場合だけ拾う
            if venue is None and len(line) <= 80:
                venue = line.strip()
            continue

        if re.match(r"^[（(].+[）)]$", line):
            access = line.strip("()（）")
            continue

        if (
            line.startswith("同日")
            or line.startswith("備考")
            or "懇親会" in line
            or "自由参加" in line
            or "初心者" in line
        ):
            note = line
            continue

    return venue, access, note


def parse_events_from_text(
    *,
    group: str,
    event_type: str,
    text: str,
    source_url: str,
    base_date: Optional[dt.date] = None,
) -> list[RawScrapedEvent]:
    """
    kent / 剣究会向け。
    プレーンテキストから稽古予定を抽出する。
    """
    if base_date is None:
        base_date = dt.datetime.now(JST).date()

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    month_year_map = build_month_year_map(text)

    events: list[RawScrapedEvent] = []
    last_title: Optional[str] = None

    for i, line in enumerate(lines):
        # kentの「『第285回剣道練習会』」などをタイトルとして記録
        if "稽古" in line or "剣道練習会" in line:
            if len(line) <= 80 and not DATE_TIME_RE.search(line):
                last_title = line.strip("『』 ")

        m = DATE_TIME_RE.search(line)
        if not m:
            continue

        month = int(m.group("month"))
        day = int(m.group("day"))
        year = infer_event_year(
            event_month=month,
            base_year=base_date.year,
            base_month=base_date.month,
            month_year_map=month_year_map,
        )

        venue, access, note = find_venue_and_access(lines, i)

        event = RawScrapedEvent(
            group=group,
            event_type=event_type,
            title=last_title,
            date=f"{year:04d}-{month:02d}-{day:02d}",
            weekday=normalize_weekday(m.group("weekday")),
            start_time=m.group("start"),
            end_time=m.group("end"),
            venue=venue,
            area=None,
            access=access,
            note=note,
            source_url=source_url,
        )
        events.append(event)

    return events
