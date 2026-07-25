from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import boto3
from boto3.dynamodb.conditions import Key

from kendo_keiko.manual_events import (
    DEFAULT_MANUAL_EVENTS_PATH,
    load_manual_events,
    merge_public_events,
)
from kendo_keiko.models import normalize_event_metadata
from kendo_keiko.static_site import build_sitemap_xml, render_static_index


JST = ZoneInfo("Asia/Tokyo")

PUBLIC_ASSETS: tuple[tuple[str, str], ...] = (
    ("favicon.svg", "image/svg+xml"),
    ("favicon.ico", "image/x-icon"),
    ("favicon-32x32.png", "image/png"),
    ("apple-touch-icon.png", "image/png"),
    ("icon-192.png", "image/png"),
    ("icon-512.png", "image/png"),
    ("ogp.png", "image/png"),
    ("site.webmanifest", "application/manifest+json; charset=utf-8"),
)


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    raise TypeError(
        f"Object of type {type(value).__name__} is not JSON serializable"
    )


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
        events.extend(
            normalize_event_metadata(item)
            for item in response.get("Items", [])
        )
        last_evaluated_key = response.get("LastEvaluatedKey")
        if not last_evaluated_key:
            break

    return sorted(
        events,
        key=lambda event: (
            event.get("event_date", ""),
            event.get("start_time", ""),
            event.get("organization_id", ""),
            event.get("event_id", ""),
        ),
    )


def build_public_events_payload(
    *,
    events: list[dict[str, Any]],
    table_name: str,
    region_name: str,
    from_date: str,
) -> dict[str, Any]:
    normalized_events = [normalize_event_metadata(event) for event in events]
    return {
        "schema_version": "public-events-0.3",
        "generated_at": dt.datetime.now(JST).isoformat(timespec="seconds"),
        "timezone": "Asia/Tokyo",
        "source": "dynamodb+manual_json",
        "table_name": table_name,
        "region": region_name,
        "from_date": from_date,
        "event_count": len(normalized_events),
        "events": normalized_events,
    }


def upload_bytes_to_s3(
    *,
    bucket: str,
    key: str,
    body: bytes,
    content_type: str,
    region_name: str,
    cache_control: str = "max-age=300",
) -> None:
    s3 = boto3.client("s3", region_name=region_name)
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType=content_type,
        CacheControl=cache_control,
    )


def upload_text_to_s3(
    *,
    bucket: str,
    key: str,
    body: str,
    content_type: str,
    region_name: str,
    cache_control: str = "max-age=300",
) -> None:
    upload_bytes_to_s3(
        bucket=bucket,
        key=key,
        body=body.encode("utf-8"),
        content_type=content_type,
        region_name=region_name,
        cache_control=cache_control,
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
    template_path = (
        Path(__file__).resolve().parent.parent / "public" / "index.html"
    )
    template_html = template_path.read_text(encoding="utf-8")
    return render_static_index(template_html, payload)


def publish_public_assets(
    *,
    bucket: str,
    region_name: str,
) -> list[str]:
    public_dir = Path(__file__).resolve().parent.parent / "public"
    published_keys: list[str] = []
    s3 = boto3.client("s3", region_name=region_name)

    for key, content_type in PUBLIC_ASSETS:
        asset_path = public_dir / key
        if not asset_path.is_file():
            raise FileNotFoundError(f"public asset not found: {asset_path}")
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=asset_path.read_bytes(),
            ContentType=content_type,
            CacheControl="max-age=86400",
        )
        published_keys.append(key)

    return published_keys


def publish_public_site(
    *,
    table_name: str,
    region_name: str,
    from_date: str,
    events_bucket: str,
    events_key: str = "events.json",
    publish_index_html: bool = True,
    index_key: str = "index.html",
    sitemap_key: str = "sitemap.xml",
    site_url: str = "https://kendo-keiko.com/",
    manual_events_path: Path = DEFAULT_MANUAL_EVENTS_PATH,
) -> dict[str, Any]:
    automatic_events = query_events_from_dynamodb(
        table_name=table_name,
        region_name=region_name,
        from_date=from_date,
    )
    manual_events = load_manual_events(manual_events_path)
    events = merge_public_events(
        automatic_events=automatic_events,
        manual_events=manual_events,
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

    result: dict[str, Any] = {
        "s3_published": True,
        "events_bucket": events_bucket,
        "events_key": events_key,
        "event_count": len(events),
        "index_published": False,
        "sitemap_published": False,
        "assets_published": False,
        "asset_keys": [],
    }

    if publish_index_html:
        upload_text_to_s3(
            bucket=events_bucket,
            key=index_key,
            body=build_public_index_html(payload),
            content_type="text/html; charset=utf-8",
            region_name=region_name,
        )
        upload_text_to_s3(
            bucket=events_bucket,
            key=sitemap_key,
            body=build_sitemap_xml(
                site_url=site_url,
                lastmod=dt.datetime.now(JST).date(),
            ),
            content_type="application/xml; charset=utf-8",
            region_name=region_name,
            cache_control="max-age=3600",
        )
        asset_keys = publish_public_assets(
            bucket=events_bucket,
            region_name=region_name,
        )
        result.update(
            {
                "index_published": True,
                "index_key": index_key,
                "sitemap_published": True,
                "sitemap_key": sitemap_key,
                "assets_published": True,
                "asset_keys": asset_keys,
            }
        )

    return result
