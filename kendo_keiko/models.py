from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Literal, Optional


UpdateMode = Literal["automatic", "assisted", "manual"]
ParticipationType = Literal[
    "anyone",
    "contact_required",
    "registration_required",
    "invitation_required",
    "members_only",
    "unknown",
]

VALID_UPDATE_MODES = frozenset({"automatic", "assisted", "manual"})
VALID_PARTICIPATION_TYPES = frozenset(
    {
        "anyone",
        "contact_required",
        "registration_required",
        "invitation_required",
        "members_only",
        "unknown",
    }
)

LEGACY_UPDATE_MODE: UpdateMode = "automatic"
LEGACY_PARTICIPATION_TYPE: ParticipationType = "unknown"


def validate_event_metadata(
    *,
    update_mode: str,
    participation_type: str,
    verified_at: Optional[str],
    review_due_at: Optional[str] = None,
) -> None:
    if update_mode not in VALID_UPDATE_MODES:
        raise ValueError(f"invalid update_mode: {update_mode}")

    if participation_type not in VALID_PARTICIPATION_TYPES:
        raise ValueError(
            f"invalid participation_type: {participation_type}"
        )

    if verified_at is not None:
        try:
            parsed = dt.datetime.fromisoformat(verified_at)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "verified_at must be an ISO 8601 datetime with timezone"
            ) from exc

        if parsed.tzinfo is None:
            raise ValueError(
                "verified_at must be an ISO 8601 datetime with timezone"
            )

    if review_due_at is not None:
        try:
            dt.date.fromisoformat(review_due_at)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "review_due_at must be a YYYY-MM-DD date"
            ) from exc


def normalize_event_metadata(
    event: dict[str, Any],
) -> dict[str, Any]:
    """
    Legacy DynamoDB items do not have Issue #22 metadata.

    Missing fields are supplemented only while loading/publishing old data.
    Explicit invalid values are rejected instead of silently overwritten.
    """
    normalized = dict(event)

    if "update_mode" not in normalized:
        normalized["update_mode"] = LEGACY_UPDATE_MODE
    if "participation_type" not in normalized:
        normalized["participation_type"] = LEGACY_PARTICIPATION_TYPE
    if "verified_at" not in normalized:
        normalized["verified_at"] = None
    if "review_due_at" not in normalized:
        normalized["review_due_at"] = None

    validate_event_metadata(
        update_mode=normalized["update_mode"],
        participation_type=normalized["participation_type"],
        verified_at=normalized["verified_at"],
        review_due_at=normalized["review_due_at"],
    )
    return normalized


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

    # Issue #22: イベント単位の取得・参加・確認メタデータ
    update_mode: UpdateMode
    participation_type: ParticipationType
    verified_at: Optional[str]

    # DynamoDB DateIndex用
    gsi1_pk: str
    gsi1_sk: str

    # 手動情報の次回確認期限。自動取得イベントではNone。
    review_due_at: Optional[str] = None

    def __post_init__(self) -> None:
        validate_event_metadata(
            update_mode=self.update_mode,
            participation_type=self.participation_type,
            verified_at=self.verified_at,
            review_due_at=self.review_due_at,
        )
