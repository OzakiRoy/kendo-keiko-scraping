#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
スクレイピング結果をサービス用JSONまたはDynamoDBへ保存するレイヤー。

既存の scrape_kendo_schedule.py はなるべく壊さず、以下を担当する。
  - data/organizations.json の団体マスタを読む
  - scraper を実行する
  - organization_id / event_id / gsi1_pk / gsi1_sk 付きのサービス用データへ正規化する
  - ローカルでは data/events.json に保存する
  - AWSでは DynamoDB に保存する

実行例:
  # ローカルJSONへ保存
  python export_events.py --output data/events.json

  # テキスト確認
  python export_events.py --group kenbokukai --format text

  # DynamoDBへ保存
  python export_events.py \
    --storage dynamodb \
    --table-name KendoKeikoEvents \
    --region ap-northeast-1 \
    --no-stdout \
    --debug
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse

import boto3
import requests
from bs4 import BeautifulSoup, Comment

from scrape_kendo_schedule import (
    JST,
    dedupe_events,
    filter_events_from_date,
    parse_from_date,
    scrape_kent,
    scrape_kenbokukai,
    scrape_kenkyukai,
)

DEFAULT_ORGANIZATIONS_PATH = Path("data/organizations.json")
DEFAULT_EVENTS_OUTPUT_PATH = Path("data/events.json")
DEFAULT_TABLE_NAME = "KendoKeikoEvents"
DEFAULT_REGION = "ap-northeast-1"


@dataclass(frozen=True)
class Organization:
    organization_id: str
    name: str
    area: Optional[str]
    website_url: str
    source_type: str
    scraper_type: str
    scraper_enabled: bool
    event_type: str
    notes: Optional[str] = None




@dataclass(frozen=True)
class RawScrapedEvent:
    """
    export_events.py 内で追加スクレイパーが返す軽量イベント。

    既存の scrape_kendo_schedule.KeikoEvent と同じ主要属性に加えて、
    normalize_events() が参照している event_type を持たせる。
    """
    group: str
    title: Optional[str]
    date: str
    weekday: Optional[str]
    start_time: Optional[str]
    end_time: Optional[str]
    venue: Optional[str]
    area: Optional[str]
    access: Optional[str]
    note: Optional[str]
    source_url: str
    event_type: str


@dataclass(frozen=True)
class ServiceEvent:
    event_id: str
    organization_id: str
    organization_name: str
    event_type: str
    title: Optional[str]
    event_date: str
    weekday: Optional[str]
    start_time: Optional[str]
    end_time: Optional[str]
    venue: Optional[str]
    area: Optional[str]
    address: Optional[str]
    access: Optional[str]
    fee: Optional[str]
    application_required: Optional[bool]
    source_url: str
    source_type: str
    last_scraped_at: str
    status: str
    raw_note: Optional[str]

    # DynamoDB DateIndex 用
    # DateIndex:
    #   Partition key: gsi1_pk
    #   Sort key:      gsi1_sk
    gsi1_pk: str
    gsi1_sk: str


def debug_print(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[DEBUG] {message}", file=sys.stderr)


def load_organizations(path: Path) -> list[Organization]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Organization(**item) for item in raw]


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


def scrape_ajkf(org: Organization, debug: bool = False) -> list[RawScrapedEvent]:
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
            debug_print(debug, f"[WARN] failed to fetch AJKF seed: {seed_url}: {e}")

    events: list[RawScrapedEvent] = []

    for link in sorted(links):
        try:
            event = parse_ajkf_event_page(url=link, organization=org)
            if event:
                events.append(event)
        except Exception as e:
            debug_print(debug, f"[WARN] failed to parse AJKF event: {link}: {e}")

    debug_print(debug, f"AJKF links={len(links)} events={len(events)}")
    return events


def scrape_by_org(org: Organization, debug: bool = False):
    if not org.scraper_enabled:
        debug_print(debug, f"scraper disabled: {org.organization_id}")
        return []

    if org.scraper_type == "kent":
        return scrape_kent()

    if org.scraper_type == "kenkyukai":
        return scrape_kenkyukai(debug=debug)

    if org.scraper_type == "kenbokukai":
        return scrape_kenbokukai(debug=debug)

    if org.scraper_type == "ajkf":
        return scrape_ajkf(org, debug=debug)

    print(f"[WARN] unknown scraper_type: {org.scraper_type}", file=sys.stderr)
    return []


def make_event_id(
    *,
    org_id: str,
    event_date: str,
    start_time: Optional[str],
    end_time: Optional[str],
    venue: Optional[str],
    title: Optional[str],
    source_url: str,
) -> str:
    """
    DynamoDBの主キーとして使う安定IDを生成する。

    例:
      kenbokukai-20260808-1300-a1b2c3d4
    """
    start = (start_time or "unknown").replace(":", "")
    date_part = event_date.replace("-", "")
    base = "|".join(
        [
            org_id,
            event_date,
            start_time or "",
            end_time or "",
            venue or "",
            title or "",
            source_url,
        ]
    )
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
    return f"{org_id}-{date_part}-{start}-{digest}"


def make_gsi1_keys(
    *,
    event_date: str,
    start_time: Optional[str],
    organization_id: str,
    event_id: str,
) -> tuple[str, str]:
    """
    DateIndex 用のキーを生成する。

    gsi1_pk はMVPでは全イベント共通で EVENT。
    gsi1_sk は日付順に並ぶようにする。

    例:
      gsi1_pk = EVENT
      gsi1_sk = 2026-08-08#13:00#kenbokukai#kenbokukai-20260808-1300-a1b2c3d4
    """
    safe_start_time = start_time or "00:00"
    return "EVENT", f"{event_date}#{safe_start_time}#{organization_id}#{event_id}"


def extract_fee(note: Optional[str]) -> Optional[str]:
    if not note:
        return None

    m = re.search(r"参加費[:：]\s*(?P<fee>.+)", note)
    if not m:
        return None

    return re.sub(r"\s+", " ", m.group("fee")).strip()


def infer_application_required(note: Optional[str], title: Optional[str]) -> Optional[bool]:
    text = " ".join(v for v in [note, title] if v)
    if not text:
        return None

    if "事前申し込み" in text or "申込必須" in text or "申し込み必須" in text:
        return True

    if "申込不要" in text or "予約不要" in text or "自由参加" in text:
        return False

    return None


def normalize_events(raw_events, organizations: list[Organization], scraped_at: str) -> list[ServiceEvent]:
    org_by_name = {org.name: org for org in organizations}

    service_events: list[ServiceEvent] = []

    for raw in raw_events:
        org = org_by_name.get(raw.group)
        if not org:
            print(f"[WARN] organization not found for group: {raw.group}", file=sys.stderr)
            continue

        raw_area = getattr(raw, "area", None)

        event_id = make_event_id(
            org_id=org.organization_id,
            event_date=raw.date,
            start_time=raw.start_time,
            end_time=raw.end_time,
            venue=raw.venue,
            title=raw.title,
            source_url=raw.source_url,
        )
        gsi1_pk, gsi1_sk = make_gsi1_keys(
            event_date=raw.date,
            start_time=raw.start_time,
            organization_id=org.organization_id,
            event_id=event_id,
        )

        service_events.append(
            ServiceEvent(
                event_id=event_id,
                organization_id=org.organization_id,
                organization_name=org.name,
                event_type=raw.event_type,
                title=raw.title,
                event_date=raw.date,
                weekday=raw.weekday,
                start_time=raw.start_time,
                end_time=raw.end_time,
                venue=raw.venue,
                area=raw_area or org.area,
                address=None,
                access=raw.access,
                fee=extract_fee(raw.note),
                application_required=infer_application_required(raw.note, raw.title),
                source_url=raw.source_url,
                source_type=org.source_type,
                last_scraped_at=scraped_at,
                status="active",
                raw_note=raw.note,
                gsi1_pk=gsi1_pk,
                gsi1_sk=gsi1_sk,
            )
        )

    return sorted(service_events, key=lambda e: (e.event_date, e.start_time or "", e.organization_id))


def build_payload(
    *,
    events: list[ServiceEvent],
    organizations: list[Organization],
    scraped_at: str,
    from_date: Optional[str],
    include_past: bool,
) -> dict:
    return {
        "schema_version": "0.2",
        "generated_at": scraped_at,
        "timezone": "Asia/Tokyo",
        "from_date": from_date,
        "include_past": include_past,
        "organization_count": len(organizations),
        "event_count": len(events),
        "events": [asdict(e) for e in events],
    }


def save_json(
    *,
    output_path: Path,
    events: list[ServiceEvent],
    organizations: list[Organization],
    scraped_at: str,
    from_date: Optional[str],
    include_past: bool,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_payload(
        events=events,
        organizations=organizations,
        scraped_at=scraped_at,
        from_date=from_date,
        include_past=include_past,
    )
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def remove_none_values(item: dict) -> dict:
    """
    DynamoDBに保存する前に None の属性を除去する。
    MVPでは NULL として保存するより、属性自体を省略する方が扱いやすい。
    """
    return {k: v for k, v in item.items() if v is not None}


def save_dynamodb(*, events: list[ServiceEvent], table_name: str, region: str) -> None:
    """
    DynamoDBへイベント情報を保存する。
    同じ event_id のItemは上書きされる。
    """
    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)

    with table.batch_writer() as batch:
        for event in events:
            item = remove_none_values(asdict(event))
            batch.put_item(Item=item)


def format_text(events: list[ServiceEvent]) -> str:
    if not events:
        return "該当する稽古予定は見つかりませんでした。"

    lines: list[str] = []
    current_org = None

    for e in events:
        if e.organization_name != current_org:
            if lines:
                lines.append("")
            lines.append(f"## {e.organization_name}")
            current_org = e.organization_name

        time_part = f" {e.start_time}-{e.end_time}" if e.start_time and e.end_time else ""
        venue_part = f" @ {e.venue}" if e.venue else ""
        access_part = f"（{e.access}）" if e.access else ""
        title_part = f" / {e.title}" if e.title else ""
        fee_part = f" / 参加費: {e.fee}" if e.fee else ""
        lines.append(
            f"- {e.event_date}({e.weekday}){time_part}{venue_part}{access_part}{title_part}{fee_part} / {e.source_url}"
        )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="稽古会スクレイピング結果をサービス用データとして保存します。")
    parser.add_argument(
        "--organizations",
        default=str(DEFAULT_ORGANIZATIONS_PATH),
        help="団体マスタJSON。default: data/organizations.json",
    )
    parser.add_argument(
        "--storage",
        choices=["json", "dynamodb"],
        default="json",
        help="保存先。default: json",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_EVENTS_OUTPUT_PATH),
        help="保存先JSON。default: data/events.json",
    )
    parser.add_argument(
        "--table-name",
        default=DEFAULT_TABLE_NAME,
        help="DynamoDBテーブル名。default: KendoKeikoEvents",
    )
    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        help="AWSリージョン。default: ap-northeast-1",
    )
    parser.add_argument(
        "--group",
        default="all",
        help="all または organization_id。例: kenbokukai",
    )
    parser.add_argument(
        "--from-date",
        help="この日付以降の稽古だけ出力。例: 2026-07-09。未指定なら今日 JST",
    )
    parser.add_argument(
        "--include-past",
        action="store_true",
        help="過去分も含める",
    )
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="標準出力の形式。default: text",
    )
    parser.add_argument(
        "--no-stdout",
        action="store_true",
        help="標準出力を抑止",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="デバッグ出力",
    )
    args = parser.parse_args()

    try:
        organizations = load_organizations(Path(args.organizations))
    except Exception as e:
        print(f"[ERROR] organizations.json を読み込めません: {e}", file=sys.stderr)
        return 1

    if args.group != "all":
        organizations = [org for org in organizations if org.organization_id == args.group]
        if not organizations:
            print(f"[ERROR] organization_id が見つかりません: {args.group}", file=sys.stderr)
            return 1

    raw_events = []
    for org in organizations:
        debug_print(args.debug, f"scrape: {org.organization_id}")
        raw_events.extend(scrape_by_org(org, debug=args.debug))

    debug_print(args.debug, f"raw events before dedupe: {len(raw_events)}")
    raw_events = dedupe_events(raw_events)
    debug_print(args.debug, f"raw events after dedupe: {len(raw_events)}")

    filter_from_date = None
    if not args.include_past:
        try:
            filter_from_date = parse_from_date(args.from_date)
        except ValueError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            return 1
        raw_events = filter_events_from_date(raw_events, filter_from_date)
        debug_print(args.debug, f"raw events after date filter: {len(raw_events)}")

    scraped_at = dt.datetime.now(JST).isoformat(timespec="seconds")
    events = normalize_events(raw_events, organizations, scraped_at)

    from_date_text = filter_from_date.isoformat() if filter_from_date else None

    if args.storage == "json":
        save_json(
            output_path=Path(args.output),
            events=events,
            organizations=organizations,
            scraped_at=scraped_at,
            from_date=from_date_text,
            include_past=args.include_past,
        )
        print(f"[INFO] saved JSON: {args.output}", file=sys.stderr)

    elif args.storage == "dynamodb":
        try:
            save_dynamodb(events=events, table_name=args.table_name, region=args.region)
        except Exception as e:
            print(f"[ERROR] DynamoDB保存に失敗しました: {e}", file=sys.stderr)
            return 2
        print(f"[INFO] saved DynamoDB: table={args.table_name}, count={len(events)}", file=sys.stderr)

    if not args.no_stdout:
        if args.format == "text":
            print(format_text(events))
        else:
            payload = build_payload(
                events=events,
                organizations=organizations,
                scraped_at=scraped_at,
                from_date=from_date_text,
                include_past=args.include_past,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
