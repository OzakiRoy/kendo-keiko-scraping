import unittest

from kendo_keiko.scrapers.kenbokukai import (
    parse_kenbokukai_events_from_text,
)
from scrape_kendo_schedule import dedupe_events


class KenbokukaiParserTests(unittest.TestCase):
    def test_parses_event_details(self) -> None:
        text = """
第51回 剣道練習会
■ 日付：2026年8月8日 (土)
■ 時間：13:00~17:00
■ 場所：江戸川区スポーツセンター1階〖最寄り駅：西葛西駅〗
■ 参加費：20代以下 500円 ／ 30代以上 1,000円
"""

        events = parse_kenbokukai_events_from_text(
            group="剣睦会",
            event_type="open_keiko",
            text=text,
            source_url="https://kenbokukai.com/archives/1193",
        )

        self.assertEqual(1, len(events))

        event = events[0]

        self.assertEqual("2026-08-08", event.date)
        self.assertEqual("13:00", event.start_time)
        self.assertEqual("17:00", event.end_time)
        self.assertEqual(
            "江戸川区スポーツセンター1階",
            event.venue,
        )
        self.assertEqual(
            "最寄り駅：西葛西駅",
            event.access,
        )
        self.assertIn(
            "20代以下 500円",
            event.note or "",
        )

    def test_preserves_japanese_long_vowel_marks(self) -> None:
        text = """
第52回 剣道練習会
■ 日付：2026年8月30日 (日)
■ 時間：13:00ー17:00
■ 場所：江戸川区スポーツセンター1階
"""

        events = parse_kenbokukai_events_from_text(
            group="剣睦会",
            event_type="open_keiko",
            text=text,
            source_url="https://kenbokukai.com/archives/1193",
        )

        self.assertEqual(1, len(events))
        self.assertEqual(
            "江戸川区スポーツセンター1階",
            events[0].venue,
        )
        self.assertNotIn("-", events[0].venue or "")

    def test_dedupes_same_event_from_multiple_sources(self) -> None:
        text = """
第51回 剣道練習会
■ 日付：2026年8月8日 (土)
■ 時間：13:00~17:00
■ 場所：江戸川区スポーツセンター1階〖最寄り駅：西葛西駅〗
■ 参加費：500円
"""

        archive_events = parse_kenbokukai_events_from_text(
            group="剣睦会",
            event_type="open_keiko",
            text=text,
            source_url="https://kenbokukai.com/archives/1193",
        )

        category_events = parse_kenbokukai_events_from_text(
            group="剣睦会",
            event_type="open_keiko",
            text=text,
            source_url=(
                "https://kenbokukai.com/"
                "archives/category/info"
            ),
        )

        result = dedupe_events(
            archive_events + category_events
        )

        self.assertEqual(1, len(result))
        self.assertEqual(
            "2026-08-08",
            result[0].date,
        )
        self.assertEqual(
            "江戸川区スポーツセンター1階",
            result[0].venue,
        )


if __name__ == "__main__":
    unittest.main()
