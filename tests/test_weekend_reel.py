from __future__ import annotations

import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from kendo_keiko.weekend_reel import (
    InstagramApiClient,
    InstagramApiConfig,
    ReelError,
    ReelStateStore,
    ReelUnknownResult,
    caption_for_reel,
    generate_reel_assets,
    parse_target_friday,
    render_reel_frames,
    resolve_schedule,
    run_key,
    select_reel_events,
    target_dates,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
FIXTURE = ROOT_DIR / "tests" / "fixtures" / "weekend_reel_events.json"


class FakeResponse:
    def __init__(self, data: dict, status_code: int = 200) -> None:
        self.data = data
        self.status_code = status_code

    def json(self) -> dict:
        return self.data


class FakeSession:
    def __init__(self, *, publish_error: bool = False) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.publish_error = publish_error

    def request(self, method: str, url: str, *, params: dict, timeout: tuple[float, float]):
        self.calls.append((method, url, params))
        if url.endswith("/ig-user"):
            return FakeResponse({"id": "ig-user", "username": "kendo_keiko", "account_type": "BUSINESS"})
        if url.endswith("/ig-user/media"):
            return FakeResponse({"id": "container-1"})
        if url.endswith("/container-1"):
            return FakeResponse({"status_code": "FINISHED", "status": "ready"})
        if url.endswith("/ig-user/media_publish"):
            if self.publish_error:
                raise OSError("connection lost")
            return FakeResponse({"id": "media-1"})
        if url.endswith("/media-1"):
            return FakeResponse({"id": "media-1", "permalink": "https://instagram.example/reel/1"})
        raise AssertionError(url)


class WeekendReelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.friday = dt.date(2026, 10, 9)

    def test_schedule_is_jst_wednesday_thursday_and_explicit(self) -> None:
        tz = dt.timezone(dt.timedelta(hours=9))
        self.assertEqual(dt.date(2026, 10, 9), resolve_schedule(now=dt.datetime(2026, 10, 7, 18, tzinfo=tz)).target_friday)
        self.assertEqual("delayed", resolve_schedule(now=dt.datetime(2026, 10, 8, 18, tzinfo=tz)).status)
        self.assertEqual("skipped_late", resolve_schedule(now=dt.datetime(2026, 10, 9, 18, tzinfo=tz)).status)
        self.assertEqual("skipped_early", resolve_schedule(now=dt.datetime(2026, 10, 6, 18, tzinfo=tz)).status)
        self.assertEqual(dt.date(2027, 1, 1), parse_target_friday("2027-01-01"))
        self.assertEqual((dt.date(2027, 1, 1), dt.date(2027, 1, 2), dt.date(2027, 1, 3)), target_dates(dt.date(2027, 1, 1)))
        with self.assertRaisesRegex(ReelError, "Friday"):
            parse_target_friday("2026-10-10")

    def test_selects_friday_saturday_sunday_and_records_exclusions(self) -> None:
        selection = select_reel_events(self.payload, self.friday)
        self.assertEqual(
            ["reel-friday-open", "reel-friday-match", "reel-saturday-federation"],
            [event.event_id for event in selection.events],
        )
        reasons = {item["event_id"]: item["reason"] for item in selection.excluded}
        self.assertIn("status=cancelled", reasons["reel-saturday-cancelled"])
        self.assertIn("missing=venue", reasons["reel-sunday-missing"])
        self.assertIn("event_type is not publishable", reasons["reel-sunday-unknown-type"])
        self.assertEqual("大人向け錬成会・練習試合", selection.events[1].category_label)
        self.assertEqual("稽古会", selection.events[2].category_label)

    def test_region_filter_and_invalid_schema(self) -> None:
        selection = select_reel_events(self.payload, self.friday, areas=["千葉県"])
        self.assertEqual(["reel-friday-match"], [event.event_id for event in selection.events])
        bad = copy.deepcopy(self.payload)
        bad["timezone"] = "UTC"
        with self.assertRaisesRegex(ReelError, "timezone"):
            select_reel_events(bad, self.friday)
        bad = copy.deepcopy(self.payload)
        bad["events"][0]["event_date"] = "not-a-date"
        with self.assertRaisesRegex(ReelError, "event_date"):
            select_reel_events(bad, self.friday)

    def test_caption_and_video_assets_are_valid(self) -> None:
        selection = select_reel_events(self.payload, self.friday)
        caption = caption_for_reel(selection)
        self.assertIn("10月9日（金）〜10月11日（日）", caption)
        self.assertIn("大人向け錬成会・練習試合", caption)
        self.assertIn("申込必須", caption)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            assets = generate_reel_assets(
                selection,
                input_sha256="a" * 64,
                output_dir=output,
                generated_at="2026-10-07T18:00:00+09:00",
            )
            with Image.open(assets.cover_path) as cover:
                self.assertEqual((1080, 1920), cover.size)
            self.assertTrue(assets.video_path.is_file())
            self.assertEqual(1080, assets.probe.width)
            self.assertEqual(1920, assets.probe.height)
            self.assertEqual("h264", assets.probe.video_codec)
            self.assertEqual("aac", assets.probe.audio_codec)
            manifest = json.loads(assets.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("a" * 64, manifest["input"]["sha256"])
            self.assertEqual(3, len(manifest["events"]))

    def test_state_store_records_run_and_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ReelStateStore(Path(directory))
            key = run_key("ig-user", self.friday)
            with store.lock():
                store.record(key, {"status": "published", "media_id": "media-1"})
            self.assertEqual("published", store.get(key)["status"])
            self.assertIn("media-1", Path(directory, "history.jsonl").read_text())

    def test_api_verifies_destination_and_publishes(self) -> None:
        session = FakeSession()
        client = InstagramApiClient(
            InstagramApiConfig("instagram_login", "v25.0", "ig-user", "kendo_keiko", "secret", "https://graph.example"),
            session=session,
            sleep=lambda _: None,
            poll_interval=0,
        )
        self.assertEqual("BUSINESS", client.verify_destination()["account_type"])
        container = client.create_reel_container(video_url="https://cdn.example/reel.mp4", caption="caption")
        self.assertEqual("container-1", container)
        self.assertEqual("FINISHED", client.wait_for_container(container)["status_code"])
        media = client.publish_container(container)
        self.assertEqual("media-1", media)
        self.assertEqual("https://instagram.example/reel/1", client.permalink(media))
        self.assertNotIn("secret", repr(client.config))

    def test_api_publish_transport_loss_is_unknown(self) -> None:
        client = InstagramApiClient(
            InstagramApiConfig("facebook_login", "v25.0", "ig-user", "kendo_keiko", "secret", "https://graph.example"),
            session=FakeSession(publish_error=True),
            sleep=lambda _: None,
        )
        with self.assertRaises(ReelUnknownResult):
            client.publish_container("container-1")

    def test_api_container_transport_loss_is_unknown_without_retry(self) -> None:
        session = Mock()
        session.request.side_effect = OSError("connection lost")
        client = InstagramApiClient(
            InstagramApiConfig("instagram_login", "v25.0", "ig-user", "kendo_keiko", "secret", "https://graph.example"),
            session=session,
            sleep=lambda _: None,
        )
        with self.assertRaises(ReelUnknownResult):
            client.create_reel_container(video_url="https://cdn.example/reel.mp4", caption="caption")
        self.assertEqual(1, session.request.call_count)


if __name__ == "__main__":
    unittest.main()
