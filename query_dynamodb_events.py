#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
DynamoDB の KendoKeikoEvents から今後の稽古会を取得して、
静的HTMLで表示しやすい JSON に出力する。

使い方:
  python query_dynamodb_events.py --output public/events.json

特定日以降:
  python query_dynamodb_events.py --from-date 2026-07-09 --output public/events.json

テーブル名・リージョン指定:
  python query_dynamodb_events.py \
    --table-name KendoKeikoEvents \
    --region ap-northeast-1 \
    --output public/events.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import boto3
from boto3.dynamodb.conditions import Key


JST = ZoneInfo("Asia/Tokyo")


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def parse_from_date(value: str | None) -> dt.date:
    if value:
        return dt.date.fromisoformat(value)
    return dt.datetime.now(JST).date()


def query_events(
    *,
    table_name: str,
    region_name: str,
    from_date: dt.date,
    limit: int | None,
) -> list[dict[str, Any]]:
    dynamodb = boto3.resource("dynamodb", region_name=region_name)
    table = dynamodb.Table(table_name)

    # gsi1_sk は "YYYY-MM-DD#HH:MM#organization_id#event_id" なので、
    # "YYYY-MM-DD" 以上で検索すれば、その日以降のイベントを取得できる。
    kwargs: dict[str, Any] = {
        "IndexName": "DateIndex",
        "KeyConditionExpression": Key("gsi1_pk").eq("EVENT")
        & Key("gsi1_sk").gte(from_date.isoformat()),
    }

    if limit:
        kwargs["Limit"] = limit

    events: list[dict[str, Any]] = []
    last_evaluated_key = None

    while True:
        if last_evaluated_key:
            kwargs["ExclusiveStartKey"] = last_evaluated_key

        response = table.query(**kwargs)
        events.extend(response.get("Items", []))

        if limit and len(events) >= limit:
            events = events[:limit]
            break

        last_evaluated_key = response.get("LastEvaluatedKey")
        if not last_evaluated_key:
            break

    return sorted(
        events,
        key=lambda e: (
            e.get("event_date", ""),
            e.get("start_time", ""),
            e.get("organization_id", ""),
        ),
    )


def save_json(
    *,
    events: list[dict[str, Any]],
    output_path: Path,
    table_name: str,
    region_name: str,
    from_date: dt.date,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema_version": "viewer-0.1",
        "generated_at": dt.datetime.now(JST).isoformat(timespec="seconds"),
        "timezone": "Asia/Tokyo",
        "source": "dynamodb",
        "table_name": table_name,
        "region": region_name,
        "from_date": from_date.isoformat(),
        "event_count": len(events),
        "events": events,
    }

    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=json_default) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DynamoDB の稽古会イベントを取得して public/events.json に保存します。"
    )
    parser.add_argument(
        "--table-name",
        default="KendoKeikoEvents",
        help="DynamoDBテーブル名。default: KendoKeikoEvents",
    )
    parser.add_argument(
        "--region",
        default="ap-northeast-1",
        help="AWSリージョン。default: ap-northeast-1",
    )
    parser.add_argument(
        "--from-date",
        default=None,
        help="この日付以降のイベントを取得する。例: 2026-07-09。未指定なら今日 JST",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="最大取得件数。未指定なら全件",
    )
    parser.add_argument(
        "--output",
        default="public/events.json",
        help="出力JSONパス。default: public/events.json",
    )

    args = parser.parse_args()

    from_date = parse_from_date(args.from_date)

    events = query_events(
        table_name=args.table_name,
        region_name=args.region,
        from_date=from_date,
        limit=args.limit,
    )

    save_json(
        events=events,
        output_path=Path(args.output),
        table_name=args.table_name,
        region_name=args.region,
        from_date=from_date,
    )

    print(f"Saved {len(events)} events to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
