from __future__ import annotations

import unittest
from unittest.mock import patch

from kendo_keiko.publication import (
    build_public_events_payload,
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
        self.assertEqual("public-events-0.2", payload["schema_version"])
        self.assertEqual("manual", event["update_mode"])
        self.assertEqual("members_only", event["participation_type"])
        self.assertEqual("2026-07-24T09:00:00+09:00", event["verified_at"])


if __name__ == "__main__":
    unittest.main()
