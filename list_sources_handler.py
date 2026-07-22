from __future__ import annotations

import datetime as dt
import os
import uuid
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from kendo_keiko.repository import (
    DEFAULT_ORGANIZATIONS_PATH,
    load_organizations,
)


JST = ZoneInfo("Asia/Tokyo")


def str_to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def lambda_handler(event: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    event = event or {}
    organizations_path = Path(
        event.get("organizations_path")
        or os.environ.get(
            "ORGANIZATIONS_PATH",
            str(DEFAULT_ORGANIZATIONS_PATH),
        )
    )
    organizations = load_organizations(organizations_path)
    sources = [
        {"organization_id": organization.organization_id}
        for organization in organizations
        if organization.scraper_enabled
    ]
    if not sources:
        raise ValueError("No enabled scraper sources were found.")

    request_id = getattr(context, "aws_request_id", None)
    run_id = event.get("run_id") or request_id or str(uuid.uuid4())
    from_date = event.get("from_date") or dt.datetime.now(JST).date().isoformat()

    return {
        "run_id": run_id,
        "table_name": event.get("table_name")
        or os.environ.get("TABLE_NAME", "KendoKeikoEvents"),
        "region": event.get("region")
        or os.environ.get("AWS_REGION", "ap-northeast-1"),
        "from_date": from_date,
        "debug": str_to_bool(
            event.get("debug"),
            str_to_bool(os.environ.get("DEBUG"), False),
        ),
        "publish_to_s3": str_to_bool(
            event.get("publish_to_s3"),
            str_to_bool(os.environ.get("PUBLISH_TO_S3"), True),
        ),
        "publish_index_html": str_to_bool(
            event.get("publish_index_html"),
            str_to_bool(os.environ.get("PUBLISH_INDEX_HTML"), True),
        ),
        "events_bucket": event.get("events_bucket")
        or os.environ.get("EVENTS_BUCKET"),
        "events_key": event.get("events_key")
        or os.environ.get("EVENTS_KEY", "events.json"),
        "index_key": event.get("index_key")
        or os.environ.get("INDEX_KEY", "index.html"),
        "sitemap_key": event.get("sitemap_key")
        or os.environ.get("SITEMAP_KEY", "sitemap.xml"),
        "site_url": event.get("site_url")
        or os.environ.get("SITE_URL", "https://kendo-keiko.com/"),
        "sources": sources,
    }
