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


    def test_hagakurey_weeknight_events_are_valid(self) -> None:
        source_url = "https://www.instagram.com/p/Dbii2xfTw5J/"
        events = [
            event
            for event in load_manual_events()
            if event["source_url"] == source_url
        ]

        self.assertEqual(11, len(events))
        self.assertEqual(
            [
                "2026-08-10",
                "2026-08-12",
                "2026-08-13",
                "2026-08-18",
                "2026-08-19",
                "2026-08-20",
                "2026-08-24",
                "2026-08-25",
                "2026-08-26",
                "2026-08-27",
                "2026-08-28",
            ],
            [event["event_date"] for event in events],
        )

        for event in events:
            self.assertEqual("hagakurey", event["organization_id"])
            self.assertEqual(
                "HAGAKUREY 8月平日夜稽古",
                event["title"],
            )
            self.assertEqual("21:00", event["start_time"])
            self.assertEqual("22:30", event["end_time"])
            self.assertEqual(
                "墨田区総合体育館",
                event["venue"],
            )
            self.assertIsNone(event["fee"])
            self.assertFalse(event["application_required"])
            self.assertEqual(
                "contact_required",
                event["participation_type"],
            )
            self.assertEqual("manual", event["update_mode"])
            self.assertEqual("active", event["status"])


    def test_kent_ladies_event_is_valid(self) -> None:
        events = [
            event
            for event in load_manual_events()
            if event["organization_id"] == "kent_ladies"
        ]

        self.assertEqual(1, len(events))

        event = events[0]

        self.assertEqual("2026-08-30", event["event_date"])
        self.assertEqual("日", event["weekday"])
        self.assertEqual(
            "kent女子稽古会 8月30日稽古",
            event["title"],
        )
        self.assertEqual("12:30", event["start_time"])
        self.assertEqual("15:00", event["end_time"])
        self.assertEqual(
            "文京スポーツセンター4階",
            event["venue"],
        )
        self.assertEqual("500円", event["fee"])
        self.assertEqual("anyone", event["participation_type"])
        self.assertFalse(event["application_required"])
        self.assertEqual("manual", event["update_mode"])
        self.assertEqual("sns", event["source_type"])
        self.assertEqual(
            "https://www.instagram.com/p/DaW0XADE927/",
            event["source_url"],
        )


    def test_kizunakai_event_is_valid(self) -> None:
        events = [
            event
            for event in load_manual_events()
            if event["organization_id"] == "kizunakai"
        ]

        self.assertEqual(1, len(events))

        event = events[0]

        self.assertEqual("2026-08-14", event["event_date"])
        self.assertEqual("金", event["weekday"])
        self.assertEqual("絆剱会 ゆる稽古会", event["title"])
        self.assertEqual("19:00", event["start_time"])
        self.assertEqual("21:30", event["end_time"])
        self.assertEqual(
            "川越市名細市民センター 多目的室",
            event["venue"],
        )
        self.assertEqual(
            "一般200円／大学生以下100円",
            event["fee"],
        )
        self.assertEqual("anyone", event["participation_type"])
        self.assertFalse(event["application_required"])
        self.assertEqual("manual", event["update_mode"])
        self.assertEqual("sns", event["source_type"])
        self.assertEqual(
            "https://www.instagram.com/p/Db2tH9hhkNr/",
            event["source_url"],
        )


    def test_seikenkai_inzai_events_are_valid(self) -> None:
        events = [
            event
            for event in load_manual_events()
            if event["organization_id"] == "seikenkai_inzai"
        ]

        self.assertEqual(2, len(events))
        self.assertEqual(
            ["2026-08-21", "2026-08-28"],
            [event["event_date"] for event in events],
        )

        for event in events:
            self.assertEqual(
                "西劔会 8月オープン稽古会",
                event["title"],
            )
            self.assertEqual("19:00", event["start_time"])
            self.assertEqual("21:00", event["end_time"])
            self.assertEqual(
                "印西市立西の原中学校",
                event["venue"],
            )
            self.assertEqual("無料", event["fee"])
            self.assertEqual("anyone", event["participation_type"])
            self.assertFalse(event["application_required"])
            self.assertEqual("manual", event["update_mode"])
            self.assertEqual("sns", event["source_type"])
            self.assertEqual(
                "https://www.instagram.com/p/DbeucGlzVHK/",
                event["source_url"],
            )


if __name__ == "__main__":
    unittest.main()
