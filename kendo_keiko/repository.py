from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import boto3

from kendo_keiko.models import Organization, ServiceEvent


DEFAULT_ORGANIZATIONS_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "organizations.json"
)


def load_organizations(
    path: Path = DEFAULT_ORGANIZATIONS_PATH,
) -> list[Organization]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("organizations.json must contain a JSON array")
    return [Organization(**item) for item in raw]


def find_organization(
    organizations: list[Organization],
    organization_id: str,
) -> Organization:
    for organization in organizations:
        if organization.organization_id == organization_id:
            return organization
    raise ValueError(f"organization_id not found: {organization_id}")


def remove_none_values(item: dict) -> dict:
    return {key: value for key, value in item.items() if value is not None}


def service_event_to_dynamodb_item(event: ServiceEvent) -> dict:
    item = remove_none_values(asdict(event))

    # verified_at=None means "not yet verified" and must be distinguishable
    # from legacy items where the Issue #22 field itself does not exist.
    item["verified_at"] = event.verified_at
    return item


def save_dynamodb(
    *,
    events: list[ServiceEvent],
    table_name: str,
    region: str,
) -> None:
    """Insert or replace event items in DynamoDB."""
    if not events:
        return

    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)

    with table.batch_writer() as batch:
        for event in events:
            batch.put_item(Item=service_event_to_dynamodb_item(event))
