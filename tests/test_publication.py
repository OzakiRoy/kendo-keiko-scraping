from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kendo_keiko.manual_events import build_manual_event, save_manual_events
from kendo_keiko.models import Organization
from kendo_keiko.publication import (
    build_public_events_payload,
    publish_public_site,
    query_events_from_dynamodb,
)


class FakeTable:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def query(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeDynamoDbResource:
    def __init__(self, table: FakeTable) -> None:
        self.table = table

    def Table(self, table_name: str) -> FakeTable:
        return self.table


class PublicationTests(unittest.TestCase):
    def test_query_supplements_legacy_metadata_and_sorts_events(self) -> None:
        table = FakeTable(
            [
                {
                    "Items": [
                        {
                            "event_id": "event-2",
                            "organization_id": "org-b",
                            "event_date": "2026-08-02",
                            "start_time": "19:00",
                        },
                        {
                            "event_id": "event-1",
                            "organization_id": "org-a",
                            "event_date": "2026-08-01",
                            "start_time": "09:00",
                        },
                    ]
                }
            ]
        )
        resource = FakeDynamoDbResource(table)

        with patch(
            "kendo_keiko.publication.boto3.resource",
            return_value=resource,
        ):
            events = query_events_from_dynamodb(
                table_name="KendoKeikoEvents",
                region_name="ap-northeast-1",
                from_date="2026-07-24",
            )

        self.assertEqual(["event-1", "event-2"], [e["event_id"] for e in events])
        for event in events:
            self.assertEqual("automatic", event["update_mode"])
            self.assertEqual("unknown", event["participation_type"])
            self.assertIsNone(event["verified_at"])

    def test_payload_preserves_explicit_manual_metadata(self) -> None:
        payload = build_public_events_payload(
            events=[
                {
                    "event_id": "manual-event",
                    "update_mode": "manual",
                    "participation_type": "members_only",
                    "verified_at": "2026-07-24T09:00:00+09:00",
                }
            ],
            table_name="KendoKeikoEvents",
            region_name="ap-northeast-1",
            from_date="2026-07-24",
        )

        event = payload["events"][0]
        self.assertEqual("public-events-0.3", payload["schema_version"])
        self.assertEqual("manual", event["update_mode"])
        self.assertEqual("members_only", event["participation_type"])
        self.assertEqual("2026-07-24T09:00:00+09:00", event["verified_at"])

    def test_publish_public_site_merges_manual_events(self) -> None:
        organization = Organization(
            organization_id="manual-org",
            name="手動団体",
            area="埼玉県",
            website_url="https://example.com/",
            source_type="official_site",
            scraper_type="manual",
            scraper_enabled=False,
            event_type="open_keiko",
        )
        event = build_manual_event(
            organization=organization,
            event_date="2026-08-10",
            source_url="https://example.com/event",
            verified_at="2026-07-24T10:00:00+09:00",
            review_due_at="2026-08-24",
            title="手動稽古会",
        )

        with tempfile.TemporaryDirectory() as directory:
            manual_path = Path(directory) / "manual_events.json"
            save_manual_events(path=manual_path, events=[event])
            with (
                patch(
                    "kendo_keiko.publication.query_events_from_dynamodb",
                    return_value=[],
                ),
                patch(
                    "kendo_keiko.publication.upload_events_json_to_s3"
                ) as upload_json,
            ):
                result = publish_public_site(
                    table_name="KendoKeikoEvents",
                    region_name="ap-northeast-1",
                    from_date="2026-07-24",
                    events_bucket="example-bucket",
                    publish_index_html=False,
                    manual_events_path=manual_path,
                )

        payload = upload_json.call_args.kwargs["payload"]
        self.assertEqual(1, result["event_count"])
        self.assertEqual("manual", payload["events"][0]["update_mode"])
        self.assertEqual("手動稽古会", payload["events"][0]["title"])


if __name__ == "__main__":
    unittest.main()
