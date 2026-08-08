from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path

from kendo_keiko.static_site import (
    PARTICIPATION_LABELS,
    build_sitemap_xml,
    render_event_card,
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
        self.assertIn("剣道稽古ナビ", rendered)
        self.assertIn("https://kendo-keiko.com/ogp.png", rendered)
        self.assertIn('href="/favicon.svg"', rendered)

    def test_renders_all_participation_labels(self) -> None:
        base_event = {
            "event_date": "2026-08-01",
            "organization_name": "テスト団体",
            "application_required": None,
            "update_mode": "automatic",
        }

        for participation_type, label in PARTICIPATION_LABELS.items():
            with self.subTest(participation_type=participation_type):
                card = render_event_card(
                    {
                        **base_event,
                        "participation_type": participation_type,
                    }
                )
                self.assertIn(label, card)
                self.assertIn(
                    f"status-badge--{participation_type}",
                    card,
                )

    def test_reconciles_application_required_with_participation(self) -> None:
        application_required = render_event_card(
            {
                "event_date": "2026-08-01",
                "organization_name": "テスト団体",
                "participation_type": "contact_required",
                "application_required": True,
                "update_mode": "manual",
                "verified_at": "2026-07-20T09:30:00+09:00",
            }
        )
        self.assertIn("事前連絡", application_required)
        self.assertIn("申込必須", application_required)

        conflicting_not_required = render_event_card(
            {
                "event_date": "2026-08-01",
                "organization_name": "テスト団体",
                "participation_type": "registration_required",
                "application_required": False,
                "update_mode": "manual",
                "verified_at": "2026-07-20T09:30:00+09:00",
            }
        )
        self.assertIn("公式情報を確認", conflicting_not_required)
        self.assertNotIn("申込必須", conflicting_not_required)

    def test_renders_verification_and_review_status(self) -> None:
        card = render_event_card(
            {
                "event_date": "2026-08-01",
                "organization_name": "テスト団体",
                "participation_type": "contact_required",
                "application_required": False,
                "update_mode": "manual",
                "verified_at": "2026-07-20T09:30:00+09:00",
                "review_due_at": "2026-07-20",
            },
            reference_date=dt.date(2026, 7, 21),
        )

        self.assertIn("事前連絡", card)
        self.assertIn("最終確認: 2026-07-20", card)
        self.assertIn("確認期限超過", card)

    def test_automatic_event_without_verified_at_is_marked_unverified(
        self,
    ) -> None:
        card = render_event_card(
            {
                "event_date": "2026-08-01",
                "organization_name": "テスト団体",
                "participation_type": "anyone",
                "application_required": False,
                "update_mode": "automatic",
                "verified_at": None,
                "review_due_at": None,
            }
        )

        self.assertIn("自動取得（未確認）", card)
        self.assertNotIn("最終確認:", card)

    def test_client_renderer_contains_same_status_labels(self) -> None:
        for participation_type, label in PARTICIPATION_LABELS.items():
            with self.subTest(participation_type=participation_type):
                self.assertIn(
                    f'{participation_type}: "{label}"',
                    self.template,
                )
        self.assertIn("${eventStatusHtml(event)}", self.template)
        self.assertIn("自動取得（未確認）", self.template)
        self.assertIn("確認期限超過", self.template)
        self.assertIn(
            "参加前には必ず主催者の公式情報をご確認ください",
            self.template,
        )

    def test_filter_controls_and_shortcuts_are_present(self) -> None:
        self.assertIn('id="area"', self.template)
        self.assertIn('id="participation"', self.template)
        self.assertIn('class="form-field date-shortcuts"', self.template)
        self.assertIn('data-date-shortcut="" aria-pressed="true">すべて</button>', self.template)
        self.assertIn('data-date-shortcut="weekend" aria-pressed="false">今週末</button>', self.template)
        self.assertIn('data-date-shortcut="7days" aria-pressed="false">7日以内</button>', self.template)
        self.assertIn('data-date-shortcut="month" aria-pressed="false">今月</button>', self.template)
        self.assertIn('id="filter-summary"', self.template)
        self.assertIn('id="clear-filters"', self.template)

    def test_client_filter_logic_combines_existing_and_new_conditions(self) -> None:
        self.assertIn('if (org && event.organization_name !== org)', self.template)
        self.assertIn('if (area && event.area !== area)', self.template)
        self.assertIn('participationTypesForFilter(event).has(participation)', self.template)
        self.assertIn('matchesDateRange(event, dateRange)', self.template)
        self.assertIn('matchesKeyword(event, keyword)', self.template)
        self.assertIn('function setDateShortcut(shortcut)', self.template)
        self.assertIn('button.setAttribute("aria-pressed", String(selected))', self.template)
        self.assertIn('data-reset-filters', self.template)

    def test_static_render_keeps_filter_controls_and_all_event_cards(self) -> None:
        rendered = render_static_index(self.template, self.payload)

        self.assertIn('id="area"', rendered)
        self.assertIn('id="participation"', rendered)
        self.assertIn('data-date-shortcut="weekend"', rendered)
        self.assertIn('2026-08-01(土)', rendered)
        self.assertIn('2026-08-02(日)', rendered)

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
