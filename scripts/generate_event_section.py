from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kendo_keiko.static_site import (
    build_sitemap_xml,
    render_listing_pages,
    render_static_index_file,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "公開events.jsonから総合・カテゴリ一覧のHTMLを静的生成します"
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
        default=Path(__file__).resolve().parents[1] / "public/index.html",
    )
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--output",
        type=Path,
        default=Path("public/index.html"),
    )
    output.add_argument(
        "--output-dir", type=Path,
        help="3一覧ページとsitemapを生成するディレクトリ（--outputとの併用不可）",
    )
    parser.add_argument("--site-url", default="https://kendo-keiko.com/")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = json.loads(args.events.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise ValueError("events.jsonのトップレベルはオブジェクトが必要です")

    if args.output_dir:
        template = args.template.read_text(encoding="utf-8")
        outputs = render_listing_pages(template, payload, site_url=args.site_url)
        lastmod = (
            dt.date.fromisoformat(payload["generated_at"][:10])
            if payload.get("generated_at") else None
        )
        outputs["sitemap.xml"] = build_sitemap_xml(site_url=args.site_url, lastmod=lastmod)
        for key, body in outputs.items():
            path = args.output_dir / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        print("[INFO] listing pages generated:", args.output_dir)
        return

    render_static_index_file(
        template_path=args.template,
        output_path=args.output,
        payload=payload,
        site_url=args.site_url,
    )

    print("[INFO] event section generated:", args.output)


if __name__ == "__main__":
    main()
