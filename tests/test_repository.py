from __future__ import annotations

import unittest
from unittest.mock import patch

from kendo_keiko.models import ServiceEvent
from kendo_keiko.repository import save_dynamodb


class FakeBatchWriter:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def put_item(self, *, Item: dict) -> None:
        self.items.append(Item)


class FakeTable:
    def __init__(self) -> None:
        self.writer = FakeBatchWriter()

    def batch_writer(self) -> FakeBatchWriter:
        return self.writer


class FakeDynamoDbResource:
    def __init__(self, table: FakeTable) -> None:
        self.table = table

    def Table(self, table_name: str) -> FakeTable:
        return self.table


class RepositoryTests(unittest.TestCase):
    def make_event(self) -> ServiceEvent:
        return ServiceEvent(
            event_id="event-1",
            organization_id="test-org",
            organization_name="テスト団体",
            event_type="open_keiko",
            title="通常稽古",
            event_date="2026-08-01",
            weekday="土",
            start_time="19:00",
            end_time="20:30",
            venue="テスト武道館",
            area="東京都",
            address=None,
            access=None,
            fee=None,
            application_required=None,
            source_url="https://example.com/",
            source_type="official_site",
            last_scraped_at="2026-07-24T09:00:00+09:00",
            status="active",
            raw_note=None,
            update_mode="automatic",
            participation_type="unknown",
            verified_at=None,
            gsi1_pk="EVENT",
            gsi1_sk="2026-08-01#19:00#test-org#event-1",
        )

    def test_saves_event_metadata_and_preserves_null_verified_at(self) -> None:
        table = FakeTable()
        resource = FakeDynamoDbResource(table)

        with patch(
            "kendo_keiko.repository.boto3.resource",
            return_value=resource,
        ):
            save_dynamodb(
                events=[self.make_event()],
                table_name="KendoKeikoEvents",
                region="ap-northeast-1",
            )

        self.assertEqual(1, len(table.writer.items))
        item = table.writer.items[0]
        self.assertEqual("automatic", item["update_mode"])
        self.assertEqual("unknown", item["participation_type"])
        self.assertIn("verified_at", item)
        self.assertIsNone(item["verified_at"])
        self.assertNotIn("address", item)
