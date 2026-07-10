#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AWS Lambda entry point for kendo-keiko-scraping.

This wrapper intentionally reuses export_events.py's CLI-oriented main().
For the MVP, this keeps the Lambda adaptation small and avoids rewriting
scraping / normalization / DynamoDB storage logic.

Required environment variables:
  TABLE_NAME=KendoKeikoEvents

Optional environment variables:
  GROUP=all
  FROM_DATE=YYYY-MM-DD
  INCLUDE_PAST=false
  DEBUG=false

AWS_REGION is provided by Lambda runtime. You can override it if needed.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import export_events


DEFAULT_TABLE_NAME = "KendoKeikoEvents"
DEFAULT_REGION = "ap-northeast-1"


def str_to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def read_setting(event: dict[str, Any], key: str, env_key: str, default: Any = None) -> Any:
    """
    Manual Lambda invoke event can override environment variables.

    Example invoke payload:
      {"group":"kenbokukai","debug":true}
    """
    if key in event and event[key] is not None:
        return event[key]

    return os.environ.get(env_key, default)


def build_export_argv(event: dict[str, Any]) -> list[str]:
    table_name = read_setting(event, "table_name", "TABLE_NAME", DEFAULT_TABLE_NAME)
    region = read_setting(event, "region", "AWS_REGION", DEFAULT_REGION)
    group = read_setting(event, "group", "GROUP", "all")
    from_date = read_setting(event, "from_date", "FROM_DATE", None)
    include_past = str_to_bool(read_setting(event, "include_past", "INCLUDE_PAST", False))
    debug = str_to_bool(read_setting(event, "debug", "DEBUG", False))

    argv = [
        "export_events.py",
        "--storage",
        "dynamodb",
        "--table-name",
        str(table_name),
        "--region",
        str(region),
        "--group",
        str(group),
        "--no-stdout",
    ]

    if from_date:
        argv.extend(["--from-date", str(from_date)])

    if include_past:
        argv.append("--include-past")

    if debug:
        argv.append("--debug")

    return argv


def lambda_handler(event: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    event = event or {}
    argv = build_export_argv(event)

    print("[INFO] start kendo keiko scrape job")
    print("[INFO] argv:", " ".join(argv))

    old_argv = sys.argv[:]
    try:
        sys.argv = argv
        exit_code = export_events.main()
    finally:
        sys.argv = old_argv

    if exit_code != 0:
        message = f"export_events.py failed with exit_code={exit_code}"
        print(f"[ERROR] {message}")
        raise RuntimeError(message)

    table_name = read_setting(event, "table_name", "TABLE_NAME", DEFAULT_TABLE_NAME)
    region = read_setting(event, "region", "AWS_REGION", DEFAULT_REGION)
    group = read_setting(event, "group", "GROUP", "all")

    body = {
        "message": "scrape job completed",
        "table_name": table_name,
        "region": region,
        "group": group,
    }

    print("[INFO] completed kendo keiko scrape job")
    return {
        "statusCode": 200,
        "body": json.dumps(body, ensure_ascii=False),
    }
