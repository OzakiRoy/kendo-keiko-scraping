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
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from kendo_keiko.models import Organization, ServiceEvent
from kendo_keiko.pipeline import JST, parse_from_date, run_pipeline
from kendo_keiko.repository import load_organizations, save_dynamodb

DEFAULT_ORGANIZATIONS_PATH = Path("data/organizations.json")
DEFAULT_EVENTS_OUTPUT_PATH = Path("data/events.json")
DEFAULT_TABLE_NAME = "KendoKeikoEvents"
DEFAULT_REGION = "ap-northeast-1"



def debug_print(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[DEBUG] {message}", file=sys.stderr)


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

    filter_from_date = None
    if not args.include_past:
        try:
            filter_from_date = parse_from_date(args.from_date)
        except ValueError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            return 1

    scraped_at = dt.datetime.now(JST).isoformat(timespec="seconds")
    events = run_pipeline(
        organizations=organizations,
        scraped_at=scraped_at,
        from_date=filter_from_date,
        debug=args.debug,
    )

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
