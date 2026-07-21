from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path

from kendo_keiko.static_site import (
    build_sitemap_xml,
    render_static_index,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT_DIR / "public" / "index.html"


class StaticSiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.template = INDEX_PATH.read_text(encoding="utf-8")
        self.payload = {
            "generated_at": "2026-07-21T10:30:00+09:00",
            "events": [
                {
                    "event_id": "event-2",
                    "organization_id": "org-b",
                    "organization_name": "B団体",
                    "title": "通常稽古",
                    "event_date": "2026-08-02",
                    "weekday": "日",
                    "start_time": None,
                    "end_time": None,
                    "venue": None,
                    "area": None,
                    "source_url": "javascript:alert(1)",
                },
                {
                    "event_id": "event-1",
                    "organization_id": "org-a",
                    "organization_name": "A団体<script>",
                    "title": "合同稽古 & 交流会",
                    "event_date": "2026-08-01",
                    "weekday": "土",
                    "start_time": "09:00",
                    "end_time": "11:00",
                    "venue": "武道館 <大> ",
                    "area": "東京都",
                    "access": "駅から5分",
                    "fee": "500円",
                    "source_url": "https://example.com/event?id=1&lang=ja",
                },
            ],
        }

    def test_renders_sorted_static_event_cards(self) -> None:
        rendered = render_static_index(self.template, self.payload)

        first = rendered.index("2026-08-01(土)")
        second = rendered.index("2026-08-02(日)")
        self.assertLess(first, second)
        self.assertIn("掲載件数: 2件", rendered)
        self.assertIn("2件掲載中", rendered)
        self.assertIn("A団体&lt;script&gt;", rendered)
        self.assertIn("合同稽古 &amp; 交流会", rendered)
        self.assertIn("武道館 &lt;大&gt;", rendered)
        self.assertIn(
            'href="https://example.com/event?id=1&amp;lang=ja"',
            rendered,
        )
        self.assertNotIn("javascript:alert(1)", rendered)

    def test_rendering_is_idempotent(self) -> None:
        once = render_static_index(self.template, self.payload)
        twice = render_static_index(once, self.payload)
        self.assertEqual(once, twice)

    def test_renders_empty_state(self) -> None:
        rendered = render_static_index(
            self.template,
            {"generated_at": "2026-07-21T10:30:00+09:00", "events": []},
        )
        self.assertIn("掲載件数: 0件", rendered)
        self.assertIn("現在掲載中の稽古会はありません。", rendered)

    def test_rejects_invalid_events_shape(self) -> None:
        with self.assertRaises(ValueError):
            render_static_index(self.template, {"events": {}})

    def test_builds_sitemap_with_lastmod(self) -> None:
        sitemap = build_sitemap_xml(
            site_url="https://kendo-keiko.com/",
            lastmod=dt.date(2026, 7, 21),
        )
        self.assertIn("<loc>https://kendo-keiko.com/</loc>", sitemap)
        self.assertIn("<lastmod>2026-07-21</lastmod>", sitemap)


if __name__ == "__main__":
    unittest.main()
