from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
import unittest

from kendo_keiko.manual_events import (
    DEFAULT_MANUAL_EVENTS_PATH,
    load_manual_events,
    sort_manual_events,
)
from kendo_keiko.repository import find_organization, load_organizations


class ManualEventDataTests(unittest.TestCase):
    def test_manual_events_file_uses_canonical_order(self) -> None:
        payload = json.loads(
            DEFAULT_MANUAL_EVENTS_PATH.read_text(encoding="utf-8")
        )
        events = payload["events"]

        self.assertEqual(
            [event["event_id"] for event in sort_manual_events(events)],
            [event["event_id"] for event in events],
        )

    def test_kenen_events_are_valid_and_linked_to_organization(self) -> None:
        organizations = load_organizations()
        organization = find_organization(organizations, "kenen")
        events = [
            event
            for event in load_manual_events()
            if event["organization_id"] == "kenen"
        ]

        self.assertEqual("剣縁", organization.name)
        self.assertEqual("manual", organization.scraper_type)
        self.assertFalse(organization.scraper_enabled)
        self.assertEqual(2, len(events))
        self.assertEqual(
            [
                "kenen-20260830-0930-fcace356",
                "kenen-20260922-1330-4099ce0f",
            ],
            [event["event_id"] for event in events],
        )

        event = events[1]
        self.assertEqual("剣縁", event["organization_name"])
        self.assertEqual("剣縁の集い 第2回", event["title"])
        self.assertEqual("2026-09-22", event["event_date"])
        self.assertEqual("火", event["weekday"])
        self.assertEqual("13:30", event["start_time"])
        self.assertEqual("14:30", event["end_time"])
        self.assertEqual(
            "渋谷区スポーツセンター 第1武道場",
            event["venue"],
        )
        self.assertEqual("東京都", event["area"])
        self.assertEqual("東京都渋谷区西原1-40-18", event["address"])
        self.assertEqual(
            "京王新線「幡ヶ谷駅」南口から徒歩約6分、"
            "小田急線「代々木上原駅」から徒歩約15分",
            event["access"],
        )
        self.assertEqual(
            "1,000円（税込）／名、剣縁法人・個人会員は無料",
            event["fee"],
        )
        self.assertTrue(event["application_required"])
        self.assertEqual(
            "registration_required",
            event["participation_type"],
        )
        self.assertEqual(
            "https://kenen.jp/event/ken-en-no-tsudoi-2",
            event["source_url"],
        )
        self.assertEqual("official_site", event["source_type"])
        self.assertEqual("manual", event["update_mode"])
        self.assertEqual("active", event["status"])
        self.assertEqual("2026-09-15", event["review_due_at"])
        self.assertIn("終了時刻は予定", event["raw_note"])
        self.assertIn("エントリー締切は2026年9月14日", event["raw_note"])
        self.assertIn("最少催行人数5名", event["raw_note"])
        self.assertIn(
            "https://forms.gle/5McZ8QVgjh961haJ6",
            event["raw_note"],
        )

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


    def test_hagakurey_september_events_are_valid(self) -> None:
        source_url = "https://www.instagram.com/p/DcgkP0szPim/"
        events = [
            event
            for event in load_manual_events()
            if event["source_url"] == source_url
        ]

        expected_schedules = {
            "2026-09-05": ("15:00", "18:00", "墨田区総合体育館"),
            "2026-09-06": ("18:00", "21:00", "墨田区総合体育館"),
            "2026-09-12": (
                "15:00",
                "18:00",
                "中央区総合スポーツセンター",
            ),
            "2026-09-13": ("18:00", "21:00", "墨田区総合体育館"),
            "2026-09-19": (
                "15:00",
                "18:00",
                "中央区総合スポーツセンター",
            ),
            "2026-09-20": ("09:00", "12:00", "江東区スポーツ会館"),
            "2026-09-22": (
                "18:00",
                "20:00",
                "BumB東京スポーツ文化館",
            ),
            "2026-09-26": (
                "19:00",
                "21:00",
                "渋谷区スポーツセンター",
            ),
            "2026-09-27": ("15:00", "18:00", "墨田区総合体育館"),
        }

        self.assertEqual(9, len(events))
        self.assertEqual(
            list(expected_schedules),
            [event["event_date"] for event in events],
        )

        for event in events:
            expected_start, expected_end, expected_venue = (
                expected_schedules[event["event_date"]]
            )
            self.assertEqual("hagakurey", event["organization_id"])
            self.assertEqual(expected_start, event["start_time"])
            self.assertEqual(expected_end, event["end_time"])
            self.assertEqual(expected_venue, event["venue"])
            self.assertIsNone(event["address"])
            self.assertIsNone(event["access"])
            self.assertEqual("500円／回", event["fee"])
            self.assertFalse(event["application_required"])
            self.assertEqual(
                "contact_required",
                event["participation_type"],
            )
            self.assertEqual("open_keiko", event["event_type"])
            self.assertEqual("manual", event["update_mode"])
            self.assertEqual("active", event["status"])

        events_by_date = {
            event["event_date"]: event
            for event in events
        }
        for event_date in {"2026-09-12", "2026-09-19"}:
            self.assertEqual(
                "HAGAKUREY 9月土日稽古",
                events_by_date[event_date]["title"],
            )
            self.assertIn(
                "練習試合",
                events_by_date[event_date]["raw_note"],
            )

        special_event = events_by_date["2026-09-22"]
        self.assertEqual("HAGAKUREY 特別稽古会", special_event["title"])
        self.assertIn("特別稽古会", special_event["raw_note"])
        self.assertIn(
            "HAGAKUREYオープン剣道大会のゲスト",
            special_event["raw_note"],
        )


    def test_hagakurey_september_weeknight_events_are_valid(self) -> None:
        source_url = "https://www.instagram.com/p/DcnN8Glzbmq/"
        events = [
            event
            for event in load_manual_events()
            if event["source_url"] == source_url
        ]
        expected_dates = [
            "2026-09-01",
            "2026-09-02",
            "2026-09-03",
            "2026-09-04",
            "2026-09-07",
            "2026-09-08",
            "2026-09-09",
            "2026-09-10",
            "2026-09-11",
            "2026-09-15",
            "2026-09-16",
            "2026-09-17",
            "2026-09-18",
            "2026-09-24",
            "2026-09-25",
            "2026-09-28",
            "2026-09-29",
            "2026-09-30",
        ]

        self.assertEqual(18, len(events))
        self.assertEqual(
            expected_dates,
            [event["event_date"] for event in events],
        )

        for event in events:
            expected_times = (
                ("18:00", "21:00")
                if event["event_date"] == "2026-09-25"
                else ("21:00", "22:30")
            )
            self.assertEqual("hagakurey", event["organization_id"])
            self.assertEqual("HAGAKUREY 9月平日夜練", event["title"])
            self.assertEqual(expected_times[0], event["start_time"])
            self.assertEqual(expected_times[1], event["end_time"])
            self.assertEqual("墨田区総合体育館", event["venue"])
            self.assertEqual("東京都", event["area"])
            self.assertEqual(
                "東京都墨田区錦糸4-15-1",
                event["address"],
            )
            self.assertEqual(
                "JR錦糸町駅北口から徒歩約5分／"
                "東京メトロ半蔵門線錦糸町駅3・4番出口から徒歩約5分",
                event["access"],
            )
            self.assertIsNone(event["fee"])
            self.assertFalse(event["application_required"])
            self.assertEqual(
                "contact_required",
                event["participation_type"],
            )
            self.assertEqual("open_keiko", event["event_type"])
            self.assertEqual("sns", event["source_type"])
            self.assertEqual("manual", event["update_mode"])
            self.assertEqual("active", event["status"])
            expected_review_due_at = (
                date.fromisoformat(event["event_date"]) - timedelta(days=1)
            ).isoformat()
            self.assertEqual(expected_review_due_at, event["review_due_at"])
            self.assertIn("アテンド", event["raw_note"])


    def test_kent_ladies_event_is_valid(self) -> None:
        events = [
            event
            for event in load_manual_events()
            if event["organization_id"] == "kent_ladies"
        ]

        self.assertEqual(2, len(events))
        self.assertEqual(
            ["2026-08-30", "2026-09-12"],
            [event["event_date"] for event in events],
        )

        august_event = events[0]
        self.assertEqual("日", august_event["weekday"])
        self.assertEqual(
            "kent女子稽古会 8月30日稽古",
            august_event["title"],
        )
        self.assertEqual("12:30", august_event["start_time"])
        self.assertEqual("15:00", august_event["end_time"])
        self.assertEqual(
            "文京スポーツセンター4階",
            august_event["venue"],
        )
        self.assertEqual("500円", august_event["fee"])
        self.assertEqual("anyone", august_event["participation_type"])
        self.assertFalse(august_event["application_required"])
        self.assertEqual("manual", august_event["update_mode"])
        self.assertEqual("sns", august_event["source_type"])
        self.assertEqual(
            "https://www.instagram.com/p/DaW0XADE927/",
            august_event["source_url"],
        )

        september_event = events[1]
        self.assertEqual(
            "kent_ladies-20260912-1230-8547d672",
            september_event["event_id"],
        )
        self.assertEqual("kent女子稽古会", september_event["organization_name"])
        self.assertEqual("土", september_event["weekday"])
        self.assertEqual(
            "kent女子稽古会 9月12日稽古",
            september_event["title"],
        )
        self.assertEqual("12:30", september_event["start_time"])
        self.assertEqual("15:00", september_event["end_time"])
        self.assertEqual(
            "文京スポーツセンター4階",
            september_event["venue"],
        )
        self.assertEqual("東京都", september_event["area"])
        self.assertIsNone(september_event["address"])
        self.assertIsNone(september_event["access"])
        self.assertEqual("500円", september_event["fee"])
        self.assertEqual(
            "contact_required",
            september_event["participation_type"],
        )
        self.assertFalse(september_event["application_required"])
        self.assertEqual("manual", september_event["update_mode"])
        self.assertEqual("sns", september_event["source_type"])
        self.assertEqual(
            "https://www.instagram.com/p/DcxTARJk4ur/",
            september_event["source_url"],
        )
        self.assertEqual("2026-09-11", september_event["review_due_at"])
        self.assertIn("成人女性対象", september_event["raw_note"])
        self.assertIn("高校生以下は保護者同伴", september_event["raw_note"])
        self.assertIn("DMまたはオープンチャット", september_event["raw_note"])


    def test_kendo_jo_tateyo_event_is_valid_and_linked_to_organization(
        self,
    ) -> None:
        organizations = load_organizations()
        organization = find_organization(
            organizations,
            "kendo_jo_tateyo",
        )
        events = [
            event
            for event in load_manual_events()
            if event["organization_id"] == "kendo_jo_tateyo"
        ]

        self.assertEqual("ケンドウジョウタテヨ", organization.name)
        self.assertEqual("千葉県", organization.area)
        self.assertEqual(
            "https://www.instagram.com/kendo_jo_tateyo/",
            organization.website_url,
        )
        self.assertEqual("sns", organization.source_type)
        self.assertEqual("manual", organization.scraper_type)
        self.assertFalse(organization.scraper_enabled)
        self.assertEqual("open_keiko", organization.event_type)
        self.assertEqual(1, len(events))

        event = events[0]
        self.assertEqual(
            "kendo_jo_tateyo-20260923-1300-d41ad868",
            event["event_id"],
        )
        self.assertEqual("ケンドウジョウタテヨ", event["organization_name"])
        self.assertEqual("リバ剣女子稽古会", event["title"])
        self.assertEqual("2026-09-23", event["event_date"])
        self.assertEqual("水", event["weekday"])
        self.assertEqual("13:00", event["start_time"])
        self.assertEqual("15:00", event["end_time"])
        self.assertEqual("YohaSアリーナ1F剣道場", event["venue"])
        self.assertEqual("千葉県", event["area"])
        self.assertIsNone(event["address"])
        self.assertIsNone(event["access"])
        self.assertEqual("500円", event["fee"])
        self.assertTrue(event["application_required"])
        self.assertEqual(
            "registration_required",
            event["participation_type"],
        )
        self.assertEqual("open_keiko", event["event_type"])
        self.assertEqual("sns", event["source_type"])
        self.assertEqual("manual", event["update_mode"])
        self.assertEqual("active", event["status"])
        self.assertEqual(
            "https://www.instagram.com/kendo_jo_tateyo/p/DcpPKvKywS4/",
            event["source_url"],
        )
        self.assertEqual("2026-09-22", event["review_due_at"])
        self.assertIn("成人女性限定", event["raw_note"])
        self.assertIn("申込は公式投稿のQRから", event["raw_note"])

        index_html = (
            Path(__file__).resolve().parents[1] / "public" / "index.html"
        ).read_text(encoding="utf-8")
        self.assertIn("<h3>ケンドウジョウタテヨ</h3>", index_html)


    def test_kendo_labo_event_is_valid_and_linked_to_organization(
        self,
    ) -> None:
        organizations = load_organizations()
        organization = find_organization(organizations, "kendo_labo")
        events = [
            event
            for event in load_manual_events()
            if event["organization_id"] == "kendo_labo"
        ]

        self.assertEqual("剣道LABO", organization.name)
        self.assertEqual("東京都", organization.area)
        self.assertEqual(
            "https://www.instagram.com/kendo_labo/",
            organization.website_url,
        )
        self.assertEqual("sns", organization.source_type)
        self.assertEqual("manual", organization.scraper_type)
        self.assertFalse(organization.scraper_enabled)
        self.assertEqual("open_keiko", organization.event_type)
        self.assertEqual(1, len(events))

        event = events[0]
        self.assertEqual(
            "kendo_labo-20260919-1540-4701fc9e",
            event["event_id"],
        )
        self.assertEqual("剣道LABO", event["organization_name"])
        self.assertEqual("剣道LABO 稽古会", event["title"])
        self.assertEqual("2026-09-19", event["event_date"])
        self.assertEqual("土", event["weekday"])
        self.assertEqual("15:40", event["start_time"])
        self.assertEqual("18:40", event["end_time"])
        self.assertEqual(
            "新宿コズミックセンター剣道場",
            event["venue"],
        )
        self.assertEqual("東京都", event["area"])
        self.assertIsNone(event["address"])
        self.assertIsNone(event["access"])
        self.assertEqual("各回1,000円", event["fee"])
        self.assertTrue(event["application_required"])
        self.assertEqual(
            "registration_required",
            event["participation_type"],
        )
        self.assertEqual("sns", event["source_type"])
        self.assertEqual("manual", event["update_mode"])
        self.assertEqual("active", event["status"])
        self.assertEqual(
            "https://www.instagram.com/p/DczRzpKTat0/",
            event["source_url"],
        )
        self.assertEqual("2026-09-18", event["review_due_at"])
        self.assertIn("社会人対象", event["raw_note"])
        self.assertIn("定員15名程度", event["raw_note"])
        self.assertIn("事前申込必須", event["raw_note"])

        index_html = (
            Path(__file__).resolve().parents[1] / "public" / "index.html"
        ).read_text(encoding="utf-8")
        self.assertIn("<h3>剣道LABO</h3>", index_html)


    def test_kizunakai_events_are_valid(self) -> None:
        events = [
            event
            for event in load_manual_events()
            if event["organization_id"] == "kizunakai"
        ]

        self.assertEqual(2, len(events))

        events_by_date = {
            event["event_date"]: event
            for event in events
        }

        self.assertEqual(
            {"2026-08-14", "2026-08-27"},
            set(events_by_date),
        )

        event = events_by_date["2026-08-14"]

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

        event = events_by_date["2026-08-27"]

        self.assertEqual("木", event["weekday"])
        self.assertEqual("絆剱会 ゆる稽古会", event["title"])
        self.assertEqual("20:00", event["start_time"])
        self.assertEqual("22:00", event["end_time"])
        self.assertEqual(
            "坂戸市 入西地域交流センター 多目的ホール",
            event["venue"],
        )
        self.assertIsNone(event["address"])
        self.assertIsNone(event["access"])
        self.assertEqual(
            "一般200円／大学生以下100円",
            event["fee"],
        )
        self.assertEqual("anyone", event["participation_type"])
        self.assertFalse(event["application_required"])
        self.assertEqual("manual", event["update_mode"])
        self.assertEqual("sns", event["source_type"])
        self.assertEqual(
            "https://www.instagram.com/p/DcXxOuzN1ne/",
            event["source_url"],
        )


    def test_gozen_kendo_event_is_valid_and_linked_to_organization(self) -> None:
        organizations = load_organizations()
        organization = find_organization(organizations, "gozen_kendo")
        events = [
            event
            for event in load_manual_events()
            if event["organization_id"] == "gozen_kendo"
        ]

        self.assertEqual("悟禅会", organization.name)
        self.assertEqual("manual", organization.scraper_type)
        self.assertFalse(organization.scraper_enabled)
        self.assertEqual(
            "contact_required",
            organization.default_participation_type,
        )
        self.assertFalse(organization.default_application_required)
        self.assertEqual(7, len(events))
        events_by_date = {
            event["event_date"]: event
            for event in events
        }

        event = events_by_date["2026-08-27"]

        self.assertEqual(
            "gozen_kendo-20260827-0930-541f23f2",
            event["event_id"],
        )
        self.assertEqual("悟禅会 稽古会", event["title"])
        self.assertEqual("2026-08-27", event["event_date"])
        self.assertEqual("木", event["weekday"])
        self.assertEqual("09:30", event["start_time"])
        self.assertEqual("11:30", event["end_time"])
        self.assertEqual(
            "新宿区スポーツセンター 4F",
            event["venue"],
        )
        self.assertIsNone(event["address"])
        self.assertIsNone(event["access"])
        self.assertIsNone(event["fee"])
        self.assertFalse(event["application_required"])
        self.assertEqual("contact_required", event["participation_type"])
        self.assertEqual("manual", event["update_mode"])
        self.assertEqual("sns", event["source_type"])
        self.assertEqual(
            "https://www.instagram.com/p/DbhdpUxPJdF/",
            event["source_url"],
        )

        expected_schedules = {
            "2026-09-02": (
                "10:00",
                "12:00",
                "神奈川県立武道館",
                "神奈川県",
                "当日の人数次第",
                "2026-09-01",
                "貸切利用",
            ),
            "2026-09-03": (
                "09:30",
                "11:30",
                "新宿区スポーツセンター 4F",
                "東京都",
                "400円",
                "2026-09-02",
                "個人利用枠",
            ),
            "2026-09-10": (
                "09:30",
                "11:30",
                "新宿区スポーツセンター 4F",
                "東京都",
                "400円",
                "2026-09-09",
                "個人利用枠",
            ),
            "2026-09-17": (
                "09:30",
                "11:30",
                "新宿区スポーツセンター 4F",
                "東京都",
                "400円",
                "2026-09-16",
                "個人利用枠",
            ),
            "2026-09-24": (
                "09:30",
                "11:30",
                "新宿区スポーツセンター 4F",
                "東京都",
                "400円",
                "2026-09-23",
                "個人利用枠",
            ),
            "2026-09-30": (
                "10:00",
                "12:00",
                "神奈川県立武道館",
                "神奈川県",
                "当日の人数次第",
                "2026-09-29",
                "貸切利用",
            ),
        }

        for event_date, expected in expected_schedules.items():
            start, end, venue, area, fee, review_due, usage = expected
            event = events_by_date[event_date]
            self.assertEqual("悟禅会", event["organization_name"])
            self.assertEqual("悟禅会 稽古会", event["title"])
            self.assertEqual(start, event["start_time"])
            self.assertEqual(end, event["end_time"])
            self.assertEqual(venue, event["venue"])
            self.assertEqual(area, event["area"])
            self.assertIsNone(event["address"])
            self.assertIsNone(event["access"])
            self.assertEqual(fee, event["fee"])
            self.assertFalse(event["application_required"])
            self.assertEqual(
                "contact_required",
                event["participation_type"],
            )
            self.assertEqual("manual", event["update_mode"])
            self.assertEqual("sns", event["source_type"])
            self.assertEqual(
                "https://www.instagram.com/p/Dcpr13AvgrP/",
                event["source_url"],
            )
            self.assertEqual(review_due, event["review_due_at"])
            self.assertIn("訂正版", event["raw_note"])
            self.assertIn(usage, event["raw_note"])
            self.assertIn("荒天時", event["raw_note"])
            self.assertIn("追加・変更", event["raw_note"])


    def test_iwaki_kamomekai_event_is_valid_and_linked_to_organization(
        self,
    ) -> None:
        organizations = load_organizations()
        organization = find_organization(
            organizations,
            "iwaki_kamomekai",
        )
        events = [
            event
            for event in load_manual_events()
            if event["organization_id"] == "iwaki_kamomekai"
        ]

        self.assertEqual("磐城鷗会", organization.name)
        self.assertEqual("福島県", organization.area)
        self.assertEqual(
            "https://www.instagram.com/kendo_kamomekai/",
            organization.website_url,
        )
        self.assertEqual("sns", organization.source_type)
        self.assertEqual("manual", organization.scraper_type)
        self.assertFalse(organization.scraper_enabled)
        self.assertEqual("open_keiko", organization.event_type)
        self.assertEqual(
            "anyone",
            organization.default_participation_type,
        )
        self.assertFalse(organization.default_application_required)
        self.assertEqual(2, len(events))
        events_by_date = {
            event["event_date"]: event
            for event in events
        }

        event = events_by_date["2026-08-29"]

        self.assertEqual(
            "iwaki_kamomekai-20260829-1700-a2701080",
            event["event_id"],
        )
        self.assertEqual("磐城鷗会", event["organization_name"])
        self.assertEqual("磐城鷗会 稽古", event["title"])
        self.assertEqual("2026-08-29", event["event_date"])
        self.assertEqual("土", event["weekday"])
        self.assertEqual("17:00", event["start_time"])
        self.assertEqual("19:00", event["end_time"])
        self.assertEqual("いわき市役所総合体育館", event["venue"])
        self.assertEqual("福島県", event["area"])
        self.assertIsNone(event["address"])
        self.assertIsNone(event["access"])
        self.assertEqual(
            "体育館の場所代等を人数で均等割り（300円前後）",
            event["fee"],
        )
        self.assertFalse(event["application_required"])
        self.assertEqual("anyone", event["participation_type"])
        self.assertEqual("manual", event["update_mode"])
        self.assertEqual("sns", event["source_type"])
        self.assertEqual(
            "https://www.instagram.com/hitachi657/",
            event["source_url"],
        )
        self.assertEqual("2026-08-28", event["review_due_at"])

        event = events_by_date["2026-09-05"]

        self.assertEqual(
            "iwaki_kamomekai-20260905-1700-62f35cc7",
            event["event_id"],
        )
        self.assertEqual("磐城鷗会", event["organization_name"])
        self.assertEqual("磐城鷗会 稽古", event["title"])
        self.assertEqual("土", event["weekday"])
        self.assertEqual("17:00", event["start_time"])
        self.assertIsNone(event["end_time"])
        self.assertEqual("いわき市総合体育館", event["venue"])
        self.assertEqual("福島県", event["area"])
        self.assertIsNone(event["address"])
        self.assertIsNone(event["access"])
        self.assertEqual(
            "体育館の場所代等を人数で均等割り（300円前後）",
            event["fee"],
        )
        self.assertFalse(event["application_required"])
        self.assertEqual("anyone", event["participation_type"])
        self.assertEqual("manual", event["update_mode"])
        self.assertEqual("sns", event["source_type"])
        self.assertEqual(
            "https://www.instagram.com/hitachi657/",
            event["source_url"],
        )
        self.assertEqual("2026-09-04", event["review_due_at"])
        self.assertIn("主催者本人のInstagram DM", event["raw_note"])

        index_html = (
            Path(__file__).resolve().parents[1] / "public" / "index.html"
        ).read_text(encoding="utf-8")
        self.assertIn("<h3>磐城鷗会</h3>", index_html)
        self.assertIn("磐城鷗会が月1〜2回程度", index_html)


    def test_seikenkai_inzai_events_are_valid(self) -> None:
        events = [
            event
            for event in load_manual_events()
            if event["organization_id"] == "seikenkai_inzai"
        ]

        self.assertEqual(6, len(events))
        self.assertEqual(
            [
                "2026-08-21",
                "2026-08-28",
                "2026-09-04",
                "2026-09-11",
                "2026-09-18",
                "2026-09-25",
            ],
            [event["event_date"] for event in events],
        )

        for event in events:
            self.assertEqual(
                (
                    "西劔会 8月オープン稽古会"
                    if event["event_date"].startswith("2026-08")
                    else "西劔会 9月オープン稽古会"
                ),
                event["title"],
            )
            self.assertEqual("西劔会", event["organization_name"])
            self.assertEqual("19:00", event["start_time"])
            self.assertEqual("21:00", event["end_time"])
            self.assertEqual(
                "印西市立西の原中学校",
                event["venue"],
            )
            self.assertEqual("無料", event["fee"])
            self.assertIsNone(event["address"])
            self.assertIsNone(event["access"])
            self.assertEqual("anyone", event["participation_type"])
            self.assertFalse(event["application_required"])
            self.assertEqual("manual", event["update_mode"])
            self.assertEqual("sns", event["source_type"])
            self.assertEqual(
                (
                    "https://www.instagram.com/p/DbeucGlzVHK/"
                    if event["event_date"].startswith("2026-08")
                    else "https://www.instagram.com/p/Dcn1pAlh1Yb/"
                ),
                event["source_url"],
            )

        september_events = [
            event
            for event in events
            if event["event_date"].startswith("2026-09")
        ]
        self.assertEqual(
            ["2026-09-03", "2026-09-10", "2026-09-17", "2026-09-24"],
            [event["review_due_at"] for event in september_events],
        )
        for event in september_events:
            self.assertIn("事前申込は任意・会費なし", event["raw_note"])
            self.assertIn(
                "面をつけて稽古できる方であれば、"
                "小学生から大人まで参加可能",
                event["raw_note"],
            )


if __name__ == "__main__":
    unittest.main()
