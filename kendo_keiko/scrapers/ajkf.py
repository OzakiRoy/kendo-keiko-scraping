from __future__ import annotations

import datetime as dt
import re
import sys
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Comment

from kendo_keiko.models import Organization, RawScrapedEvent


def _debug_print(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[DEBUG] {message}", file=sys.stderr)


AJKF_BASE_URL = "https://www.kendo.or.jp"

# 全剣連の稽古会ページは一覧HTMLにイベント本体が出ないため、
# 確認済みの個別ページをseedにして関連する稽古会リンクをたどる。
AJKF_SEED_URLS = [
    "https://www.kendo.or.jp/keiko-kai/kendo-lesson-japan-20260713_tokyo/",
]

WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]

AJKF_PREFECTURE_BY_SLUG = {
    "hokkaido": "北海道",
    "aomori": "青森県",
    "iwate": "岩手県",
    "miyagi": "宮城県",
    "akita": "秋田県",
    "yamagata": "山形県",
    "fukushima": "福島県",
    "ibaraki": "茨城県",
    "tochigi": "栃木県",
    "gunma": "群馬県",
    "saitama": "埼玉県",
    "chiba": "千葉県",
    "tokyo": "東京都",
    "kanagawa": "神奈川県",
    "niigata": "新潟県",
    "toyama": "富山県",
    "ishikawa": "石川県",
    "fukui": "福井県",
    "yamanashi": "山梨県",
    "nagano": "長野県",
    "gifu": "岐阜県",
    "shizuoka": "静岡県",
    "aichi": "愛知県",
    "mie": "三重県",
    "shiga": "滋賀県",
    "kyoto": "京都府",
    "osaka": "大阪府",
    "hyogo": "兵庫県",
    "nara": "奈良県",
    "wakayama": "和歌山県",
    "tottori": "鳥取県",
    "shimane": "島根県",
    "okayama": "岡山県",
    "hiroshima": "広島県",
    "yamaguchi": "山口県",
    "tokushima": "徳島県",
    "kagawa": "香川県",
    "ehime": "愛媛県",
    "kochi": "高知県",
    "fukuoka": "福岡県",
    "saga": "佐賀県",
    "nagasaki": "長崎県",
    "kumamoto": "熊本県",
    "oita": "大分県",
    "miyazaki": "宮崎県",
    "kagoshima": "鹿児島県",
    "okinawa": "沖縄県",
}


def normalize_ajkf_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def strip_html_comments(soup: BeautifulSoup) -> None:
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()


def html_to_ajkf_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    strip_html_comments(soup)

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    return soup.get_text("\n")


def clean_ajkf_text_value(value: Optional[str]) -> Optional[str]:
    if not value:
        return None

    value = re.sub(r"<!--.*?-->", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def extract_ajkf_keiko_links(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = urljoin(AJKF_BASE_URL, a["href"])
        parsed = urlparse(href)

        # LINE/X/Facebook などの共有URLを除外する。
        if parsed.netloc not in {"www.kendo.or.jp", "kendo.or.jp"}:
            continue

        # 全剣連の稽古会個別ページだけ対象にする。
        if not parsed.path.startswith("/keiko-kai/kendo-lesson-"):
            continue

        links.add(normalize_ajkf_url(href))

    return sorted(links)


def extract_ajkf_title(soup: BeautifulSoup, text: str) -> str:
    # og:title が一番安定しやすい。
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = re.sub(r"\s+", " ", og_title["content"]).strip()
        title = re.split(r"\s*[|｜]\s*", title)[0].strip()
        if "剣道合同稽古会" in title:
            return title

    if soup.title and soup.title.string:
        title = re.sub(r"\s+", " ", soup.title.string).strip()
        title = re.split(r"\s*[|｜]\s*", title)[0].strip()
        if "剣道合同稽古会" in title:
            return title

    for selector in ["h1", "h2", "h3"]:
        for tag in soup.find_all(selector):
            title = re.sub(r"\s+", " ", tag.get_text(" ")).strip()
            if "剣道合同稽古会" in title:
                return title

    m = re.search(r"(剣道合同稽古会[^\n]+)", text)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()

    return "全日本剣道連盟 稽古会"


def extract_ajkf_date_from_url(url: str) -> Optional[str]:
    # 例:
    # /keiko-kai/kendo-lesson-japan-20260713_tokyo/
    # /keiko-kai/kendo-lesson-kinki-20260801-kyoto
    m = re.search(r"-(20\d{6})(?:[_-])", url)
    if not m:
        return None

    raw = m.group(1)
    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"


def extract_ajkf_date_from_text(text: str) -> Optional[str]:
    m = re.search(r"開催日\s*[:：]?\s*(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", text)
    if not m:
        m = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", text)

    if not m:
        return None

    y, mo, d = m.groups()
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"


def extract_ajkf_date(text: str, url: str) -> Optional[str]:
    # 関連イベント欄の日付を誤って拾うのを避けるため、まずURLの日付を優先する。
    return extract_ajkf_date_from_url(url) or extract_ajkf_date_from_text(text)


def weekday_ja(date_value: str) -> Optional[str]:
    try:
        return WEEKDAYS_JA[dt.date.fromisoformat(date_value).weekday()]
    except ValueError:
        return None


def extract_ajkf_times(text: str) -> tuple[Optional[str], Optional[str]]:
    m = re.search(r"(\d{1,2}:\d{2})\s*[〜～\-–]\s*(\d{1,2}:\d{2})", text)
    if not m:
        return None, None

    return m.group(1), m.group(2)


def extract_ajkf_venue(text: str) -> Optional[str]:
    m = re.search(r"会場名\s*[:：]?\s*\n?\s*([^\n]+)", text)
    if m:
        venue = clean_ajkf_text_value(m.group(1))
        if venue:
            venue = re.split(r"〒|Google MAP|開催日|行事概要|お知らせをシェア", venue)[0].strip()
            venue = clean_ajkf_text_value(venue)
            if venue:
                return venue

    if "日本武道館" in text:
        return "日本武道館"

    return None


def extract_ajkf_area(*, title: str, text: str, venue: Optional[str], url: str) -> Optional[str]:
    """
    全剣連の合同稽古会ページから都道府県を推定する。

    優先順位:
      1. タイトルの括弧内: 剣道合同稽古会 東海地区（愛知県）
      2. 本文中の都道府県表記
      3. URL末尾slug: ...-aichi / ..._tokyo
    """
    for value in [title, text, venue or ""]:
        m = re.search(r"[（(]([^）)()]+?[都道府県])[）)]", value)
        if m:
            return m.group(1).strip()

    # 括弧なしで会場周辺に都道府県が出る場合のfallback。
    m = re.search(
        r"(北海道|東京都|京都府|大阪府|.{2,3}県)",
        " ".join(v for v in [venue, text] if v),
    )
    if m:
        return m.group(1).strip()

    parsed = urlparse(url)
    slug = parsed.path.rstrip("/").split("-")[-1]
    return AJKF_PREFECTURE_BY_SLUG.get(slug)


def extract_ajkf_fee(text: str) -> Optional[str]:
    if "参加費" in text and "無料" in text:
        return "無料"
    if "参加費は「無料」です" in text:
        return "無料"
    return None


def extract_ajkf_note(text: str, fee: Optional[str]) -> Optional[str]:
    notes: list[str] = []

    # extract_fee() が既存仕様で note から参加費を読むため、明示的に入れておく。
    if fee:
        notes.append(f"参加費: {fee}")

    if "一般の方ならどなたでも参加できます" in text:
        notes.append("一般の方ならどなたでも参加できます。")

    m = re.search(r"(受付[^。]*。)", text)
    if m:
        notes.append(re.sub(r"\s+", " ", m.group(1)).strip())

    notes.append("全日本剣道連盟の公式情報をもとに掲載しています。参加前に必ず公式ページをご確認ください。")

    return " ".join(notes) if notes else None


def parse_ajkf_event_page(*, url: str, organization: Organization) -> Optional[RawScrapedEvent]:
    response = requests.get(
        url,
        headers={"User-Agent": "kendo-keiko.com crawler; contact: https://www.royozaki.net/"},
        timeout=20,
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding

    soup = BeautifulSoup(response.text, "html.parser")
    strip_html_comments(soup)
    text = html_to_ajkf_text(str(soup))

    if "稽古会" not in text:
        return None

    title = extract_ajkf_title(soup, text)

    # 中止イベントは一旦除外する。
    if "中止" in title or "【中止】" in text or "〖中止〗" in text:
        return None

    event_date = extract_ajkf_date(text, url)
    if not event_date:
        return None

    start_time, end_time = extract_ajkf_times(text)
    venue = extract_ajkf_venue(text)
    area = extract_ajkf_area(title=title, text=text, venue=venue, url=url)
    fee = extract_ajkf_fee(text)
    note = extract_ajkf_note(text, fee)

    return RawScrapedEvent(
        group=organization.name,
        title=title,
        date=event_date,
        weekday=weekday_ja(event_date),
        start_time=start_time,
        end_time=end_time,
        venue=venue,
        area=area,
        access=None,
        note=note,
        source_url=url,
        event_type=organization.event_type,
    )


def scrape(org: Organization, debug: bool = False) -> list[RawScrapedEvent]:
    seed_urls = set(AJKF_SEED_URLS)

    # organizations.json の website_url が全剣連の個別稽古会ページならseedに加える。
    if org.website_url and "/keiko-kai/kendo-lesson-" in org.website_url:
        seed_urls.add(org.website_url)

    links: set[str] = {normalize_ajkf_url(url) for url in seed_urls}

    for seed_url in sorted(seed_urls):
        try:
            response = requests.get(
                seed_url,
                headers={"User-Agent": "kendo-keiko.com crawler; contact: https://www.royozaki.net/"},
                timeout=20,
            )
            response.raise_for_status()
            response.encoding = response.apparent_encoding or response.encoding

            for link in extract_ajkf_keiko_links(response.text):
                links.add(link)
        except Exception as e:
            _debug_print(debug, f"[WARN] failed to fetch AJKF seed: {seed_url}: {e}")

    events: list[RawScrapedEvent] = []

    for link in sorted(links):
        try:
            event = parse_ajkf_event_page(url=link, organization=org)
            if event:
                events.append(event)
        except Exception as e:
            _debug_print(debug, f"[WARN] failed to parse AJKF event: {link}: {e}")

    _debug_print(debug, f"AJKF links={len(links)} events={len(events)}")
    return events
