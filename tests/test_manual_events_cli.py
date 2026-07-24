from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import manage_manual_events
from kendo_keiko.manual_events import load_manual_events


class ManualEventsCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.manual_path = root / "manual_events.json"
        self.organizations_path = root / "organizations.json"
        self.organizations_path.write_text(
            json.dumps(
                [
                    {
                        "organization_id": "manual-org",
                        "name": "手動団体",
                        "area": "埼玉県",
                        "website_url": "https://example.com/",
                        "source_type": "official_site",
                        "scraper_type": "manual",
                        "scraper_enabled": False,
                        "event_type": "open_keiko",
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.base_args = [
            "--file",
            str(self.manual_path),
            "--organizations",
            str(self.organizations_path),
        ]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_cli(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = manage_manual_events.main([*self.base_args, *args])
        return code, stdout.getvalue(), stderr.getvalue()

    def add_args(self) -> list[str]:
        return [
            "--organization-id",
            "manual-org",
            "--title",
            "合同稽古会",
            "--start-time",
            "19:00",
            "--end-time",
            "20:30",
            "--venue",
            "テスト武道館",
            "--source-url",
            "https://example.com/event",
            "--verified-at",
            "2026-07-24T10:00:00+09:00",
            "--review-due-at",
            "2026-08-24",
        ]

    def test_dry_run_does_not_write_file(self) -> None:
        code, stdout, stderr = self.run_cli(
            ["add", *self.add_args(), "--date", "2026-08-10", "--dry-run"]
        )

        self.assertEqual(0, code)
        self.assertEqual("", stderr)
        self.assertIn('"dry_run": true', stdout)
        self.assertFalse(self.manual_path.exists())

    def test_add_and_add_batch(self) -> None:
        code, _, stderr = self.run_cli(
            ["add", *self.add_args(), "--date", "2026-08-10"]
        )
        self.assertEqual(0, code, stderr)

        batch_args = self.add_args()
        batch_args[batch_args.index("https://example.com/event")] = (
            "https://example.com/batch"
        )
        code, _, stderr = self.run_cli(
            [
                "add-batch",
                *batch_args,
                "--date",
                "2026-08-11",
                "--date",
                "2026-08-12",
            ]
        )

        self.assertEqual(0, code, stderr)
        events = load_manual_events(self.manual_path)
        self.assertEqual(3, len(events))
        self.assertEqual(
            ["2026-08-10", "2026-08-11", "2026-08-12"],
            [event["event_date"] for event in events],
        )

    def test_update_cancel_archive_and_verify(self) -> None:
        code, _, stderr = self.run_cli(
            ["add", *self.add_args(), "--date", "2026-08-10"]
        )
        self.assertEqual(0, code, stderr)
        event_id = load_manual_events(self.manual_path)[0]["event_id"]

        code, _, stderr = self.run_cli(
            ["update", event_id, "--venue", "更新後武道館"]
        )
        self.assertEqual(0, code, stderr)
        self.assertEqual(
            "更新後武道館",
            load_manual_events(self.manual_path)[0]["venue"],
        )

        code, _, stderr = self.run_cli(["cancel", event_id])
        self.assertEqual(0, code, stderr)
        self.assertEqual(
            "cancelled",
            load_manual_events(self.manual_path)[0]["status"],
        )

        code, _, stderr = self.run_cli(["archive", event_id])
        self.assertEqual(0, code, stderr)
        self.assertEqual(
            "archived",
            load_manual_events(self.manual_path)[0]["status"],
        )

        code, _, stderr = self.run_cli(
            [
                "verify",
                event_id,
                "--verified-at",
                "2026-07-25T09:00:00+09:00",
                "--review-due-at",
                "2026-08-25",
            ]
        )
        self.assertEqual(0, code, stderr)
        event = load_manual_events(self.manual_path)[0]
        self.assertEqual("2026-07-25T09:00:00+09:00", event["verified_at"])
        self.assertEqual("2026-08-25", event["review_due_at"])

    def test_list_review_due(self) -> None:
        code, _, stderr = self.run_cli(
            ["add", *self.add_args(), "--date", "2026-09-10"]
        )
        self.assertEqual(0, code, stderr)

        code, stdout, stderr = self.run_cli(
            ["list-review-due", "--as-of", "2026-08-24"]
        )

        self.assertEqual(0, code, stderr)
        self.assertIn("手動団体", stdout)
        self.assertIn("review_due=2026-08-24", stdout)


if __name__ == "__main__":
    unittest.main()
