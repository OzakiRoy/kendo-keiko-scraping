from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

from kendo_keiko.models import Organization, normalize_event_metadata
from kendo_keiko.pipeline import make_event_id, make_gsi1_keys
from kendo_keiko.scrapers.common import JST


MANUAL_EVENTS_SCHEMA_VERSION = "manual-events-0.1"
DEFAULT_MANUAL_EVENTS_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "manual_events.json"
)
VALID_MANUAL_STATUSES = frozenset({"active", "cancelled", "archived"})
WEEKDAYS_JA = ("月", "火", "水", "木", "金", "土", "日")


def now_jst() -> str:
    return dt.datetime.now(JST).isoformat(timespec="seconds")


def parse_iso_date(value: Any, *, field_name: str) -> dt.date:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be YYYY-MM-DD") from exc


def parse_optional_time(value: Any, *, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be HH:MM or null")
    try:
        parsed = dt.time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be HH:MM") from exc
    if parsed.second or parsed.microsecond:
        raise ValueError(f"{field_name} must be HH:MM")
    return parsed.strftime("%H:%M")


def validate_official_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("source_url is required")
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("source_url must be an official http(s) URL")
    return url


def manual_event_key(event: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(event.get("organization_id") or ""),
        str(event.get("event_type") or ""),
        str(event.get("event_date") or ""),
        str(event.get("start_time") or ""),
        str(event.get("end_time") or ""),
    )


def validate_manual_event(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ValueError("manual event must be a JSON object")

    normalized = normalize_event_metadata(event)

    required_text_fields = (
        "event_id",
        "organization_id",
        "organization_name",
        "event_type",
        "source_type",
        "last_scraped_at",
        "gsi1_pk",
        "gsi1_sk",
    )
    for field_name in required_text_fields:
        value = normalized.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} is required")

    if normalized["update_mode"] != "manual":
        raise ValueError("manual event update_mode must be manual")

    status = normalized.get("status")
    if status not in VALID_MANUAL_STATUSES:
        raise ValueError(f"invalid manual event status: {status}")

    event_date = parse_iso_date(
        normalized.get("event_date"),
        field_name="event_date",
    )
    normalized["event_date"] = event_date.isoformat()
    normalized["weekday"] = WEEKDAYS_JA[event_date.weekday()]
    normalized["start_time"] = parse_optional_time(
        normalized.get("start_time"),
        field_name="start_time",
    )
    normalized["end_time"] = parse_optional_time(
        normalized.get("end_time"),
        field_name="end_time",
    )
    if (
        normalized["start_time"]
        and normalized["end_time"]
        and normalized["end_time"] <= normalized["start_time"]
    ):
        raise ValueError("end_time must be later than start_time")

    normalized["source_url"] = validate_official_url(
        normalized.get("source_url")
    )

    verified_at = normalized.get("verified_at")
    if verified_at is None:
        raise ValueError("verified_at is required for manual events")
    verified_datetime = dt.datetime.fromisoformat(verified_at)

    review_due_at = parse_iso_date(
        normalized.get("review_due_at"),
        field_name="review_due_at",
    )
    if review_due_at < verified_datetime.date():
        raise ValueError("review_due_at must not be before verified_at")
    normalized["review_due_at"] = review_due_at.isoformat()

    expected_gsi1_pk, expected_gsi1_sk = make_gsi1_keys(
        event_date=normalized["event_date"],
        start_time=normalized["start_time"],
        organization_id=normalized["organization_id"],
        event_id=normalized["event_id"],
    )
    if normalized["gsi1_pk"] != expected_gsi1_pk:
        raise ValueError("gsi1_pk does not match event data")
    if normalized["gsi1_sk"] != expected_gsi1_sk:
        raise ValueError("gsi1_sk does not match event data")

    return normalized


def build_manual_event(
    *,
    organization: Organization,
    event_date: str,
    source_url: str,
    verified_at: str,
    review_due_at: str,
    title: Optional[str] = None,
    event_type: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    venue: Optional[str] = None,
    area: Optional[str] = None,
    address: Optional[str] = None,
    access: Optional[str] = None,
    fee: Optional[str] = None,
    application_required: Optional[bool] = None,
    participation_type: str = "unknown",
    raw_note: Optional[str] = None,
) -> dict[str, Any]:
    parsed_date = parse_iso_date(event_date, field_name="event_date")
    normalized_start = parse_optional_time(
        start_time,
        field_name="start_time",
    )
    normalized_end = parse_optional_time(end_time, field_name="end_time")
    official_url = validate_official_url(source_url)
    actual_event_type = event_type or organization.event_type

    event_id = make_event_id(
        org_id=organization.organization_id,
        event_date=parsed_date.isoformat(),
        start_time=normalized_start,
        end_time=normalized_end,
        venue=venue,
        title=title,
        source_url=official_url,
    )
    gsi1_pk, gsi1_sk = make_gsi1_keys(
        event_date=parsed_date.isoformat(),
        start_time=normalized_start,
        organization_id=organization.organization_id,
        event_id=event_id,
    )

    event = {
        "event_id": event_id,
        "organization_id": organization.organization_id,
        "organization_name": organization.name,
        "event_type": actual_event_type,
        "title": title,
        "event_date": parsed_date.isoformat(),
        "weekday": WEEKDAYS_JA[parsed_date.weekday()],
        "start_time": normalized_start,
        "end_time": normalized_end,
        "venue": venue,
        "area": area or organization.area,
        "address": address,
        "access": access,
        "fee": fee,
        "application_required": application_required,
        "source_url": official_url,
        "source_type": organization.source_type,
        "last_scraped_at": verified_at,
        "status": "active",
        "raw_note": raw_note,
        "update_mode": "manual",
        "participation_type": participation_type,
        "verified_at": verified_at,
        "review_due_at": review_due_at,
        "gsi1_pk": gsi1_pk,
        "gsi1_sk": gsi1_sk,
    }
    return validate_manual_event(event)



def validate_manual_events(
    events: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    validated = [validate_manual_event(event) for event in events]
    event_ids: set[str] = set()
    event_keys: set[tuple[str, str, str, str, str]] = set()
    for event in validated:
        if event["event_id"] in event_ids:
            raise ValueError(f"duplicate manual event_id: {event['event_id']}")
        key = manual_event_key(event)
        if key in event_keys:
            raise ValueError(
                "duplicate manual event schedule: "
                f"{event['organization_id']} {event['event_date']} "
                f"{event.get('start_time') or '-'}"
            )
        event_ids.add(event["event_id"])
        event_keys.add(key)
    return sort_manual_events(validated)

def load_manual_events(
    path: Path = DEFAULT_MANUAL_EVENTS_PATH,
    *,
    allow_missing: bool = False,
) -> list[dict[str, Any]]:
    if not path.exists():
        if allow_missing:
            return []
        raise FileNotFoundError(f"manual events file not found: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("manual_events.json must contain a JSON object")
    if raw.get("schema_version") != MANUAL_EVENTS_SCHEMA_VERSION:
        raise ValueError(
            "unsupported manual_events.json schema_version: "
            f"{raw.get('schema_version')}"
        )
    raw_events = raw.get("events")
    if not isinstance(raw_events, list):
        raise ValueError("manual_events.json events must be a JSON array")

    return validate_manual_events(raw_events)


def sort_manual_events(
    events: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        (dict(event) for event in events),
        key=lambda event: (
            str(event.get("event_date") or ""),
            str(event.get("start_time") or ""),
            str(event.get("organization_id") or ""),
            str(event.get("event_id") or ""),
        ),
    )


def save_manual_events(
    *,
    path: Path,
    events: Iterable[dict[str, Any]],
) -> None:
    validated = validate_manual_events(events)
    payload = {
        "schema_version": MANUAL_EVENTS_SCHEMA_VERSION,
        "events": validated,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def find_manual_event(
    events: Iterable[dict[str, Any]],
    event_id: str,
) -> dict[str, Any]:
    for event in events:
        if event.get("event_id") == event_id:
            return dict(event)
    raise ValueError(f"manual event_id not found: {event_id}")


def replace_manual_event(
    events: Iterable[dict[str, Any]],
    updated_event: dict[str, Any],
) -> list[dict[str, Any]]:
    validated = validate_manual_event(updated_event)
    result: list[dict[str, Any]] = []
    replaced = False
    for event in events:
        if event.get("event_id") == validated["event_id"]:
            result.append(validated)
            replaced = True
        else:
            result.append(dict(event))
    if not replaced:
        raise ValueError(
            f"manual event_id not found: {validated['event_id']}"
        )
    return sort_manual_events(result)


def refresh_manual_event_keys(event: dict[str, Any]) -> dict[str, Any]:
    refreshed = dict(event)
    event_date = parse_iso_date(
        refreshed.get("event_date"),
        field_name="event_date",
    )
    refreshed["event_date"] = event_date.isoformat()
    refreshed["weekday"] = WEEKDAYS_JA[event_date.weekday()]
    refreshed["start_time"] = parse_optional_time(
        refreshed.get("start_time"),
        field_name="start_time",
    )
    refreshed["end_time"] = parse_optional_time(
        refreshed.get("end_time"),
        field_name="end_time",
    )
    refreshed["gsi1_pk"], refreshed["gsi1_sk"] = make_gsi1_keys(
        event_date=refreshed["event_date"],
        start_time=refreshed["start_time"],
        organization_id=refreshed["organization_id"],
        event_id=refreshed["event_id"],
    )
    return validate_manual_event(refreshed)


def list_review_due_events(
    events: Iterable[dict[str, Any]],
    *,
    as_of: dt.date,
) -> list[dict[str, Any]]:
    due: list[dict[str, Any]] = []
    for raw_event in events:
        event = validate_manual_event(raw_event)
        if event["status"] != "active":
            continue
        event_date = dt.date.fromisoformat(event["event_date"])
        review_due_at = dt.date.fromisoformat(event["review_due_at"])
        if event_date >= as_of and review_due_at <= as_of:
            due.append(event)
    return sort_manual_events(due)


def merge_public_events(
    *,
    automatic_events: Iterable[dict[str, Any]],
    manual_events: Iterable[dict[str, Any]],
    from_date: str,
) -> list[dict[str, Any]]:
    minimum_date = parse_iso_date(from_date, field_name="from_date")
    merged: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}

    for raw_event in automatic_events:
        event = normalize_event_metadata(raw_event)
        event_date = parse_iso_date(
            event.get("event_date"),
            field_name="event_date",
        )
        if event.get("status", "active") != "active":
            continue
        if event_date < minimum_date:
            continue
        merged[manual_event_key(event)] = event

    # Manual data is authoritative. Active manual events replace automatic
    # duplicates, while cancelled/archived records suppress matching automatic
    # events without deleting the source record.
    for raw_event in manual_events:
        event = validate_manual_event(raw_event)
        key = manual_event_key(event)
        event_date = dt.date.fromisoformat(event["event_date"])
        if event["status"] != "active" or event_date < minimum_date:
            merged.pop(key, None)
            continue
        merged[key] = event

    return sorted(
        merged.values(),
        key=lambda event: (
            str(event.get("event_date") or ""),
            str(event.get("start_time") or ""),
            str(event.get("organization_id") or ""),
            str(event.get("event_id") or ""),
        ),
    )
