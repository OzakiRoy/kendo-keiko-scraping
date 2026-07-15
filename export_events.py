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
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import boto3

from scrape_kendo_schedule import (
    JST,
    dedupe_events,
    filter_events_from_date,
    parse_from_date,
)

from kendo_keiko.models import (
    Organization,
    RawScrapedEvent,
    ServiceEvent,
)

from kendo_keiko.scrapers.ajkf import scrape as scrape_ajkf
from kendo_keiko.scrapers.kent import scrape as scrape_kent
from kendo_keiko.scrapers.kenkyukai import scrape as scrape_kenkyukai
from kendo_keiko.scrapers.kenbokukai import scrape as scrape_kenbokukai

DEFAULT_ORGANIZATIONS_PATH = Path("data/organizations.json")
DEFAULT_EVENTS_OUTPUT_PATH = Path("data/events.json")
DEFAULT_TABLE_NAME = "KendoKeikoEvents"
DEFAULT_REGION = "ap-northeast-1"



def debug_print(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[DEBUG] {message}", file=sys.stderr)


def load_organizations(path: Path) -> list[Organization]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Organization(**item) for item in raw]



def scrape_by_org(org: Organization, debug: bool = False):
    if not org.scraper_enabled:
        debug_print(debug, f"scraper disabled: {org.organization_id}")
        return []

    if org.scraper_type == "kent":
        return scrape_kent(org, debug=debug)

    if org.scraper_type == "kenkyukai":
        return scrape_kenkyukai(org, debug=debug)

    if org.scraper_type == "kenbokukai":
        return scrape_kenbokukai(org, debug=debug)

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
