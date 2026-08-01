from __future__ import annotations

import unittest

from kendo_keiko.manual_events import load_manual_events
from kendo_keiko.repository import find_organization, load_organizations


class ManualEventDataTests(unittest.TestCase):
    def test_magokorokai_events_are_valid_and_linked_to_organization(self) -> None:
        organizations = load_organizations()
        organization = find_organization(organizations, "magokorokai")
        events = [
            event
            for event in load_manual_events()
            if event["organization_id"] == "magokorokai"
        ]

        self.assertEqual("眞心会", organization.name)
        self.assertEqual("manual", organization.scraper_type)
        self.assertFalse(organization.scraper_enabled)
        self.assertEqual(14, len(events))
        self.assertEqual(
            [
                "2026-07-28",
                "2026-07-30",
                "2026-08-04",
                "2026-08-18",
                "2026-08-20",
                "2026-08-25",
                "2026-08-27",
            "2026-09-01",
            "2026-09-08",
            "2026-09-10",
            "2026-09-15",
            "2026-09-17",
            "2026-09-24",
            "2026-09-29",
            ],
            [event["event_date"] for event in events],
        )
        for event in events:
            self.assertEqual("manual", event["update_mode"])
            self.assertEqual("anyone", event["participation_type"])
            self.assertEqual("active", event["status"])
            self.assertEqual("19:30", event["start_time"])
            self.assertEqual("20:30", event["end_time"])
            expected_review_due_at = (
                "2026-09-01"
                if event["event_date"] >= "2026-09-01"
                else "2026-08-24"
            )
            self.assertEqual(
                expected_review_due_at,
                event["review_due_at"],
            )


if __name__ == "__main__":
    unittest.main()
