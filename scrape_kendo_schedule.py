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
import html
import json
import re
import sys
from dataclasses import asdict
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from kendo_keiko.models import RawScrapedEvent


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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; kendo-schedule-scraper/1.2; "
        "+https://example.com/local-script)"
    )
}

JST = ZoneInfo("Asia/Tokyo")


def debug_print(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[DEBUG] {message}", file=sys.stderr)


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


def normalize_title(text: str) -> str:
    """
    WordPress APIのtitle.renderedなどからHTMLタグを除去する。
    """
    return BeautifulSoup(html.unescape(text), "html.parser").get_text("", strip=True)


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u3000", " ")).strip()


def parse_wp_posts(site_url: str, per_page: int = 10) -> list[dict]:
    """
    WordPress REST API から投稿を取得する。
    APIが閉じている場合もあるので、呼び出し元で例外を拾ってHTML fallbackする。
    """
    api_url = site_url.rstrip("/") + (
        "/wp-json/wp/v2/posts"
        f"?per_page={per_page}"
        "&_fields=date,link,title,content,excerpt"
    )
    raw = fetch(api_url)
    return json.loads(raw)


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


def normalize_weekday(value: Optional[str]) -> Optional[str]:
    if not value:
        return None

    value = value.strip()
    value = value.replace("曜日", "")
    return value[:1] if value else None


def trim_label_value(value: str) -> str:
    """
    1行に複数ラベルが詰まっている場合に、次のラベル以降を削る。
    例:
      参加費：500円■ 場所：xxx
      => 500円
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
    会場名の中に 〖最寄り駅：西葛西駅〗 のような補足があれば access に分離する。
    """
    venue_raw = trim_label_value(venue_raw)
    access = None

    m = re.search(r"〖(?P<access>.*?)〗", venue_raw)
    if m:
        access = normalize_space(m.group("access"))
        venue_raw = re.sub(r"〖.*?〗", "", venue_raw)

    return normalize_space(venue_raw), access


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


def is_kenbokukai_title(line: str) -> bool:
    """
    剣睦会のイベント見出しらしい行かどうか。
    """
    clean = line.strip("# 　\t")
    if not clean or len(clean) > 120:
        return False

    if "稽古会情報" in clean:
        return False

    keywords = ("剣道練習会", "稽古会", "練成会", "練習試合")
    return any(k in clean for k in keywords)


def collect_kenbokukai_event_block(lines: list[str], date_index: int) -> str:
    """
    日付行から次のイベント見出し・次の日付までを1イベントのブロックとして集める。
    """
    block_lines: list[str] = [lines[date_index]]

    for line in lines[date_index + 1 : date_index + 15]:
        if KENBOKUKAI_DATE_RE.search(line):
            break

        if is_kenbokukai_title(line):
            break

        # 記事後半の説明セクションに入ったら打ち切る
        if "剣睦会とは" in line or "剣睦会の特徴" in line or "剣道をもっと楽しみたい方へ" in line:
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
    """
    剣睦会向け。
    「■ 日付」「■ 時間」「■ 場所」のラベル付き情報から稽古予定を抽出する。
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    events: list[RawScrapedEvent] = []
    last_title: Optional[str] = None

    for i, line in enumerate(lines):
        if is_kenbokukai_title(line):
            last_title = line.strip("# 『』 ")

        # ホームページの抜粋では「タイトル ■ 日付：...」が1行に詰まることがある。
        if "日付" in line:
            prefix = line.split("日付", 1)[0].strip("■□ #『』 　\t")
            if is_kenbokukai_title(prefix):
                last_title = prefix

        if "日付" not in line:
            continue

        # line単体でなく、以降のラベル行も含めたブロックにしてから正規表現で抜く
        block_text = collect_kenbokukai_event_block(lines, i)

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

        # 申し込み必須など、参加可否に影響する注意だけ拾う
        for note_line in lines[i + 1 : i + 15]:
            if "事前申し込み" in note_line or "申し込み必須" in note_line:
                note_parts.append(note_line)
                break

        note = " / ".join(note_parts) if note_parts else None

        event = RawScrapedEvent(
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
            note=note,
            source_url=source_url,
        )
        events.append(event)

    return events


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


def extract_same_domain_archive_links(site_url: str, raw_html: str, limit: int = 20) -> list[str]:
    """
    トップページなどから /archives/ の個別記事リンクを抽出する。
    剣睦会はトップページの「最新情報」から個別記事へ辿る方が安定する。
    """
    soup = BeautifulSoup(raw_html, "html.parser")
    base_host = urlparse(site_url).netloc

    links: list[str] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = urljoin(site_url, a["href"])
        parsed = urlparse(href)

        if parsed.netloc != base_host:
            continue

        if "/archives/" not in parsed.path:
            continue

        # #fragmentやqueryは落とす
        clean = parsed._replace(query="", fragment="").geturl()

        if clean in seen:
            continue

        seen.add(clean)
        links.append(clean)

        if len(links) >= limit:
            break

    return links


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


def scrape_kenkyukai(debug: bool = False) -> list[RawScrapedEvent]:
    """
    剣究会の新着情報から稽古予定を取得する。
    まずWordPress REST APIを試し、駄目ならトップページHTMLにfallbackする。
    """
    site = SITES["kenkyukai"]
    events: list[RawScrapedEvent] = []

    try:
        posts = parse_wp_posts(site["url"], per_page=10)
        debug_print(debug, f"剣究会 WP posts: {len(posts)}")

        for post in posts:
            title = normalize_title(post.get("title", {}).get("rendered", ""))
            link = post.get("link") or site["url"]

            post_date_raw = post.get("date", "")
            try:
                base_date = dt.date.fromisoformat(post_date_raw[:10])
            except ValueError:
                base_date = dt.datetime.now(JST).date()

            body_html = (
                post.get("content", {}).get("rendered", "")
                or post.get("excerpt", {}).get("rendered", "")
            )

            text = title + "\n" + html_to_text(body_html)

            parsed = parse_events_from_text(
                group=site["name"],
                event_type=site["event_type"],
                text=text,
                source_url=link,
                base_date=base_date,
            )
            events.extend(parsed)

    except Exception as e:
        print(
            f"[WARN] 剣究会のWordPress API取得に失敗しました。HTML fallbackします: {e}",
            file=sys.stderr,
        )

        raw = fetch(site["url"])
        text = html_to_text(raw)

        events.extend(
            parse_events_from_text(
                group=site["name"],
                event_type=site["event_type"],
                text=text,
                source_url=site["url"],
            )
        )

    debug_print(debug, f"剣究会 parsed events: {len(events)}")
    return events


def scrape_kenbokukai(debug: bool = False) -> list[RawScrapedEvent]:
    """
    剣睦会の最新情報から稽古予定を取得する。

    v2の方針:
      1. WordPress REST APIも試す
      2. トップページHTMLから /archives/ の個別記事リンクを抽出
      3. 個別記事を取得して「■ 日付」「■ 時間」「■ 場所」を読む
      4. APIで0件でもHTMLリンク巡回を必ず試す

    剣睦会はトップページの抜粋だけだと「場所」が省略されることがあるため、
    個別記事を辿る方がWebサービス向き。
    """
    site = SITES["kenbokukai"]
    events: list[RawScrapedEvent] = []

    # 1. WordPress API
    try:
        posts = parse_wp_posts(site["url"], per_page=10)
        debug_print(debug, f"剣睦会 WP posts: {len(posts)}")

        for post in posts:
            title = normalize_title(post.get("title", {}).get("rendered", ""))
            link = post.get("link") or site["url"]

            body_html = (
                post.get("content", {}).get("rendered", "")
                or post.get("excerpt", {}).get("rendered", "")
            )
            text = title + "\n" + html_to_text(body_html)

            if "稽古会情報" not in title and "日付" not in text:
                continue

            parsed = parse_kenbokukai_events_from_text(
                group=site["name"],
                event_type=site["event_type"],
                text=text,
                source_url=link,
            )
            events.extend(parsed)

    except Exception as e:
        print(
            f"[WARN] 剣睦会のWordPress API取得に失敗しました。HTMLリンク巡回へ進みます: {e}",
            file=sys.stderr,
        )

    debug_print(debug, f"剣睦会 events after WP API: {len(events)}")

    # 2. HTMLリンク巡回。APIで取れていても、個別記事HTMLの方が場所まで取りやすいので必ず実行。
    try:
        home_html = fetch(site["url"])
        article_links = extract_same_domain_archive_links(site["url"], home_html, limit=20)
        debug_print(debug, f"剣睦会 archive links from home: {len(article_links)}")

        for link in article_links:
            try:
                article_html = fetch(link)
            except requests.RequestException as e:
                print(f"[WARN] 剣睦会記事の取得に失敗しました: {link} ({e})", file=sys.stderr)
                continue

            title = ""
            soup = BeautifulSoup(article_html, "html.parser")
            h1 = soup.find("h1")
            if h1:
                title = h1.get_text(" ", strip=True)

            text = title + "\n" + html_to_text(article_html)

            if "稽古会情報" not in title and "日付" not in text:
                continue

            parsed = parse_kenbokukai_events_from_text(
                group=site["name"],
                event_type=site["event_type"],
                text=text,
                source_url=link,
            )
            debug_print(debug, f"剣睦会 parsed from {link}: {len(parsed)}")
            events.extend(parsed)

        # リンクが1件も取れない場合だけ、トップページ本文自体も最後のfallbackとして読む
        if not article_links:
            text = html_to_text(home_html)
            parsed = parse_kenbokukai_events_from_text(
                group=site["name"],
                event_type=site["event_type"],
                text=text,
                source_url=site["url"],
            )
            events.extend(parsed)

    except requests.RequestException as e:
        print(f"[WARN] 剣睦会HTMLリンク巡回に失敗しました: {e}", file=sys.stderr)

    debug_print(debug, f"剣睦会 parsed events total before dedupe/filter: {len(events)}")
    return events


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
