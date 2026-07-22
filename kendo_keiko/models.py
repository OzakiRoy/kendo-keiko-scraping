from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class Organization:
    organization_id: str
    name: str
    area: Optional[str]
    website_url: str
    source_type: str
    scraper_type: str
    scraper_enabled: bool
    event_type: str
    notes: Optional[str] = None
    public_description: Optional[str] = None


@dataclass(frozen=True)
class ScrapeResult:
    """One scraper worker execution summary passed through Step Functions."""

    run_id: str
    organization_id: str
    scraper_type: str
    status: Literal["success", "warning", "failure"]
    event_count: int
    duration_ms: int
    checked_at: str
    from_date: str
    error_type: Optional[str] = None
    error_message: Optional[str] = None


@dataclass(frozen=True)
class RawScrapedEvent:
    """
    各スクレイパーが返す正規化前のイベント。
    """

    group: str
    title: Optional[str]
    date: str
    weekday: Optional[str]
    start_time: Optional[str]
    end_time: Optional[str]
    venue: Optional[str]
    area: Optional[str]
    access: Optional[str]
    note: Optional[str]
    source_url: str
    event_type: str


@dataclass(frozen=True)
class ServiceEvent:
    """
    JSON・DynamoDBへ保存するサービス用イベント。
    """

    event_id: str
    organization_id: str
    organization_name: str
    event_type: str
    title: Optional[str]
    event_date: str
    weekday: Optional[str]
    start_time: Optional[str]
    end_time: Optional[str]
    venue: Optional[str]
    area: Optional[str]
    address: Optional[str]
    access: Optional[str]
    fee: Optional[str]
    application_required: Optional[bool]
    source_url: str
    source_type: str
    last_scraped_at: str
    status: str
    raw_note: Optional[str]

    # DynamoDB DateIndex用
    gsi1_pk: str
    gsi1_sk: str
