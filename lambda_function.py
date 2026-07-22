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
from io import StringIO
from typing import Any
from zoneinfo import ZoneInfo

import export_events
from kendo_keiko.publication import publish_public_site


JST = ZoneInfo("Asia/Tokyo")


def today_jst() -> dt.date:
    return dt.datetime.now(JST).date()


def str_to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


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

        publish_result = publish_public_site(
            table_name=table_name,
            region_name=region_name,
            from_date=from_date,
            events_bucket=events_bucket,
            events_key=events_key,
            publish_index_html=publish_index_html,
            index_key=index_key,
            sitemap_key=sitemap_key,
            site_url=site_url,
        )
        response.update(publish_result)
        print(
            json.dumps(
                {
                    "message": "public site files uploaded to S3",
                    **publish_result,
                },
                ensure_ascii=False,
            )
        )

    return response
