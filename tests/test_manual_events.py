from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from kendo_keiko.manual_events import (
    build_manual_event,
    list_review_due_events,
    load_manual_events,
    merge_public_events,
    save_manual_events,
)
from kendo_keiko.models import Organization


class ManualEventsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.organization = Organization(
            organization_id="manual-org",
            name="手動団体",
            area="埼玉県",
            website_url="https://example.com/",
            source_type="official_site",
            scraper_type="manual",
            scraper_enabled=False,
            event_type="open_keiko",
        )

    def make_event(self, **overrides):
        values = {
            "organization": self.organization,
            "event_date": "2026-08-10",
            "source_url": "https://example.com/events/1",
            "verified_at": "2026-07-24T10:00:00+09:00",
            "review_due_at": "2026-08-24",
            "title": "合同稽古会",
            "start_time": "19:00",
            "end_time": "20:30",
            "venue": "テスト武道館",
            "participation_type": "contact_required",
        }
        values.update(overrides)
        return build_manual_event(**values)

    def test_round_trip_manual_events_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manual_events.json"
            event = self.make_event()

            save_manual_events(path=path, events=[event])
            loaded = load_manual_events(path)

        self.assertEqual([event], loaded)
        self.assertEqual("manual", loaded[0]["update_mode"])
        self.assertEqual("2026-08-24", loaded[0]["review_due_at"])

    def test_rejects_non_official_url_and_missing_timezone(self) -> None:
        with self.assertRaisesRegex(ValueError, "official http"):
            self.make_event(source_url="not-a-url")

        with self.assertRaisesRegex(ValueError, "with timezone"):
            self.make_event(verified_at="2026-07-24T10:00:00")

    def test_manual_event_overrides_automatic_duplicate(self) -> None:
        manual = self.make_event(title="手動で確認した稽古会")
        automatic = {
            **manual,
            "event_id": "automatic-event",
            "title": "自動取得の稽古会",
            "update_mode": "automatic",
            "verified_at": None,
            "review_due_at": None,
            "last_scraped_at": "2026-07-24T05:00:00+09:00",
        }

        events = merge_public_events(
            automatic_events=[automatic],
            manual_events=[manual],
            from_date="2026-07-24",
        )

        self.assertEqual(1, len(events))
        self.assertEqual("手動で確認した稽古会", events[0]["title"])
        self.assertEqual("manual", events[0]["update_mode"])

    def test_cancelled_manual_event_suppresses_automatic_duplicate(self) -> None:
        manual = self.make_event()
        automatic = {
            **manual,
            "event_id": "automatic-event",
            "update_mode": "automatic",
            "verified_at": None,
            "review_due_at": None,
        }
        manual["status"] = "cancelled"

        events = merge_public_events(
            automatic_events=[automatic],
            manual_events=[manual],
            from_date="2026-07-24",
        )

        self.assertEqual([], events)

    def test_filters_past_events_and_lists_review_due(self) -> None:
        past = self.make_event(
            event_date="2026-07-23",
            source_url="https://example.com/events/past",
        )
        due = self.make_event(
            event_date="2026-08-10",
            source_url="https://example.com/events/due",
            review_due_at="2026-07-24",
        )
        future_review = self.make_event(
            event_date="2026-08-11",
            source_url="https://example.com/events/future",
            review_due_at="2026-07-25",
        )

        public_events = merge_public_events(
            automatic_events=[],
            manual_events=[past, due, future_review],
            from_date="2026-07-24",
        )
        review_due = list_review_due_events(
            [past, due, future_review],
            as_of=dt.date(2026, 7, 24),
        )

        self.assertEqual(2, len(public_events))
        self.assertEqual([due["event_id"]], [e["event_id"] for e in review_due])

    def test_missing_file_is_rejected_unless_explicitly_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"
            with self.assertRaises(FileNotFoundError):
                load_manual_events(path)
            self.assertEqual([], load_manual_events(path, allow_missing=True))


if __name__ == "__main__":
    unittest.main()
