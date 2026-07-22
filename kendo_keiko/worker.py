from __future__ import annotations

import datetime as dt
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import requests
from zoneinfo import ZoneInfo

from kendo_keiko.models import ScrapeResult
from kendo_keiko.pipeline import parse_from_date, run_pipeline
from kendo_keiko.repository import (
    DEFAULT_ORGANIZATIONS_PATH,
    find_organization,
    load_organizations,
    save_dynamodb,
)


JST = ZoneInfo("Asia/Tokyo")


class ScraperWorkerError(RuntimeError):
    """Base error raised by the scraper worker."""


class ScraperDisabledError(ScraperWorkerError):
    """Raised when Step Functions requests a disabled scraper."""


class ScraperTransientError(ScraperWorkerError):
    """Raised for retryable network failures."""


def run_scraper_worker(
    *,
    organization_id: str,
    table_name: str,
    region_name: str,
    from_date: str | None,
    run_id: str,
    debug: bool = False,
    organizations_path: Path = DEFAULT_ORGANIZATIONS_PATH,
) -> dict[str, Any]:
    started = time.perf_counter()
    checked_at = dt.datetime.now(JST).isoformat(timespec="seconds")

    try:
        organizations = load_organizations(organizations_path)
        organization = find_organization(organizations, organization_id)
        if not organization.scraper_enabled:
            raise ScraperDisabledError(
                f"scraper is disabled: {organization_id}"
            )

        filter_from_date = parse_from_date(from_date)
        events = run_pipeline(
            organizations=[organization],
            scraped_at=checked_at,
            from_date=filter_from_date,
            debug=debug,
        )
        save_dynamodb(
            events=events,
            table_name=table_name,
            region=region_name,
        )
    except Exception as exc:
        duration_ms = max(0, round((time.perf_counter() - started) * 1000))
        error = (
            ScraperTransientError(str(exc))
            if isinstance(exc, requests.RequestException)
            else exc
        )
        print(
            json.dumps(
                {
                    "message": "scraper worker failed",
                    "run_id": run_id,
                    "organization_id": organization_id,
                    "status": "failure",
                    "event_count": 0,
                    "duration_ms": duration_ms,
                    "checked_at": dt.datetime.now(JST).isoformat(
                        timespec="seconds"
                    ),
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                },
                ensure_ascii=False,
            )
        )
        if error is not exc:
            raise error from exc
        raise

    duration_ms = max(0, round((time.perf_counter() - started) * 1000))
    status = "success" if events else "warning"
    result = ScrapeResult(
        run_id=run_id,
        organization_id=organization.organization_id,
        scraper_type=organization.scraper_type,
        status=status,
        event_count=len(events),
        duration_ms=duration_ms,
        checked_at=dt.datetime.now(JST).isoformat(timespec="seconds"),
        from_date=filter_from_date.isoformat(),
        error_type="empty_result" if not events else None,
        error_message=(
            "No future events were returned by the scraper."
            if not events
            else None
        ),
    )
    payload = asdict(result)
    print(
        json.dumps(
            {"message": "scraper worker completed", **payload},
            ensure_ascii=False,
        )
    )
    return payload
