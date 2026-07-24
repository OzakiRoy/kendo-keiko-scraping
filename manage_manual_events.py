#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Optional

from kendo_keiko.manual_events import (
    DEFAULT_MANUAL_EVENTS_PATH,
    VALID_MANUAL_STATUSES,
    build_manual_event,
    find_manual_event,
    list_review_due_events,
    load_manual_events,
    now_jst,
    refresh_manual_event_keys,
    replace_manual_event,
    save_manual_events,
    validate_manual_events,
)
from kendo_keiko.models import VALID_PARTICIPATION_TYPES
from kendo_keiko.scrapers.common import JST
from kendo_keiko.repository import (
    DEFAULT_ORGANIZATIONS_PATH,
    find_organization,
    load_organizations,
)


CLEARABLE_FIELDS = frozenset(
    {
        "title",
        "start_time",
        "end_time",
        "venue",
        "area",
        "address",
        "access",
        "fee",
        "application_required",
        "raw_note",
    }
)


def parse_application_required(value: Optional[str]) -> Optional[bool]:
    if value is None or value == "unknown":
        return None
    return value == "yes"


def event_summary(event: dict[str, Any]) -> str:
    time_text = event.get("start_time") or "時間未定"
    return (
        f"{event['event_id']}\t{event['event_date']}\t{time_text}\t"
        f"{event['organization_name']}\t{event['status']}\t"
        f"review_due={event['review_due_at']}"
    )


def print_events(events: list[dict[str, Any]], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(events, ensure_ascii=False, indent=2))
        return
    if not events:
        print("該当する手動イベントはありません。")
        return
    for event in events:
        print(event_summary(event))


def print_dry_run(
    *,
    action: str,
    affected_events: list[dict[str, Any]],
    resulting_events: list[dict[str, Any]],
) -> None:
    print(
        json.dumps(
            {
                "dry_run": True,
                "action": action,
                "affected_count": len(affected_events),
                "total_count_after": len(resulting_events),
                "events": affected_events,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--organization-id", required=True)
    parser.add_argument("--title")
    parser.add_argument("--event-type")
    parser.add_argument("--start-time")
    parser.add_argument("--end-time")
    parser.add_argument("--venue")
    parser.add_argument("--area")
    parser.add_argument("--address")
    parser.add_argument("--access")
    parser.add_argument("--fee")
    parser.add_argument(
        "--application-required",
        choices=["yes", "no", "unknown"],
        default="unknown",
    )
    parser.add_argument("--source-url", required=True)
    parser.add_argument(
        "--participation-type",
        choices=sorted(VALID_PARTICIPATION_TYPES),
        default="unknown",
    )
    parser.add_argument("--verified-at", required=True)
    parser.add_argument("--review-due-at", required=True)
    parser.add_argument("--note", dest="raw_note")
    parser.add_argument("--dry-run", action="store_true")


def build_from_args(
    *,
    args: argparse.Namespace,
    event_date: str,
    organizations_path: Path,
) -> dict[str, Any]:
    organizations = load_organizations(organizations_path)
    organization = find_organization(organizations, args.organization_id)
    return build_manual_event(
        organization=organization,
        event_date=event_date,
        source_url=args.source_url,
        verified_at=args.verified_at,
        review_due_at=args.review_due_at,
        title=args.title,
        event_type=args.event_type,
        start_time=args.start_time,
        end_time=args.end_time,
        venue=args.venue,
        area=args.area,
        address=args.address,
        access=args.access,
        fee=args.fee,
        application_required=parse_application_required(
            args.application_required
        ),
        participation_type=args.participation_type,
        raw_note=args.raw_note,
    )


def handle_add(
    args: argparse.Namespace,
    *,
    manual_path: Path,
    organizations_path: Path,
) -> int:
    existing = load_manual_events(manual_path, allow_missing=True)
    new_event = build_from_args(
        args=args,
        event_date=args.date,
        organizations_path=organizations_path,
    )
    resulting = validate_manual_events([*existing, new_event])
    if args.dry_run:
        print_dry_run(
            action="add",
            affected_events=[new_event],
            resulting_events=resulting,
        )
        return 0
    save_manual_events(path=manual_path, events=resulting)
    print(event_summary(new_event))
    return 0


def handle_add_batch(
    args: argparse.Namespace,
    *,
    manual_path: Path,
    organizations_path: Path,
) -> int:
    dates = list(dict.fromkeys(args.date))
    if len(dates) < 2:
        raise ValueError("add-batch requires at least two --date values")
    existing = load_manual_events(manual_path, allow_missing=True)
    new_events = [
        build_from_args(
            args=args,
            event_date=event_date,
            organizations_path=organizations_path,
        )
        for event_date in dates
    ]
    resulting = validate_manual_events([*existing, *new_events])
    if args.dry_run:
        print_dry_run(
            action="add-batch",
            affected_events=new_events,
            resulting_events=resulting,
        )
        return 0
    save_manual_events(path=manual_path, events=resulting)
    print_events(new_events, "text")
    return 0


def handle_list(args: argparse.Namespace, *, manual_path: Path) -> int:
    events = load_manual_events(manual_path, allow_missing=True)
    if args.status:
        events = [event for event in events if event["status"] == args.status]
    if args.organization_id:
        events = [
            event
            for event in events
            if event["organization_id"] == args.organization_id
        ]
    print_events(events, args.format)
    return 0


def handle_show(args: argparse.Namespace, *, manual_path: Path) -> int:
    event = find_manual_event(load_manual_events(manual_path, allow_missing=True), args.event_id)
    print(json.dumps(event, ensure_ascii=False, indent=2))
    return 0


def apply_update_arguments(
    event: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    updated = dict(event)
    mapping = {
        "event_date": "date",
        "title": "title",
        "event_type": "event_type",
        "start_time": "start_time",
        "end_time": "end_time",
        "venue": "venue",
        "area": "area",
        "address": "address",
        "access": "access",
        "fee": "fee",
        "source_url": "source_url",
        "participation_type": "participation_type",
        "verified_at": "verified_at",
        "review_due_at": "review_due_at",
        "raw_note": "note",
    }
    for field_name, argument_name in mapping.items():
        value = getattr(args, argument_name)
        if value is not None:
            updated[field_name] = value

    if args.application_required is not None:
        updated["application_required"] = parse_application_required(
            args.application_required
        )

    for field_name in args.clear_field:
        updated[field_name] = None

    if args.verified_at is not None:
        updated["last_scraped_at"] = args.verified_at

    return refresh_manual_event_keys(updated)


def handle_update(args: argparse.Namespace, *, manual_path: Path) -> int:
    events = load_manual_events(manual_path, allow_missing=True)
    current = find_manual_event(events, args.event_id)
    updated = apply_update_arguments(current, args)
    resulting = replace_manual_event(events, updated)
    validate_manual_events(resulting)
    if args.dry_run:
        print_dry_run(
            action="update",
            affected_events=[updated],
            resulting_events=resulting,
        )
        return 0
    save_manual_events(path=manual_path, events=resulting)
    print(event_summary(updated))
    return 0


def handle_status_change(
    args: argparse.Namespace,
    *,
    manual_path: Path,
    status: str,
) -> int:
    events = load_manual_events(manual_path, allow_missing=True)
    updated = find_manual_event(events, args.event_id)
    updated["status"] = status
    updated = refresh_manual_event_keys(updated)
    resulting = replace_manual_event(events, updated)
    if args.dry_run:
        print_dry_run(
            action=status,
            affected_events=[updated],
            resulting_events=resulting,
        )
        return 0
    save_manual_events(path=manual_path, events=resulting)
    print(event_summary(updated))
    return 0


def handle_verify(args: argparse.Namespace, *, manual_path: Path) -> int:
    events = load_manual_events(manual_path, allow_missing=True)
    updated = find_manual_event(events, args.event_id)
    verified_at = args.verified_at or now_jst()
    updated["verified_at"] = verified_at
    updated["last_scraped_at"] = verified_at
    updated["review_due_at"] = args.review_due_at
    updated = refresh_manual_event_keys(updated)
    resulting = replace_manual_event(events, updated)
    if args.dry_run:
        print_dry_run(
            action="verify",
            affected_events=[updated],
            resulting_events=resulting,
        )
        return 0
    save_manual_events(path=manual_path, events=resulting)
    print(event_summary(updated))
    return 0


def handle_list_review_due(
    args: argparse.Namespace,
    *,
    manual_path: Path,
) -> int:
    as_of = (
        dt.date.fromisoformat(args.as_of)
        if args.as_of
        else dt.datetime.now(JST).date()
    )
    events = list_review_due_events(
        load_manual_events(manual_path, allow_missing=True),
        as_of=as_of,
    )
    print_events(events, args.format)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Git管理の手動稽古会イベントを登録・更新します。"
    )
    parser.add_argument(
        "--file",
        default=str(DEFAULT_MANUAL_EVENTS_PATH),
        help="manual_events.json path",
    )
    parser.add_argument(
        "--organizations",
        default=str(DEFAULT_ORGANIZATIONS_PATH),
        help="organizations.json path",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add")
    add_common_arguments(add_parser)
    add_parser.add_argument("--date", required=True)

    batch_parser = subparsers.add_parser("add-batch")
    add_common_arguments(batch_parser)
    batch_parser.add_argument("--date", action="append", required=True)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--status", choices=sorted(VALID_MANUAL_STATUSES))
    list_parser.add_argument("--organization-id")
    list_parser.add_argument("--format", choices=["text", "json"], default="text")

    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("event_id")

    update_parser = subparsers.add_parser("update")
    update_parser.add_argument("event_id")
    update_parser.add_argument("--date")
    update_parser.add_argument("--title")
    update_parser.add_argument("--event-type")
    update_parser.add_argument("--start-time")
    update_parser.add_argument("--end-time")
    update_parser.add_argument("--venue")
    update_parser.add_argument("--area")
    update_parser.add_argument("--address")
    update_parser.add_argument("--access")
    update_parser.add_argument("--fee")
    update_parser.add_argument(
        "--application-required",
        choices=["yes", "no", "unknown"],
    )
    update_parser.add_argument("--source-url")
    update_parser.add_argument(
        "--participation-type",
        choices=sorted(VALID_PARTICIPATION_TYPES),
    )
    update_parser.add_argument("--verified-at")
    update_parser.add_argument("--review-due-at")
    update_parser.add_argument("--note")
    update_parser.add_argument(
        "--clear-field",
        action="append",
        choices=sorted(CLEARABLE_FIELDS),
        default=[],
    )
    update_parser.add_argument("--dry-run", action="store_true")

    for command in ("cancel", "archive"):
        status_parser = subparsers.add_parser(command)
        status_parser.add_argument("event_id")
        status_parser.add_argument("--dry-run", action="store_true")

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("event_id")
    verify_parser.add_argument("--verified-at")
    verify_parser.add_argument("--review-due-at", required=True)
    verify_parser.add_argument("--dry-run", action="store_true")

    due_parser = subparsers.add_parser("list-review-due")
    due_parser.add_argument("--as-of")
    due_parser.add_argument("--format", choices=["text", "json"], default="text")

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    manual_path = Path(args.file)
    organizations_path = Path(args.organizations)

    try:
        if args.command == "add":
            return handle_add(
                args,
                manual_path=manual_path,
                organizations_path=organizations_path,
            )
        if args.command == "add-batch":
            return handle_add_batch(
                args,
                manual_path=manual_path,
                organizations_path=organizations_path,
            )
        if args.command == "list":
            return handle_list(args, manual_path=manual_path)
        if args.command == "show":
            return handle_show(args, manual_path=manual_path)
        if args.command == "update":
            return handle_update(args, manual_path=manual_path)
        if args.command == "cancel":
            return handle_status_change(
                args,
                manual_path=manual_path,
                status="cancelled",
            )
        if args.command == "archive":
            return handle_status_change(
                args,
                manual_path=manual_path,
                status="archived",
            )
        if args.command == "verify":
            return handle_verify(args, manual_path=manual_path)
        if args.command == "list-review-due":
            return handle_list_review_due(args, manual_path=manual_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
