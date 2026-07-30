from __future__ import annotations

import datetime as dt
import hashlib
import re
import sys
from typing import Iterable, Optional

from kendo_keiko.models import (
    Organization,
    ParticipationType,
    RawScrapedEvent,
    ServiceEvent,
)
from kendo_keiko.scrapers import SCRAPER_REGISTRY
from kendo_keiko.scrapers.common import JST


def debug_print(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[DEBUG] {message}", file=sys.stderr)


def scrape_by_org(
    org: Organization,
    debug: bool = False,
) -> list[RawScrapedEvent]:
    if not org.scraper_enabled:
        debug_print(
            debug,
            f"scraper disabled: {org.organization_id}",
        )
        return []

    scraper = SCRAPER_REGISTRY.get(org.scraper_type)

    if scraper is None:
        print(
            f"[WARN] unknown scraper_type: {org.scraper_type}",
            file=sys.stderr,
        )
        return []

    return scraper(org, debug=debug)


def event_score(event: RawScrapedEvent) -> int:
    """
    同一イベントが複数ソースから取れたとき、
    情報量が多い方を残すためのスコア。
    """
    score = 0
    for value in (
        event.title,
        event.weekday,
        event.start_time,
        event.end_time,
        event.venue,
        event.access,
        event.note,
        event.source_url,
    ):
        if value:
            score += 1
    return score


def dedupe_events(
    events: Iterable[RawScrapedEvent],
) -> list[RawScrapedEvent]:
    """
    同一イベントらしきものを重複排除する。

    venueが取得できたりできなかったりしても同一扱いできるよう、
    venueはキーから外す。同一キーでは情報量の多いイベントを残す。
    """
    best: dict[tuple, RawScrapedEvent] = {}

    for event in events:
        key = (
            event.group,
            event.event_type,
            event.date,
            event.start_time,
            event.end_time,
        )

        if key not in best or event_score(event) > event_score(best[key]):
            best[key] = event

    return sorted(
        best.values(),
        key=lambda item: (
            item.date,
            item.start_time or "",
            item.group,
        ),
    )


def filter_events_from_date(
    events: Iterable[RawScrapedEvent],
    from_date: dt.date,
) -> list[RawScrapedEvent]:
    """
    from_date以降のイベントだけを残す。
    """
    result: list[RawScrapedEvent] = []

    for event in events:
        try:
            event_date = dt.date.fromisoformat(event.date)
        except ValueError:
            continue

        if event_date >= from_date:
            result.append(event)

    return sorted(
        result,
        key=lambda item: (
            item.date,
            item.start_time or "",
            item.group,
        ),
    )


def parse_from_date(value: Optional[str]) -> dt.date:
    """
    --from-dateが指定されていればその日付、
    未指定ならJSTの今日を返す。
    """
    if value:
        try:
            return dt.date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                "--from-date は YYYY-MM-DD 形式で指定してください。"
                "例: 2026-07-09"
            ) from exc

    return dt.datetime.now(JST).date()


def make_event_id(
    *,
    org_id: str,
    event_date: str,
    start_time: Optional[str],
    end_time: Optional[str],
    venue: Optional[str],
    title: Optional[str],
    source_url: str,
) -> str:
    """
    DynamoDBの主キーとして使う安定IDを生成する。
    """
    start = (start_time or "unknown").replace(":", "")
    date_part = event_date.replace("-", "")
    base = "|".join(
        [
            org_id,
            event_date,
            start_time or "",
            end_time or "",
            venue or "",
            title or "",
            source_url,
        ]
    )
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
    return f"{org_id}-{date_part}-{start}-{digest}"


def make_gsi1_keys(
    *,
    event_date: str,
    start_time: Optional[str],
    organization_id: str,
    event_id: str,
) -> tuple[str, str]:
    """
    DateIndex用のキーを生成する。
    """
    safe_start_time = start_time or "00:00"
    return (
        "EVENT",
        f"{event_date}#{safe_start_time}#{organization_id}#{event_id}",
    )


def extract_fee(note: Optional[str]) -> Optional[str]:
    if not note:
        return None

    match = re.search(r"参加費[:：]\s*(?P<fee>.+)", note)
    if not match:
        return None

    return re.sub(r"\s+", " ", match.group("fee")).strip()


def infer_application_required(
    note: Optional[str],
    title: Optional[str],
) -> Optional[bool]:
    text = " ".join(value for value in [note, title] if value)
    if not text:
        return None

    if (
        "事前申し込み" in text
        or "申込必須" in text
        or "申し込み必須" in text
    ):
        return True

    if "申込不要" in text or "予約不要" in text or "自由参加" in text:
        return False

    return None



def resolve_participation_metadata(
    *,
    org: Organization,
    note: Optional[str],
    title: Optional[str],
) -> tuple[Optional[bool], ParticipationType]:
    """Resolve event metadata, preferring event text over org defaults."""
    application_required = infer_application_required(note, title)
    if application_required is None:
        application_required = org.default_application_required

    participation_type = org.default_participation_type
    if (
        application_required is True
        and participation_type
        in {"anyone", "contact_required", "unknown"}
    ):
        participation_type = "registration_required"
    elif (
        application_required is False
        and participation_type == "registration_required"
    ):
        participation_type = "unknown"

    return application_required, participation_type

def normalize_events(
    raw_events: Iterable[RawScrapedEvent],
    organizations: list[Organization],
    scraped_at: str,
) -> list[ServiceEvent]:
    org_by_name = {org.name: org for org in organizations}
    service_events: list[ServiceEvent] = []

    for raw in raw_events:
        org = org_by_name.get(raw.group)
        if not org:
            print(
                f"[WARN] organization not found for group: {raw.group}",
                file=sys.stderr,
            )
            continue

        event_id = make_event_id(
            org_id=org.organization_id,
            event_date=raw.date,
            start_time=raw.start_time,
            end_time=raw.end_time,
            venue=raw.venue,
            title=raw.title,
            source_url=raw.source_url,
        )
        gsi1_pk, gsi1_sk = make_gsi1_keys(
            event_date=raw.date,
            start_time=raw.start_time,
            organization_id=org.organization_id,
            event_id=event_id,
        )
        (
            application_required,
            participation_type,
        ) = resolve_participation_metadata(
            org=org,
            note=raw.note,
            title=raw.title,
        )

        service_events.append(
            ServiceEvent(
                event_id=event_id,
                organization_id=org.organization_id,
                organization_name=org.name,
                event_type=raw.event_type,
                title=raw.title,
                event_date=raw.date,
                weekday=raw.weekday,
                start_time=raw.start_time,
                end_time=raw.end_time,
                venue=raw.venue,
                area=raw.area or org.area,
                address=None,
                access=raw.access,
                fee=extract_fee(raw.note),
                application_required=application_required,
                source_url=raw.source_url,
                source_type=org.source_type,
                last_scraped_at=scraped_at,
                status="active",
                raw_note=raw.note,
                update_mode="automatic",
                participation_type=participation_type,
                verified_at=None,
                gsi1_pk=gsi1_pk,
                gsi1_sk=gsi1_sk,
            )
        )

    return sorted(
        service_events,
        key=lambda event: (
            event.event_date,
            event.start_time or "",
            event.organization_id,
        ),
    )


def run_pipeline(
    *,
    organizations: list[Organization],
    scraped_at: str,
    from_date: Optional[dt.date],
    debug: bool = False,
) -> list[ServiceEvent]:
    """
    スクレイピングからサービス用イベントへの変換までを実行する。

    from_dateがNoneの場合は過去イベントも含める。
    """
    raw_events: list[RawScrapedEvent] = []

    for org in organizations:
        debug_print(debug, f"scrape: {org.organization_id}")
        raw_events.extend(scrape_by_org(org, debug=debug))

    debug_print(debug, f"raw events before dedupe: {len(raw_events)}")
    raw_events = dedupe_events(raw_events)
    debug_print(debug, f"raw events after dedupe: {len(raw_events)}")

    if from_date is not None:
        raw_events = filter_events_from_date(raw_events, from_date)
        debug_print(
            debug,
            f"raw events after date filter: {len(raw_events)}",
        )

    return normalize_events(
        raw_events,
        organizations,
        scraped_at,
    )
