from __future__ import annotations

import datetime as dt
import sys
import unicodedata
from dataclasses import dataclass
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from kendo_keiko.models import Organization, RawScrapedEvent
from kendo_keiko.scrapers.common import HEADERS, JST


KANAGAWA_ICS_URL = (
    "https://calendar.google.com/calendar/ical/"
    "kanagawa.kendorenmei%40gmail.com/public/basic.ics"
)

TARGET_SUMMARIES = {
    "剣道一般合同稽古会": "一般合同稽古会",
    "剣道女子合同稽古会": "女子合同稽古会",
}

WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]


@dataclass(frozen=True)
class IcsDateTime:
    value: dt.datetime
    all_day: bool


def _debug_print(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[DEBUG] {message}", file=sys.stderr)


def fetch_ics_text(
    url: str = KANAGAWA_ICS_URL,
    timeout: int = 30,
) -> str:
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.content.decode(
        "utf-8-sig",
        errors="replace",
    )


def unfold_ics_lines(text: str) -> list[str]:
    """
    RFC 5545 の折り返し行を展開する。

    改行後が半角スペースまたはタブで始まる場合は、
    直前の行へ連結する。
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []

    for line in normalized.split("\n"):
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)

    return lines


def decode_ics_text(value: str) -> str:
    """ICS の TEXT 値で使われる代表的なエスケープを戻す。"""
    result: list[str] = []
    index = 0

    while index < len(value):
        char = value[index]

        if char != "\\" or index + 1 >= len(value):
            result.append(char)
            index += 1
            continue

        escaped = value[index + 1]
        replacements = {
            "n": "\n",
            "N": "\n",
            ",": ",",
            ";": ";",
            "\\": "\\",
        }
        result.append(replacements.get(escaped, escaped))
        index += 2

    return "".join(result)


def parse_property(line: str) -> tuple[str, dict[str, str], str]:
    if ":" not in line:
        raise ValueError(f"ICSプロパティの区切りがありません: {line!r}")

    name_and_params, value = line.split(":", 1)
    parts = name_and_params.split(";")
    name = parts[0].upper()
    params: dict[str, str] = {}

    for raw_param in parts[1:]:
        if "=" not in raw_param:
            continue
        key, param_value = raw_param.split("=", 1)
        params[key.upper()] = param_value.strip('"')

    return name, params, value


def parse_ics_events(text: str) -> list[dict[str, list[tuple[dict[str, str], str]]]]:
    events: list[dict[str, list[tuple[dict[str, str], str]]]] = []
    current: Optional[dict[str, list[tuple[dict[str, str], str]]]] = None

    for line in unfold_ics_lines(text):
        if line == "BEGIN:VEVENT":
            current = {}
            continue

        if line == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None
            continue

        if current is None or not line or ":" not in line:
            continue

        name, params, value = parse_property(line)
        current.setdefault(name, []).append((params, value))

    return events


def first_property(
    event: dict[str, list[tuple[dict[str, str], str]]],
    name: str,
) -> tuple[dict[str, str], str] | None:
    values = event.get(name)
    return values[0] if values else None


def parse_ics_datetime(
    params: dict[str, str],
    value: str,
) -> IcsDateTime:
    is_date = params.get("VALUE", "").upper() == "DATE" or (
        len(value) == 8 and "T" not in value
    )

    if is_date:
        parsed_date = dt.datetime.strptime(value, "%Y%m%d").date()
        return IcsDateTime(
            value=dt.datetime.combine(
                parsed_date,
                dt.time.min,
                tzinfo=JST,
            ),
            all_day=True,
        )

    if value.endswith("Z"):
        parsed = dt.datetime.strptime(value, "%Y%m%dT%H%M%SZ")
        aware = parsed.replace(tzinfo=dt.timezone.utc).astimezone(JST)
        return IcsDateTime(value=aware, all_day=False)

    parsed = dt.datetime.strptime(value, "%Y%m%dT%H%M%S")
    timezone_name = params.get("TZID")

    if timezone_name:
        try:
            source_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            source_timezone = JST
    else:
        source_timezone = JST

    return IcsDateTime(
        value=parsed.replace(tzinfo=source_timezone).astimezone(JST),
        all_day=False,
    )


def normalize_summary(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", decode_ics_text(value))
    normalized = normalized.replace("【剣道】", "")
    return "".join(normalized.split())


def classify_summary(value: str) -> str | None:
    return TARGET_SUMMARIES.get(normalize_summary(value))


def build_note(event_date: dt.date) -> str:
    """
    令和8年度の参加条件は、公式の年度案内に基づいて補完する。

    次年度以降へ古い条件を誤適用しないよう、年度範囲外では
    参加費・対象を固定せず、公式情報の確認だけを案内する。
    """
    fiscal_2026_start = dt.date(2026, 4, 1)
    fiscal_2026_end = dt.date(2027, 3, 31)

    if fiscal_2026_start <= event_date <= fiscal_2026_end:
        return (
            "参加費: 500円\n"
            "対象: 満18歳以上\n"
            "支払方法: 現金または回数券\n"
            "令和8年度の公式案内に基づく情報です。\n"
            "日程や参加条件が変更される場合があります。"
            "参加前に神奈川県剣道連盟の公式情報をご確認ください。"
        )

    return (
        "参加費・参加条件は年度により変更される場合があります。"
        "参加前に神奈川県剣道連盟の公式情報をご確認ください。"
    )


def parse_joint_practice_events(
    text: str,
    organization: Organization,
    source_url: Optional[str] = None,
) -> list[RawScrapedEvent]:
    """
    神奈川県剣道連盟の公開Googleカレンダーから、
    一般合同稽古会・女子合同稽古会だけを取得する。
    """
    events: list[RawScrapedEvent] = []
    official_url = source_url or organization.website_url

    for raw_event in parse_ics_events(text):
        status_property = first_property(raw_event, "STATUS")
        status = status_property[1].upper() if status_property else ""
        if status == "CANCELLED":
            continue

        summary_property = first_property(raw_event, "SUMMARY")
        if not summary_property:
            continue

        title = classify_summary(summary_property[1])
        if not title:
            continue

        start_property = first_property(raw_event, "DTSTART")
        if not start_property:
            print(
                "[WARN] 神奈川県剣道連盟の合同稽古会に"
                "DTSTARTがありません",
                file=sys.stderr,
            )
            continue

        try:
            start = parse_ics_datetime(*start_property)
        except ValueError as exc:
            print(
                "[WARN] 神奈川県剣道連盟の開始日時を"
                f"解析できません: {start_property[1]!r} ({exc})",
                file=sys.stderr,
            )
            continue

        end_property = first_property(raw_event, "DTEND")
        end: IcsDateTime | None = None
        if end_property:
            try:
                end = parse_ics_datetime(*end_property)
            except ValueError as exc:
                print(
                    "[WARN] 神奈川県剣道連盟の終了日時を"
                    f"解析できません: {end_property[1]!r} ({exc})",
                    file=sys.stderr,
                )

        location_property = first_property(raw_event, "LOCATION")
        venue = (
            decode_ics_text(location_property[1]).strip()
            if location_property
            else None
        )

        start_time = None if start.all_day else start.value.strftime("%H:%M")
        end_time = (
            None
            if end is None or end.all_day
            else end.value.strftime("%H:%M")
        )

        events.append(
            RawScrapedEvent(
                group=organization.name,
                title=title,
                date=start.value.date().isoformat(),
                weekday=WEEKDAYS_JA[start.value.weekday()],
                start_time=start_time,
                end_time=end_time,
                venue=venue or "神奈川県立武道館",
                area="神奈川県",
                access=None,
                note=build_note(start.value.date()),
                source_url=official_url,
                event_type=organization.event_type,
            )
        )

    return sorted(
        events,
        key=lambda event: (
            event.date,
            event.start_time or "",
            event.title or "",
        ),
    )


def scrape(
    organization: Organization,
    debug: bool = False,
) -> list[RawScrapedEvent]:
    _debug_print(
        debug,
        f"Kanagawa calendar ICS: {KANAGAWA_ICS_URL}",
    )

    ics_text = fetch_ics_text()
    events = parse_joint_practice_events(
        ics_text,
        organization,
        organization.website_url,
    )

    _debug_print(
        debug,
        f"Kanagawa joint practice events: {len(events)}",
    )

    return events
