import datetime as dt
import unittest

from scrape_kendo_schedule import (
    KeikoEvent,
    dedupe_events,
    html_to_text,
    parse_events_from_text,
)


class HtmlToTextTests(unittest.TestCase):
    def test_preserves_japanese_long_vowel_mark(self) -> None:
        text = html_to_text(
            "<p>江戸川区スポーツセンター</p>"
            "<p>7月18日（土）15:30ー18:00</p>"
        )

        self.assertIn("スポーツセンター", text)
        self.assertNotIn("スポ-ツセンタ-", text)


class ParseEventsFromTextTests(unittest.TestCase):
    def test_kent_parses_separate_venue_line(self) -> None:
        text = """
        2026年7月
        『第285回剣道練習会』
        日時：7月18日（土）15:30~18:00
        会場：
        文京スポーツセンター
        『第286回剣道練習会』
        日時：7月19日（日）15:00~18:00
        会場：池袋スポーツセンター
        """

        events = parse_events_from_text(
            group="kent",
            event_type="open_practice",
            text=text,
            source_url="https://kendonetwork.com/",
            base_date=dt.date(2026, 7, 1),
        )

        self.assertEqual(2, len(events))
        self.assertEqual("文京スポーツセンター", events[0].venue)
        self.assertEqual("池袋スポーツセンター", events[1].venue)

    def test_does_not_take_venue_from_next_date_without_time(self) -> None:
        text = """
        2026年9月
        9/23(日)12:30~15:00
        @文京区スポーツセンター
        （茗荷谷駅 徒歩3分）
        9/26(土)&9/27(日)
        kentグループ 合同合宿
        @山梨県 河口湖
        """

        events = parse_events_from_text(
            group="kenkyukai",
            event_type="open_practice",
            text=text,
            source_url="https://kenkyukai-kendo.com/archives/example",
            base_date=dt.date(2026, 9, 1),
        )

        self.assertEqual(1, len(events))
        self.assertEqual("文京区スポーツセンター", events[0].venue)
        self.assertEqual("茗荷谷駅 徒歩3分", events[0].access)


class DedupeEventsTests(unittest.TestCase):
    def test_dedupes_same_datetime_when_titles_differ(self) -> None:
        sparse = KeikoEvent(
            group="kenkyukai",
            event_type="open_practice",
            title="7月＆8月稽古情報",
            date="2026-08-23",
            weekday="日",
            start_time="12:30",
            end_time="15:00",
            venue=None,
            access=None,
            note=None,
            source_url="https://kenkyukai-kendo.com/archives/old",
        )

        detailed = KeikoEvent(
            group="kenkyukai",
            event_type="open_practice",
            title="2026年8月&9月稽古情報",
            date="2026-08-23",
            weekday="日",
            start_time="12:30",
            end_time="15:00",
            venue="文京区スポーツセンター",
            access="茗荷谷駅 徒歩3分",
            note=None,
            source_url="https://kenkyukai-kendo.com/archives/new",
        )

        result = dedupe_events([sparse, detailed])

        self.assertEqual(1, len(result))
        self.assertEqual("文京区スポーツセンター", result[0].venue)
        self.assertEqual("2026年8月&9月稽古情報", result[0].title)


if __name__ == "__main__":
    unittest.main()
