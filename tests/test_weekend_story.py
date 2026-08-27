from __future__ import annotations

import copy
import datetime as dt
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

from kendo_keiko.weekend_story import (
    DEFAULT_ICON_PATH,
    DEFAULT_FONT_PATH,
    EXPECTED_SCHEMA_VERSION,
    ACCENT,
    ACCENT_SOFT,
    LayoutOverflowError,
    NoEventsError,
    StoryError,
    event_for_story,
    fetch_events_payload,
    layout_event,
    load_events_file,
    load_font,
    output_paths,
    paginate_layouts,
    parse_target_saturday,
    render_story_pages,
    save_story_pages,
    select_weekend_events,
)
from scripts import generate_weekend_story


ROOT_DIR = Path(__file__).resolve().parents[1]
FIXTURE = ROOT_DIR / "tests" / "fixtures" / "weekend_story_events.json"


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise AssertionError(f"not a PNG: {path}")
    return struct.unpack(">II", data[16:24])


class WeekendStoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = load_events_file(FIXTURE)
        self.saturday = dt.date(2026, 8, 29)

    def test_requires_saturday(self) -> None:
        self.assertEqual(self.saturday, parse_target_saturday("2026-08-29"))
        with self.assertRaisesRegex(StoryError, "Saturday"):
            parse_target_saturday("2026-08-30")

    def test_selects_only_saturday_and_sunday_in_stable_order(self) -> None:
        selected = select_weekend_events(self.payload, self.saturday)
        expected = [
            "saturday-anyone",
            "saturday-contact",
            "saturday-registration",
            "sunday-contact-application",
            "sunday-invitation",
            "sunday-unknown",
            "sunday-members",
        ]
        self.assertEqual(expected, [event.event_id for event in selected])

        reversed_payload = copy.deepcopy(self.payload)
        reversed_payload["events"].reverse()
        reversed_selected = select_weekend_events(
            reversed_payload, self.saturday
        )
        self.assertEqual(expected, [event.event_id for event in reversed_selected])
        self.assertNotIn(
            "previous-week", [event.event_id for event in selected]
        )
        self.assertNotIn("next-week", [event.event_id for event in selected])

    def test_display_model_preserves_event_strings_without_normalization(self) -> None:
        raw = next(
            event
            for event in self.payload["events"]
            if event["event_id"] == "saturday-contact"
        )
        model = event_for_story(raw)
        self.assertEqual("西劔会", model.organization_name)
        self.assertNotEqual("西剣会", model.organization_name)
        self.assertNotEqual("西劒会", model.organization_name)
        self.assertEqual(raw["title"], model.title)
        self.assertEqual(raw["venue"], model.venue)
        self.assertEqual(raw["fee"], model.fee)
        self.assertIsNone(model.access)

    def test_null_fee_and_access_are_preserved(self) -> None:
        raw = next(
            event
            for event in self.payload["events"]
            if event["event_id"] == "saturday-anyone"
        )
        model = event_for_story(raw)
        self.assertIsNone(model.fee)
        self.assertIsNone(model.access)

    def test_all_participation_types_use_existing_display_rules(self) -> None:
        expected = {
            "anyone": ("一般参加可",),
            "contact_required": ("事前連絡",),
            "registration_required": ("申込必須",),
            "invitation_required": ("招待制",),
            "members_only": ("会員限定",),
            "unknown": ("公式情報を確認",),
        }
        base = {
            "event_id": "event",
            "organization_id": "org",
            "organization_name": "団体",
            "title": "稽古",
            "event_date": "2026-08-29",
            "start_time": "09:00",
            "end_time": "11:00",
            "venue": "会場",
            "area": "東京都",
            "fee": None,
            "access": None,
            "application_required": None,
        }
        for participation_type, labels in expected.items():
            with self.subTest(participation_type=participation_type):
                model = event_for_story(
                    {**base, "participation_type": participation_type}
                )
                self.assertEqual(labels, model.participation_labels)

        application = event_for_story(
            {
                **base,
                "participation_type": "contact_required",
                "application_required": True,
            }
        )
        self.assertEqual(("事前連絡", "申込必須"), application.participation_labels)
        conflict = event_for_story(
            {
                **base,
                "participation_type": "registration_required",
                "application_required": False,
            }
        )
        self.assertEqual(("公式情報を確認",), conflict.participation_labels)

    def test_schema_and_timezone_are_checked_using_actual_keys(self) -> None:
        wrong_schema = copy.deepcopy(self.payload)
        wrong_schema["schema_version"] = "other"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.json"
            path.write_text(json.dumps(wrong_schema), encoding="utf-8")
            with self.assertRaisesRegex(StoryError, "schema_version"):
                load_events_file(path)
        wrong_timezone = copy.deepcopy(self.payload)
        wrong_timezone["timezone"] = "UTC"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.json"
            path.write_text(json.dumps(wrong_timezone), encoding="utf-8")
            with self.assertRaisesRegex(StoryError, "timezone"):
                load_events_file(path)
        self.assertEqual("public-events-0.3", EXPECTED_SCHEMA_VERSION)

    def test_http_loader_uses_the_validated_public_payload_without_network(self) -> None:
        response = Mock()
        response.headers = {"Content-Length": "1024"}
        response.content = json.dumps(self.payload).encode("utf-8")
        response.json.return_value = self.payload
        with patch(
            "kendo_keiko.weekend_story.requests.get", return_value=response
        ) as get:
            loaded = fetch_events_payload("https://example.com/events.json")
        self.assertIs(self.payload, loaded)
        get.assert_called_once_with(
            "https://example.com/events.json", timeout=(5.0, 20.0)
        )
        response.raise_for_status.assert_called_once_with()

    def test_bundled_font_contains_required_variant_characters(self) -> None:
        font = load_font(DEFAULT_FONT_PATH, 64)
        masks = [bytes(font.getmask(character)) for character in ("劔", "剱", "�")]
        self.assertTrue(all(masks))
        self.assertNotEqual(masks[0], masks[2])
        self.assertNotEqual(masks[1], masks[2])

    def test_one_event_renders_one_1080_by_1920_png(self) -> None:
        event = select_weekend_events(self.payload, self.saturday)[0]
        images = render_story_pages([event], self.saturday)
        self.assertEqual(1, len(images))
        with tempfile.TemporaryDirectory() as directory:
            paths = save_story_pages(
                images, Path(directory) / "weekend-story.png"
            )
            self.assertEqual(1, len(paths))
            self.assertEqual((1080, 1920), png_dimensions(paths[0]))

    def test_renderer_uses_the_committed_official_brand_icon(self) -> None:
        self.assertEqual(ROOT_DIR / "public" / "icon-512.png", DEFAULT_ICON_PATH)
        self.assertTrue(DEFAULT_ICON_PATH.is_file())
        event = select_weekend_events(self.payload, self.saturday)[0]
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing-icon.png"
            with self.assertRaisesRegex(StoryError, "official brand icon"):
                render_story_pages([event], self.saturday, icon_path=missing)

    def test_rendered_template_uses_brand_accent_and_badge_colors(self) -> None:
        event = select_weekend_events(self.payload, self.saturday)[0]
        image = render_story_pages([event], self.saturday)[0]
        colors = {color for _, color in image.getcolors(maxcolors=1_000_000) or []}
        self.assertIn(tuple(Image.new("RGB", (1, 1), ACCENT).getpixel((0, 0))), colors)
        self.assertIn(
            tuple(Image.new("RGB", (1, 1), ACCENT_SOFT).getpixel((0, 0))),
            colors,
        )

    def test_multiple_and_more_than_five_events_paginate(self) -> None:
        events = select_weekend_events(self.payload, self.saturday)
        images = render_story_pages(events, self.saturday)
        self.assertGreaterEqual(len(images), 2)
        image = Image.new("RGB", (1080, 1920))
        draw = ImageDraw.Draw(image)
        fonts = {
            "org": load_font(DEFAULT_FONT_PATH, 39, weight=700),
            "title": load_font(DEFAULT_FONT_PATH, 31, weight=600),
            "body": load_font(DEFAULT_FONT_PATH, 27),
            "small": load_font(DEFAULT_FONT_PATH, 24, weight=500),
        }
        pages = paginate_layouts(
            layout_event(draw, event, fonts) for event in events
        )
        self.assertEqual([3, 2, 2], [len(page) for page in pages])
        self.assertTrue(all(len(page) <= 5 for page in pages))
        self.assertEqual(
            [
                Path("output/weekend-story-01.png"),
                Path("output/weekend-story-02.png"),
            ],
            output_paths(Path("output/weekend-story.png"), 2),
        )

    def test_long_names_wrap_without_changing_source_strings(self) -> None:
        raw = copy.deepcopy(self.payload["events"][0])
        raw.update(
            {
                "event_id": "long-event",
                "event_date": "2026-08-29",
                "organization_name": "非常に長い団体名" * 8,
                "venue": "非常に長い会場名" * 10,
                "area": "非常に長い地域名" * 4,
                "access": "非常に長いアクセス案内" * 6,
            }
        )
        event = event_for_story(raw)
        image = Image.new("RGB", (1080, 1920))
        draw = ImageDraw.Draw(image)
        fonts = {
            "org": load_font(DEFAULT_FONT_PATH, 39, weight=700),
            "title": load_font(DEFAULT_FONT_PATH, 31, weight=600),
            "body": load_font(DEFAULT_FONT_PATH, 27),
            "small": load_font(DEFAULT_FONT_PATH, 24, weight=500),
        }
        layout = layout_event(draw, event, fonts)
        self.assertEqual(event.organization_name, "".join(layout.organization_lines))
        self.assertEqual(event.venue, "".join(layout.venue_lines))
        self.assertEqual(event.area, "".join(layout.area_lines))
        self.assertEqual(event.access, "".join(layout.access_lines))

    def test_overflow_raises_instead_of_dropping_text(self) -> None:
        raw = copy.deepcopy(self.payload["events"][0])
        raw.update(
            {
                "event_id": "overflow-event",
                "event_date": "2026-08-29",
                "organization_name": "長い団体名" * 400,
            }
        )
        with self.assertRaisesRegex(LayoutOverflowError, "overflow-event"):
            render_story_pages([event_for_story(raw)], self.saturday)

    def test_no_events_returns_distinct_exit_code_and_creates_no_image(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "story.png"
            code = generate_weekend_story.main(
                [
                    "--date",
                    "2026-09-12",
                    "--events-file",
                    str(FIXTURE),
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(generate_weekend_story.NO_EVENTS_EXIT_CODE, code)
            self.assertFalse(output.exists())
        with self.assertRaises(NoEventsError):
            render_story_pages([], self.saturday)

    def test_fixture_cli_does_not_use_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "kendo_keiko.weekend_story.requests.get"
        ) as get:
            code = generate_weekend_story.main(
                [
                    "--date",
                    "2026-08-29",
                    "--events-file",
                    str(FIXTURE),
                    "--output",
                    str(Path(directory) / "weekend-story.png"),
                ]
            )
            self.assertEqual(0, code)
            get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
