from __future__ import annotations

import datetime as dt
import re
import sys
import unicodedata
from io import BytesIO
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

from kendo_keiko.models import Organization, RawScrapedEvent
from kendo_keiko.scrapers.common import HEADERS, fetch


PDF_LINK_HINT = "kendokeikokainitteihyo"

SCHEDULE_ENTRY_RE = re.compile(
    r"""
    (?P<month>\d{1,2})月
    (?P<day>\d{1,2})日
    \s*
    (?P<weekday>[月火水木金土日])
    \s*
    (?P<venue>大武道場|第二武道場)
    """,
    re.VERBOSE,
)

TIME_RANGE_RE = re.compile(
    r"""
    (?P<start>\d{1,2}:\d{2})
    \s*[~\-]\s*
    (?P<end>\d{1,2}:\d{2})
    """,
    re.VERBOSE,
)

FISCAL_YEAR_RE = re.compile(
    r"令和(?P<reiwa_year>\d+)年4月"
)


def _debug_print(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[DEBUG] {message}", file=sys.stderr)


def find_latest_schedule_pdf_url(
    raw_html: str,
    page_url: str,
) -> str:
    """
    稽古会ページから最新年度の日程PDFを取得する。
    """
    soup = BeautifulSoup(raw_html, "html.parser")
    candidates: list[tuple[int, str]] = []

    for anchor in soup.find_all("a", href=True):
        raw_href = re.sub(r"\s+", "", anchor["href"])
        href = urljoin(page_url, raw_href)
        label = anchor.get_text(" ", strip=True)

        if not href.lower().endswith(".pdf"):
            continue

        if (
            PDF_LINK_HINT not in href.lower()
            and "剣道合同稽古会" not in label
            and "剣道稽古会" not in label
        ):
            continue

        year_match = re.search(
            r"(?P<year>20\d{2})"
            r"kendokeikokainitteihyo",
            href.lower(),
        )
        year = (
            int(year_match.group("year"))
            if year_match
            else 0
        )

        candidates.append((year, href))

    if not candidates:
        raise ValueError(
            "東京都剣道連盟の日程PDFが見つかりません"
        )

    return max(candidates)[1]


def fetch_pdf_bytes(
    url: str,
    timeout: int = 30,
) -> bytes:
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.content


def extract_pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))

    return "\n".join(
        page.extract_text() or ""
        for page in reader.pages
    )


def parse_joint_practice_events(
    text: str,
    organization: Organization,
    source_url: str,
) -> list[RawScrapedEvent]:
    """
    東京都剣道連盟の年度日程表から、
    大武道場で開催される剣道合同稽古会を取得する。

    第二武道場の水曜稽古会は今回の対象外。
    """
    normalized = unicodedata.normalize("NFKC", text)

    fiscal_match = FISCAL_YEAR_RE.search(normalized)
    if not fiscal_match:
        raise ValueError(
            "PDFから年度を特定できません"
        )

    fiscal_start_year = (
        int(fiscal_match.group("reiwa_year")) + 2018
    )

    matches = list(
        SCHEDULE_ENTRY_RE.finditer(normalized)
    )
    events: list[RawScrapedEvent] = []

    for index, match in enumerate(matches):
        if match.group("venue") != "大武道場":
            continue

        next_start = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(normalized)
        )
        following_text = normalized[
            match.end():next_start
        ]

        time_match = TIME_RANGE_RE.search(
            following_text
        )
        if not time_match:
            print(
                "[WARN] 東京都剣道連盟の日程から"
                "時刻を取得できません: "
                f"{match.group(0)!r}",
                file=sys.stderr,
            )
            continue

        month = int(match.group("month"))
        day = int(match.group("day"))

        year = (
            fiscal_start_year
            if month >= 4
            else fiscal_start_year + 1
        )

        event_date = dt.date(
            year,
            month,
            day,
        ).isoformat()

        events.append(
            RawScrapedEvent(
                group=organization.name,
                title=(
                    "東京都剣道連盟 "
                    "剣道合同稽古会"
                ),
                date=event_date,
                weekday=match.group("weekday"),
                start_time=time_match.group("start"),
                end_time=time_match.group("end"),
                venue="東京武道館 大武道場",
                area="東京都",
                access=(
                    "東京メトロ千代田線 "
                    "綾瀬駅東口 徒歩5分"
                ),
                note=(
                    "参加費: 800円\n"
                    "対象: 15歳以上"
                    "（中学生を除く）\n"
                    "所属団体が扱う"
                    "スポーツ保険への加入が必要"
                ),
                source_url=source_url,
                event_type=organization.event_type,
            )
        )

    return sorted(
        events,
        key=lambda event: (
            event.date,
            event.start_time or "",
        ),
    )


def scrape(
    organization: Organization,
    debug: bool = False,
) -> list[RawScrapedEvent]:
    page_html = fetch(
        organization.website_url
    )
    pdf_url = find_latest_schedule_pdf_url(
        page_html,
        organization.website_url,
    )

    _debug_print(
        debug,
        f"Tokyo schedule PDF: {pdf_url}",
    )

    pdf_bytes = fetch_pdf_bytes(pdf_url)
    pdf_text = extract_pdf_text(pdf_bytes)

    events = parse_joint_practice_events(
        pdf_text,
        organization,
        pdf_url,
    )

    _debug_print(
        debug,
        f"Tokyo joint practice events: {len(events)}",
    )

    return events
