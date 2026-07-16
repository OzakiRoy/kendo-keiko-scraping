from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


START_MARKER = "<!-- ORGANIZATION_SECTION_START -->"
END_MARKER = "<!-- ORGANIZATION_SECTION_END -->"


def safe_http_url(value: object) -> str:
    if not value:
        return ""

    url = str(value).strip()
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        return ""

    if not parsed.netloc:
        return ""

    return url


def build_organization_section(
    organizations: list[dict[str, Any]],
) -> str:
    items: list[str] = []

    for organization in organizations:
        if not organization.get("scraper_enabled", False):
            continue

        description = str(
            organization.get("public_description") or ""
        ).strip()

        if not description:
            continue

        name = escape(
            str(organization.get("name") or ""),
            quote=True,
        )
        area = escape(
            str(organization.get("area") or "地域未設定"),
            quote=True,
        )
        description_html = escape(
            description,
            quote=True,
        )

        website_url = safe_http_url(
            organization.get("website_url")
        )

        if website_url:
            website_html = (
                '          <p class="organization-link">'
                f'<a href="{escape(website_url, quote=True)}" '
                'target="_blank" rel="noopener noreferrer">'
                "公式サイトを確認"
                "</a></p>"
            )
        else:
            website_html = ""

        lines = [
            '        <li class="organization-item">',
            f"          <h3>{name}</h3>",
            (
                '          <p class="organization-area">'
                f"主な地域: {area}</p>"
            ),
            f"          <p>{description_html}</p>",
        ]

        if website_html:
            lines.append(website_html)

        lines.append("        </li>")
        items.append("\n".join(lines))

    if items:
        body = "\n".join(items)
    else:
        body = (
            '        <li class="organization-item">'
            "現在掲載中の団体はありません。"
            "</li>"
        )

    return "\n".join(
        [
            (
                '    <section class="organization-section" '
                'id="listed-organizations" '
                'aria-labelledby="listed-organizations-heading">'
            ),
            (
                '      <h2 id="listed-organizations-heading">'
                "掲載中の剣道団体・剣道連盟"
                "</h2>"
            ),
            '      <p class="organization-intro">',
            (
                "        各団体・連盟の公式情報をもとに、"
                "一般参加できる稽古会や合同稽古会の予定を"
                "掲載しています。"
            ),
            "      </p>",
            '      <ul class="organization-list">',
            body,
            "      </ul>",
            '      <p class="organization-source-note">',
            (
                "        日程や参加条件が変更される場合があります。"
                "参加前に必ず主催団体の公式情報をご確認ください。"
            ),
            "      </p>",
            "    </section>",
        ]
    )


def replace_organization_section(
    html: str,
    section: str,
) -> str:
    start_index = html.find(START_MARKER)
    end_index = html.find(END_MARKER)

    if start_index == -1:
        raise ValueError(
            f"開始マーカーが見つかりません: {START_MARKER}"
        )

    if end_index == -1:
        raise ValueError(
            f"終了マーカーが見つかりません: {END_MARKER}"
        )

    if end_index <= start_index:
        raise ValueError(
            "団体セクションのマーカー順序が不正です"
        )

    content_start = start_index + len(START_MARKER)

    return (
        html[:content_start]
        + "\n"
        + section.rstrip()
        + "\n    "
        + html[end_index:]
    )


def generate_index(
    organizations_path: Path,
    index_path: Path,
) -> None:
    organizations = json.loads(
        organizations_path.read_text(encoding="utf-8")
    )

    if not isinstance(organizations, list):
        raise ValueError(
            "organizations.jsonのトップレベルは配列が必要です"
        )

    current_html = index_path.read_text(encoding="utf-8")
    section = build_organization_section(organizations)
    generated_html = replace_organization_section(
        current_html,
        section,
    )

    index_path.write_text(
        generated_html,
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "organizations.jsonからトップページの"
            "掲載団体セクションを生成します"
        )
    )
    parser.add_argument(
        "--organizations",
        type=Path,
        default=Path("data/organizations.json"),
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=Path("public/index.html"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    generate_index(
        organizations_path=args.organizations,
        index_path=args.index,
    )

    print(
        "[INFO] organization section generated:",
        args.index,
    )


if __name__ == "__main__":
    main()
