#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Lambda entrypoint for kendo-keiko-scraping.

Flow:
  1. Call export_events.py main() with --storage dynamodb
  2. Update DynamoDB KendoKeikoEvents
  3. Optionally query DynamoDB DateIndex
  4. Export public events.json to S3
  5. Pre-render event cards into index.html and refresh sitemap.xml

Environment variables:
  TABLE_NAME=KendoKeikoEvents
  AWS_REGION=ap-northeast-1
  GROUP=all
  DEBUG=false

  PUBLISH_TO_S3=false
  EVENTS_BUCKET=<your-s3-bucket>
  EVENTS_KEY=events.json

  PUBLISH_INDEX_HTML=true
  INDEX_KEY=index.html
  SITEMAP_KEY=sitemap.xml
  SITE_URL=https://kendo-keiko.com/
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal
from io import StringIO
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import boto3
from boto3.dynamodb.conditions import Key

import export_events
from kendo_keiko.static_site import build_sitemap_xml, render_static_index


JST = ZoneInfo("Asia/Tokyo")


def str_to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)

    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def today_jst() -> dt.date:
    return dt.datetime.now(JST).date()


def query_events_from_dynamodb(
    *,
    table_name: str,
    region_name: str,
    from_date: str,
) -> list[dict[str, Any]]:
    dynamodb = boto3.resource("dynamodb", region_name=region_name)
    table = dynamodb.Table(table_name)

    events: list[dict[str, Any]] = []
    last_evaluated_key = None

    while True:
        kwargs: dict[str, Any] = {
            "IndexName": "DateIndex",
            "KeyConditionExpression": Key("gsi1_pk").eq("EVENT")
            & Key("gsi1_sk").gte(from_date),
        }

        if last_evaluated_key:
            kwargs["ExclusiveStartKey"] = last_evaluated_key

        response = table.query(**kwargs)
        events.extend(response.get("Items", []))

        last_evaluated_key = response.get("LastEvaluatedKey")
        if not last_evaluated_key:
            break

    return sorted(
        events,
        key=lambda e: (
            e.get("event_date", ""),
            e.get("start_time", ""),
            e.get("organization_id", ""),
            e.get("event_id", ""),
        ),
    )


def build_public_events_payload(
    *,
    events: list[dict[str, Any]],
    table_name: str,
    region_name: str,
    from_date: str,
) -> dict[str, Any]:
    return {
        "schema_version": "public-events-0.1",
        "generated_at": dt.datetime.now(JST).isoformat(timespec="seconds"),
        "timezone": "Asia/Tokyo",
        "source": "dynamodb",
        "table_name": table_name,
        "region": region_name,
        "from_date": from_date,
        "event_count": len(events),
        "events": events,
    }


def upload_text_to_s3(
    *,
    bucket: str,
    key: str,
    body: str,
    content_type: str,
    region_name: str,
    cache_control: str = "max-age=300",
) -> None:
    s3 = boto3.client("s3", region_name=region_name)
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body.encode("utf-8"),
        ContentType=content_type,
        CacheControl=cache_control,
    )


def upload_events_json_to_s3(
    *,
    bucket: str,
    key: str,
    payload: dict[str, Any],
    region_name: str,
) -> None:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        default=json_default,
    )
    upload_text_to_s3(
        bucket=bucket,
        key=key,
        body=body,
        content_type="application/json; charset=utf-8",
        region_name=region_name,
    )


def build_public_index_html(payload: dict[str, Any]) -> str:
    template_path = Path(__file__).resolve().parent / "public" / "index.html"
    template_html = template_path.read_text(encoding="utf-8")
    return render_static_index(template_html, payload)


def run_export_events_main(
    *,
    table_name: str,
    region_name: str,
    group: str,
    debug: bool,
) -> dict[str, Any]:
    """
    Reuse existing export_events.py CLI implementation.
    """
    argv = [
        "export_events.py",
        "--storage",
        "dynamodb",
        "--table-name",
        table_name,
        "--region",
        region_name,
        "--group",
        group,
        "--no-stdout",
    ]

    if debug:
        argv.append("--debug")

    old_argv = sys.argv[:]
    stdout = StringIO()
    stderr = StringIO()

    try:
        sys.argv = argv
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = export_events.main()
    finally:
        sys.argv = old_argv

    return {
        "exit_code": exit_code,
        "stdout": stdout.getvalue(),
        "stderr": stderr.getvalue(),
    }


def lambda_handler(event: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    event = event or {}

    table_name = event.get("table_name") or os.environ.get("TABLE_NAME", "KendoKeikoEvents")
    region_name = event.get("region") or os.environ.get("AWS_REGION", "ap-northeast-1")
    group = event.get("group") or os.environ.get("GROUP", "all")
    debug = str_to_bool(event.get("debug"), str_to_bool(os.environ.get("DEBUG"), False))

    publish_to_s3 = str_to_bool(
        event.get("publish_to_s3"),
        str_to_bool(os.environ.get("PUBLISH_TO_S3"), False),
    )
    events_bucket = event.get("events_bucket") or os.environ.get("EVENTS_BUCKET")
    events_key = event.get("events_key") or os.environ.get("EVENTS_KEY", "events.json")
    publish_index_html = str_to_bool(
        event.get("publish_index_html"),
        str_to_bool(os.environ.get("PUBLISH_INDEX_HTML"), publish_to_s3),
    )
    index_key = event.get("index_key") or os.environ.get("INDEX_KEY", "index.html")
    sitemap_key = event.get("sitemap_key") or os.environ.get("SITEMAP_KEY", "sitemap.xml")
    site_url = event.get("site_url") or os.environ.get("SITE_URL", "https://kendo-keiko.com/")
    from_date = event.get("from_date") or today_jst().isoformat()

    print(
        json.dumps(
            {
                "message": "kendo scraper started",
                "table_name": table_name,
                "region": region_name,
                "group": group,
                "publish_to_s3": publish_to_s3,
                "events_bucket": events_bucket,
                "events_key": events_key,
                "publish_index_html": publish_index_html,
                "index_key": index_key,
                "sitemap_key": sitemap_key,
                "site_url": site_url,
                "from_date": from_date,
            },
            ensure_ascii=False,
        )
    )

    export_result = run_export_events_main(
        table_name=table_name,
        region_name=region_name,
        group=group,
        debug=debug,
    )

    if export_result["stdout"]:
        print(export_result["stdout"])

    if export_result["stderr"]:
        print(export_result["stderr"], file=sys.stderr)

    if export_result["exit_code"] != 0:
        raise RuntimeError(f"export_events.py failed: exit_code={export_result['exit_code']}")

    response: dict[str, Any] = {
        "statusCode": 200,
        "table_name": table_name,
        "region": region_name,
        "group": group,
        "dynamodb_updated": True,
        "s3_published": False,
    }

    if publish_to_s3:
        if not events_bucket:
            raise ValueError("PUBLISH_TO_S3 is true, but EVENTS_BUCKET is not set.")

        events = query_events_from_dynamodb(
            table_name=table_name,
            region_name=region_name,
            from_date=from_date,
        )
        payload = build_public_events_payload(
            events=events,
            table_name=table_name,
            region_name=region_name,
            from_date=from_date,
        )
        upload_events_json_to_s3(
            bucket=events_bucket,
            key=events_key,
            payload=payload,
            region_name=region_name,
        )

        print(
            json.dumps(
                {
                    "message": "events.json uploaded to S3",
                    "bucket": events_bucket,
                    "key": events_key,
                    "event_count": len(events),
                },
                ensure_ascii=False,
            )
        )

        response.update(
            {
                "s3_published": True,
                "events_bucket": events_bucket,
                "events_key": events_key,
                "event_count": len(events),
                "index_published": False,
                "sitemap_published": False,
            }
        )

        if publish_index_html:
            index_html = build_public_index_html(payload)
            upload_text_to_s3(
                bucket=events_bucket,
                key=index_key,
                body=index_html,
                content_type="text/html; charset=utf-8",
                region_name=region_name,
            )

            sitemap_xml = build_sitemap_xml(
                site_url=site_url,
                lastmod=today_jst(),
            )
            upload_text_to_s3(
                bucket=events_bucket,
                key=sitemap_key,
                body=sitemap_xml,
                content_type="application/xml; charset=utf-8",
                region_name=region_name,
                cache_control="max-age=3600",
            )

            print(
                json.dumps(
                    {
                        "message": "index.html and sitemap.xml uploaded to S3",
                        "bucket": events_bucket,
                        "index_key": index_key,
                        "sitemap_key": sitemap_key,
                        "event_count": len(events),
                    },
                    ensure_ascii=False,
                )
            )

            response.update(
                {
                    "index_published": True,
                    "index_key": index_key,
                    "sitemap_published": True,
                    "sitemap_key": sitemap_key,
                }
            )

    return response
