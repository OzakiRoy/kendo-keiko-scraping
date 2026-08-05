from __future__ import annotations

import datetime as dt
import re
import sys
import unicodedata
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from kendo_keiko.models import (
    Organization,
    ParticipationType,
    RawScrapedEvent,
)
from kendo_keiko.scrapers.common import HEADERS, JST


SAITAMA_BASE_URL = "https://www.saitama-kendo.or.jp"
CALENDAR_PLUGIN_ID = 11
CALENDAR_FRAME_ID = 229
MONTHS_TO_SCAN = 13

MONTH_URL = (
    f"{SAITAMA_BASE_URL}/plugin/calendars/index/"
    f"{CALENDAR_PLUGIN_ID}/{CALENDAR_FRAME_ID}"
)

EVENT_PATH_RE = re.compile(
    r"^/plugin/calendars/show/"
    rf"{CALENDAR_PLUGIN_ID}/\d+/(?P<event_id>\d+)/?$"
)

TARGET_TITLE_KEYS = frozenset(
    {
        "月例稽古",
        "月例稽古会",
        "追加月例稽古会",
    }
)
REGULAR_TITLE_KEYS = frozenset(
    {
        "月例稽古",
        "月例稽古会",
    }
)

WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]

FISCAL_2026_START = dt.date(2026, 4, 1)
FISCAL_2026_END = dt.date(2027, 3, 31)


def _debug_print(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[DEBUG] {message}", file=sys.stderr)


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_title_key(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def is_target_title(value: str) -> bool:
    return normalize_title_key(value) in TARGET_TITLE_KEYS


def build_month_url(year: int, month: int) -> str:
    if not 1 <= month <= 12:
        raise ValueError(f"invalid month: {month}")

    return (
        f"{MONTH_URL}?year{CALENDAR_FRAME_ID}={year:04d}"
        f"&month{CALENDAR_FRAME_ID}={month:02d}"
    )


def iter_months(
    start_date: dt.date,
    count: int = MONTHS_TO_SCAN,
) -> list[tuple[int, int]]:
    if count < 1:
        raise ValueError("count must be at least 1")

    start_index = start_date.year * 12 + start_date.month - 1
    result: list[tuple[int, int]] = []

    for offset in range(count):
        value = start_index + offset
        year, zero_based_month = divmod(value, 12)
        result.append((year, zero_based_month + 1))

    return result


def normalize_event_url(url: str) -> str:
    absolute_url = urljoin(SAITAMA_BASE_URL, url)
    parsed = urlparse(absolute_url)

    if parsed.netloc not in {
        "www.saitama-kendo.or.jp",
        "saitama-kendo.or.jp",
    }:
        raise ValueError(f"unexpected Saitama event host: {parsed.netloc}")

    match = EVENT_PATH_RE.match(parsed.path)
    if not match:
        raise ValueError(f"unexpected Saitama event URL: {url}")

    event_id = match.group("event_id")
    return (
        f"{SAITAMA_BASE_URL}/plugin/calendars/show/"
        f"{CALENDAR_PLUGIN_ID}/{CALENDAR_FRAME_ID}/{event_id}"
    )


def extract_monthly_practice_links(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    frame = soup.find(id=f"frame-card-{CALENDAR_FRAME_ID}")

    if frame is None:
        raise ValueError(
            "埼玉県剣道連盟の主カレンダーframeが見つかりません"
        )

    links: set[str] = set()

    for anchor in frame.select('a[href*="/plugin/calendars/show/"]'):
        label = normalize_text(anchor.get_text(" ", strip=True))
        if not is_target_title(label):
            continue

        href = anchor.get("href")
        if not href:
            continue

        links.add(normalize_event_url(href))

    return sorted(links)


def extract_detail_fields(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")

    for detail_list in soup.find_all("dl"):
        fields: dict[str, str] = {}

        for term in detail_list.find_all("dt", recursive=False):
            description = term.find_next_sibling("dd")
            if description is None:
                continue

            key = normalize_text(term.get_text(" ", strip=True))
            value = normalize_text(description.get_text(" ", strip=True))
            fields[key] = value

        title = fields.get("タイトル", "")
        if title and is_target_title(title):
            return fields

    return {}


def parse_datetime(value: str, field_name: str) -> dt.datetime:
    normalized = normalize_text(value)

    try:
        return dt.datetime.strptime(normalized, "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError(
            f"埼玉県剣道連盟の{field_name}を解析できません: {value!r}"
        ) from exc


def is_regular_repro_event(
    *,
    title: str,
    venue: Optional[str],
    event_date: dt.date,
) -> bool:
    return (
        normalize_title_key(title) in REGULAR_TITLE_KEYS
        and venue is not None
        and "リプロ武道館" in normalize_text(venue)
        and FISCAL_2026_START <= event_date <= FISCAL_2026_END
    )


def build_note(
    *,
    regular_repro_event: bool,
) -> str:
    if regular_repro_event:
        return (
            "参加費: 無料\n"
            "対象: 中学生以上の剣道経験者\n"
            "埼玉県立武道館の令和8年度月例稽古年間予定表に"
            "基づく情報です。\n"
            "日程や参加条件が変更される場合があります。"
            "参加前に公式情報をご確認ください。"
        )

    return (
        "埼玉県剣道連盟の公式カレンダーをもとに掲載しています。"
        "参加条件、申込要否、参加費は公式情報をご確認ください。"
    )


def parse_event_detail(
    *,
    html: str,
    source_url: str,
    organization: Organization,
) -> Optional[RawScrapedEvent]:
    fields = extract_detail_fields(html)
    if not fields:
        return None

    title = fields["タイトル"]
    if not is_target_title(title):
        return None

    start_value = fields.get("開始日時")
    if not start_value:
        raise ValueError(
            "埼玉県剣道連盟の月例稽古会に開始日時がありません"
        )

    start = parse_datetime(start_value, "開始日時")

    end_value = fields.get("終了日時")
    end = (
        parse_datetime(end_value, "終了日時")
        if end_value
        else None
    )

    venue = fields.get("場所") or None
    event_date = start.date()
    regular_repro_event = is_regular_repro_event(
        title=title,
        venue=venue,
        event_date=event_date,
    )
    participation_type: ParticipationType = (
        "anyone" if regular_repro_event else "unknown"
    )

    return RawScrapedEvent(
        group=organization.name,
        title=title,
        date=event_date.isoformat(),
        weekday=WEEKDAYS_JA[event_date.weekday()],
        start_time=start.strftime("%H:%M"),
        end_time=end.strftime("%H:%M") if end else None,
        venue=venue,
        area=organization.area,
        access=None,
        note=build_note(
            regular_repro_event=regular_repro_event,
        ),
        source_url=normalize_event_url(source_url),
        event_type=organization.event_type,
        participation_type=participation_type,
    )


def fetch_html(url: str, timeout: int = 30) -> str:
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def scrape(
    organization: Organization,
    debug: bool = False,
) -> list[RawScrapedEvent]:
    today = dt.datetime.now(JST).date()
    event_links: set[str] = set()

    for year, month in iter_months(today):
        month_url = build_month_url(year, month)
        _debug_print(debug, f"Saitama calendar month: {month_url}")
        month_html = fetch_html(month_url)
        event_links.update(extract_monthly_practice_links(month_html))

    events: list[RawScrapedEvent] = []

    for event_url in sorted(event_links):
        _debug_print(debug, f"Saitama event detail: {event_url}")
        event_html = fetch_html(event_url)
        event = parse_event_detail(
            html=event_html,
            source_url=event_url,
            organization=organization,
        )
        if event is not None:
            events.append(event)

    _debug_print(
        debug,
        f"Saitama links={len(event_links)} events={len(events)}",
    )

    return sorted(
        events,
        key=lambda event: (
            event.date,
            event.start_time or "",
            event.title or "",
        ),
    )
