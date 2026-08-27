#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from kendo_keiko.weekend_story import (
    DEFAULT_EVENTS_URL,
    NoEventsError,
    StoryError,
    fetch_events_payload,
    load_events_file,
    parse_target_saturday,
    render_story_pages,
    save_story_pages,
    select_weekend_events,
)


NO_EVENTS_EXIT_CODE = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "本番events.jsonまたはfixtureから、指定した土曜日と翌日曜日の"
            "Instagram Story画像を生成します。"
        )
    )
    parser.add_argument(
        "--date",
        required=True,
        help="対象週末の土曜日。YYYY-MM-DD。土曜日以外は拒否します。",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="PNG出力パス。複数ページ時は -01、-02 を付けます。",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--events-url",
        default=DEFAULT_EVENTS_URL,
        help=f"events.json URL。default: {DEFAULT_EVENTS_URL}",
    )
    source.add_argument(
        "--events-file",
        type=Path,
        help="ネットワークを使わずに読み込むfixture JSON。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        target = parse_target_saturday(args.date)
        payload = (
            load_events_file(args.events_file)
            if args.events_file is not None
            else fetch_events_payload(args.events_url)
        )
        events = select_weekend_events(payload, target)
        if not events:
            raise NoEventsError("no published events for the target weekend")
        images = render_story_pages(events, target)
        paths = save_story_pages(images, args.output)
    except NoEventsError as exc:
        print(f"[NO_EVENTS] {exc}", file=sys.stderr)
        return NO_EVENTS_EXIT_CODE
    except StoryError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    print(
        f"Generated {len(paths)} page(s) for {len(events)} event(s): "
        + ", ".join(str(path) for path in paths)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
