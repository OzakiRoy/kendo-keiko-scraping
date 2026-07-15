from __future__ import annotations

import re
import sys
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from kendo_keiko.models import Organization, RawScrapedEvent
from kendo_keiko.scrapers.common import (
    fetch,
    html_to_text,
    normalize_title,
    normalize_weekday,
    parse_wp_posts,
)


# 剣睦会向け:
# 例:
#   ■ 日付：2026年8月8日 (土)
#   ■ 時間：13:00～17:00
#   ■ 場所：江戸川区スポーツセンター1階〖最寄り駅：西葛西駅〗
#
# HTMLの整形により「日付：」と日付本体が別行になることもあるので、
# parse側では複数行をスペース結合した block_text に対して検索する。
KENBOKUKAI_DATE_RE = re.compile(
    r"""
    (?:[■□]\s*)?
    日付[:：]\s*
    (?P<year>\d{4})年\s*
    (?P<month>\d{1,2})月\s*
    (?P<day>\d{1,2})日
    \s*
    (?:[（(]?\s*(?P<weekday>月曜日|火曜日|水曜日|木曜日|金曜日|土曜日|日曜日|[月火水木金土日])\s*[）)]?)?
    """,
    re.VERBOSE,
)

TIME_LABEL_RE = re.compile(
    r"""
    (?:[■□]\s*)?
    時間[:：]\s*
    (?P<start>\d{1,2}:\d{2})
    \s*[~\-ー]\s*
    (?P<end>\d{1,2}:\d{2})
    """,
    re.VERBOSE,
)

VENUE_LABEL_RE = re.compile(
    r"""
    (?:[■□]\s*)?
    (?:場所|会場)[:：]\s*
    (?P<venue>.+?)
    (?=
        \s*[■□]\s*(?:日付|時間|持ち物|参加費|場所|会場|ご参加|剣睦会とは)[:：]?
        |
        \s*https?://
        |
        \s*$
    )
    """,
    re.VERBOSE,
)

FEE_LABEL_RE = re.compile(
    r"""
    (?:[■□]\s*)?
    参加費[:：]\s*
    (?P<fee>.+?)
    (?=
        \s*[■□]\s*(?:日付|時間|持ち物|参加費|場所|会場|ご参加|剣睦会とは)[:：]?
        |
        \s*$
    )
    """,
    re.VERBOSE,
)


def _debug_print(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[DEBUG] {message}", file=sys.stderr)


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u3000", " ")).strip()


def trim_label_value(value: str) -> str:
    """
    1行に複数ラベルが詰まっている場合に、次のラベル以降を削る。
    """
    value = re.sub(r"https?://\S+", "", value)
    value = re.split(
        r"\s*[■□]\s*(?:日付|時間|持ち物|参加費|場所|会場|ご参加|剣睦会とは)[:：]?",
        value,
        maxsplit=1,
    )[0]
    return normalize_space(value)


def split_venue_access(venue_raw: str) -> tuple[str, Optional[str]]:
    """
    会場名の中に 〖最寄り駅：西葛西駅〗 のような補足があればaccessへ分離する。
    """
    venue_raw = trim_label_value(venue_raw)
    access = None

    match = re.search(r"〖(?P<access>.*?)〗", venue_raw)
    if match:
        access = normalize_space(match.group("access"))
        venue_raw = re.sub(r"〖.*?〗", "", venue_raw)

    return normalize_space(venue_raw), access


def is_kenbokukai_title(line: str) -> bool:
    clean = line.strip("# 　\t")
    if not clean or len(clean) > 120:
        return False

    if "稽古会情報" in clean:
        return False

    keywords = ("剣道練習会", "稽古会", "練成会", "練習試合")
    return any(keyword in clean for keyword in keywords)


def collect_kenbokukai_event_block(lines: list[str], date_index: int) -> str:
    block_lines: list[str] = [lines[date_index]]

    for line in lines[date_index + 1 : date_index + 15]:
        if KENBOKUKAI_DATE_RE.search(line):
            break

        if is_kenbokukai_title(line):
            break

        if (
            "剣睦会とは" in line
            or "剣睦会の特徴" in line
            or "剣道をもっと楽しみたい方へ" in line
        ):
            break

        block_lines.append(line)

    return normalize_space(" ".join(block_lines))


def parse_kenbokukai_events_from_text(
    *,
    group: str,
    event_type: str,
    text: str,
    source_url: str,
) -> list[RawScrapedEvent]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    events: list[RawScrapedEvent] = []
    last_title: Optional[str] = None

    for index, line in enumerate(lines):
        if is_kenbokukai_title(line):
            last_title = line.strip("# 『』 ")

        if "日付" in line:
            prefix = line.split("日付", 1)[0].strip("■□ #『』 　\t")
            if is_kenbokukai_title(prefix):
                last_title = prefix

        if "日付" not in line:
            continue

        block_text = collect_kenbokukai_event_block(lines, index)
        date_match = KENBOKUKAI_DATE_RE.search(block_text)
        if not date_match:
            continue

        time_match = TIME_LABEL_RE.search(block_text)
        venue_match = VENUE_LABEL_RE.search(block_text)
        fee_match = FEE_LABEL_RE.search(block_text)

        venue = None
        access = None
        if venue_match:
            venue, access = split_venue_access(venue_match.group("venue"))

        note_parts: list[str] = []
        if fee_match:
            fee = trim_label_value(fee_match.group("fee"))
            if fee:
                note_parts.append(f"参加費: {fee}")

        for note_line in lines[index + 1 : index + 15]:
            if "事前申し込み" in note_line or "申し込み必須" in note_line:
                note_parts.append(note_line)
                break

        events.append(
            RawScrapedEvent(
                group=group,
                event_type=event_type,
                title=last_title,
                date=(
                    f"{int(date_match.group('year')):04d}-"
                    f"{int(date_match.group('month')):02d}-"
                    f"{int(date_match.group('day')):02d}"
                ),
                weekday=normalize_weekday(date_match.group("weekday")),
                start_time=time_match.group("start") if time_match else None,
                end_time=time_match.group("end") if time_match else None,
                venue=venue,
                area=None,
                access=access,
                note=" / ".join(note_parts) if note_parts else None,
                source_url=source_url,
            )
        )

    return events


def extract_same_domain_archive_links(
    site_url: str,
    raw_html: str,
    limit: int = 20,
) -> list[str]:
    soup = BeautifulSoup(raw_html, "html.parser")
    base_host = urlparse(site_url).netloc

    links: list[str] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = urljoin(site_url, anchor["href"])
        parsed = urlparse(href)

        if parsed.netloc != base_host or "/archives/" not in parsed.path:
            continue

        clean = parsed._replace(query="", fragment="").geturl()
        if clean in seen:
            continue

        seen.add(clean)
        links.append(clean)

        if len(links) >= limit:
            break

    return links


def scrape(
    organization: Organization,
    debug: bool = False,
) -> list[RawScrapedEvent]:
    events: list[RawScrapedEvent] = []

    try:
        posts = parse_wp_posts(organization.website_url, per_page=10)
        _debug_print(debug, f"剣睦会 WP posts: {len(posts)}")

        for post in posts:
            title = normalize_title(post.get("title", {}).get("rendered", ""))
            link = post.get("link") or organization.website_url
            body_html = (
                post.get("content", {}).get("rendered", "")
                or post.get("excerpt", {}).get("rendered", "")
            )
            text = title + "\n" + html_to_text(body_html)

            if "稽古会情報" not in title and "日付" not in text:
                continue

            events.extend(
                parse_kenbokukai_events_from_text(
                    group=organization.name,
                    event_type=organization.event_type,
                    text=text,
                    source_url=link,
                )
            )

    except Exception as exc:
        print(
            "[WARN] 剣睦会のWordPress API取得に失敗しました。"
            f"HTMLリンク巡回へ進みます: {exc}",
            file=sys.stderr,
        )

    _debug_print(debug, f"剣睦会 events after WP API: {len(events)}")

    try:
        home_html = fetch(organization.website_url)
        article_links = extract_same_domain_archive_links(
            organization.website_url,
            home_html,
            limit=20,
        )
        _debug_print(debug, f"剣睦会 archive links from home: {len(article_links)}")

        for link in article_links:
            try:
                article_html = fetch(link)
            except requests.RequestException as exc:
                print(
                    f"[WARN] 剣睦会記事の取得に失敗しました: {link} ({exc})",
                    file=sys.stderr,
                )
                continue

            soup = BeautifulSoup(article_html, "html.parser")
            heading = soup.find("h1")
            title = heading.get_text(" ", strip=True) if heading else ""
            text = title + "\n" + html_to_text(article_html)

            if "稽古会情報" not in title and "日付" not in text:
                continue

            parsed = parse_kenbokukai_events_from_text(
                group=organization.name,
                event_type=organization.event_type,
                text=text,
                source_url=link,
            )
            _debug_print(debug, f"剣睦会 parsed from {link}: {len(parsed)}")
            events.extend(parsed)

        if not article_links:
            events.extend(
                parse_kenbokukai_events_from_text(
                    group=organization.name,
                    event_type=organization.event_type,
                    text=html_to_text(home_html),
                    source_url=organization.website_url,
                )
            )

    except requests.RequestException as exc:
        print(
            f"[WARN] 剣睦会HTMLリンク巡回に失敗しました: {exc}",
            file=sys.stderr,
        )

    _debug_print(
        debug,
        f"剣睦会 parsed events total before dedupe/filter: {len(events)}",
    )
    return events
