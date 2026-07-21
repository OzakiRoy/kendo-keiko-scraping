from __future__ import annotations

import argparse
import json
from pathlib import Path

from kendo_keiko.static_site import render_static_index_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "events.jsonからトップページの開催予定イベントを静的生成します"
        )
    )
    parser.add_argument(
        "--events",
        type=Path,
        default=Path("public/events.json"),
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=Path("public/index.html"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("public/index.html"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = json.loads(args.events.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise ValueError("events.jsonのトップレベルはオブジェクトが必要です")

    render_static_index_file(
        template_path=args.template,
        output_path=args.output,
        payload=payload,
    )

    print("[INFO] event section generated:", args.output)


if __name__ == "__main__":
    main()
