from __future__ import annotations

import json
import os
from collections import Counter
from typing import Any

from kendo_keiko.publication import publish_public_site


class AllSourcesFailedError(RuntimeError):
    """Raised when no scraper source completed successfully or with warning."""


def str_to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def validate_scrape_results(results: Any) -> Counter[str]:
    if not isinstance(results, list) or not results:
        raise ValueError("scrape_results must be a non-empty array")

    statuses = [str(result.get("status")) for result in results]
    invalid_statuses = sorted(set(statuses) - {"success", "warning", "failure"})
    if invalid_statuses:
        raise ValueError(
            f"Unknown scrape result status: {', '.join(invalid_statuses)}"
        )

    counts = Counter(statuses)
    if counts["failure"] == len(results):
        raise AllSourcesFailedError("All scraper sources failed; publishing skipped.")
    return counts


def lambda_handler(event: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    event = event or {}
    publish_only = str_to_bool(event.get("publish_only"), False)

    if publish_only:
        response: dict[str, Any] = {
            "mode": "publish_only",
            "s3_published": False,
        }
    else:
        results = event.get("scrape_results")
        counts = validate_scrape_results(results)
        response = {
            "run_id": event.get("run_id"),
            "source_count": len(results),
            "success_count": counts["success"],
            "warning_count": counts["warning"],
            "failure_count": counts["failure"],
            "s3_published": False,
        }

    publish_to_s3 = str_to_bool(
        event.get("publish_to_s3"),
        str_to_bool(os.environ.get("PUBLISH_TO_S3"), True),
    )
    if publish_to_s3:
        events_bucket = event.get("events_bucket") or os.environ.get(
            "EVENTS_BUCKET"
        )
        if not events_bucket:
            raise ValueError("EVENTS_BUCKET is required when publishing is enabled")

        response.update(
            publish_public_site(
                table_name=event.get("table_name")
                or os.environ.get("TABLE_NAME", "KendoKeikoEvents"),
                region_name=event.get("region")
                or os.environ.get("AWS_REGION", "ap-northeast-1"),
                from_date=event.get("from_date"),
                events_bucket=events_bucket,
                events_key=event.get("events_key")
                or os.environ.get("EVENTS_KEY", "events.json"),
                publish_index_html=str_to_bool(
                    event.get("publish_index_html"),
                    str_to_bool(os.environ.get("PUBLISH_INDEX_HTML"), True),
                ),
                index_key=event.get("index_key")
                or os.environ.get("INDEX_KEY", "index.html"),
                sitemap_key=event.get("sitemap_key")
                or os.environ.get("SITEMAP_KEY", "sitemap.xml"),
                site_url=event.get("site_url")
                or os.environ.get("SITE_URL", "https://kendo-keiko.com/"),
            )
        )

    message = (
        "manual event publishing completed"
        if publish_only
        else "scraper workflow completed"
    )
    print(json.dumps({"message": message, **response}, ensure_ascii=False))
    return response
