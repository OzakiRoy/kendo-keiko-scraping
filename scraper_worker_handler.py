from __future__ import annotations

import os
from typing import Any

from kendo_keiko.worker import run_scraper_worker


def str_to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def lambda_handler(event: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    event = event or {}
    organization_id = event.get("organization_id")
    if not organization_id:
        raise ValueError("organization_id is required")

    run_id = event.get("run_id") or getattr(context, "aws_request_id", "unknown")
    return run_scraper_worker(
        organization_id=organization_id,
        table_name=event.get("table_name")
        or os.environ.get("TABLE_NAME", "KendoKeikoEvents"),
        region_name=event.get("region")
        or os.environ.get("AWS_REGION", "ap-northeast-1"),
        from_date=event.get("from_date"),
        run_id=run_id,
        debug=str_to_bool(
            event.get("debug"),
            str_to_bool(os.environ.get("DEBUG"), False),
        ),
    )
