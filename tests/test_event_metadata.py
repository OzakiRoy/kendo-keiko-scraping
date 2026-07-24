from __future__ import annotations

import unittest

from kendo_keiko.models import (
    ServiceEvent,
    normalize_event_metadata,
)


class EventMetadataTests(unittest.TestCase):
    def make_event(self, **overrides) -> ServiceEvent:
        values = {
            "event_id": "event-1",
            "organization_id": "test-org",
            "organization_name": "テスト団体",
            "event_type": "open_keiko",
            "title": "通常稽古",
            "event_date": "2026-08-01",
            "weekday": "土",
            "start_time": "19:00",
            "end_time": "20:30",
            "venue": "テスト武道館",
            "area": "東京都",
            "address": None,
            "access": None,
            "fee": None,
            "application_required": None,
            "source_url": "https://example.com/",
            "source_type": "official_site",
            "last_scraped_at": "2026-07-24T09:00:00+09:00",
            "status": "active",
            "raw_note": None,
            "update_mode": "automatic",
            "participation_type": "unknown",
            "verified_at": None,
            "gsi1_pk": "EVENT",
            "gsi1_sk": "2026-08-01#19:00#test-org#event-1",
        }
        values.update(overrides)
        return ServiceEvent(**values)

    def test_supplements_legacy_event_metadata(self) -> None:
        event = normalize_event_metadata({"event_id": "legacy-event"})

        self.assertEqual("automatic", event["update_mode"])
        self.assertEqual("unknown", event["participation_type"])
        self.assertIsNone(event["verified_at"])
        self.assertIsNone(event["review_due_at"])

    def test_preserves_explicit_event_metadata(self) -> None:
        event = normalize_event_metadata(
            {
                "event_id": "manual-event",
                "update_mode": "manual",
                "participation_type": "contact_required",
                "verified_at": "2026-07-24T09:00:00+09:00",
            }
        )

        self.assertEqual("manual", event["update_mode"])
        self.assertEqual("contact_required", event["participation_type"])
        self.assertEqual(
            "2026-07-24T09:00:00+09:00",
            event["verified_at"],
        )

    def test_rejects_invalid_update_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid update_mode"):
            self.make_event(update_mode="scheduled")

    def test_rejects_invalid_participation_type(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid participation_type"):
            self.make_event(participation_type="open")

    def test_rejects_verified_at_without_timezone(self) -> None:
        with self.assertRaisesRegex(ValueError, "with timezone"):
            self.make_event(verified_at="2026-07-24T09:00:00")
