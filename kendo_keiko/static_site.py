from __future__ import annotations

import datetime as dt
import json
import re
from html import escape
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse, urljoin

from kendo_keiko.listing import (
    CATEGORIES,
    PAGES,
    TYPE_LABELS,
    UNKNOWN_TYPE_LABEL,
    select_events,
    type_label,
)


EVENT_META_START = "<!-- EVENT_META_START -->"
EVENT_META_END = "<!-- EVENT_META_END -->"
EVENT_COUNT_START = "<!-- EVENT_COUNT_START -->"
EVENT_COUNT_END = "<!-- EVENT_COUNT_END -->"
EVENT_CARDS_START = "<!-- EVENT_CARDS_START -->"
EVENT_CARDS_END = "<!-- EVENT_CARDS_END -->"

PARTICIPATION_LABELS = {
    "anyone": "一般参加可",
    "contact_required": "事前連絡",
    "registration_required": "申込必須",
    "invitation_required": "招待制",
    "members_only": "会員限定",
    "unknown": "公式情報を確認",
}


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


def _text(value: object, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def format_event_date(event: dict[str, Any]) -> str:
    event_date = _text(event.get("event_date"))
    weekday = _text(event.get("weekday"))
    return f"{event_date}({weekday})" if weekday else event_date


def format_event_time(event: dict[str, Any]) -> str:
    start_time = _text(event.get("start_time"))
    end_time = _text(event.get("end_time"))

    if start_time and end_time:
        return f"{start_time} - {end_time}"
    if start_time:
        return start_time
    return "時間未定"


def _iso_date(value: object) -> dt.date | None:
    text = _text(value)
    if len(text) < 10:
        return None

    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def participation_type_for_display(event: dict[str, Any]) -> str:
    participation_type = _text(
        event.get("participation_type"),
        "unknown",
    )
    if participation_type not in PARTICIPATION_LABELS:
        return "unknown"
    if (
        event.get("application_required") is False
        and participation_type == "registration_required"
    ):
        return "unknown"
    return participation_type


def render_event_status(
    event: dict[str, Any],
    *,
    reference_date: dt.date | None = None,
) -> list[str]:
    participation_type = participation_type_for_display(event)
    participation_label = PARTICIPATION_LABELS[participation_type]

    lines = [
        (
            '          <div class="event-status" '
            'aria-label="参加条件と情報確認状況">'
        ),
        (
            '            <span class="status-badge '
            f'status-badge--{participation_type}">'
            f'{escape(participation_label, quote=True)}</span>'
        ),
    ]

    if (
        event.get("application_required") is True
        and participation_type != "registration_required"
    ):
        lines.append(
            '            <span class="status-badge '
            'status-badge--registration_required">申込必須</span>'
        )

    verified_date = _iso_date(event.get("verified_at"))
    if verified_date is not None:
        verification_text = f"最終確認: {verified_date.isoformat()}"
    elif _text(event.get("update_mode"), "automatic") == "automatic":
        verification_text = "自動取得（未確認）"
    else:
        verification_text = "最終確認日なし"

    lines.append(
        '            <span class="verification-status">'
        f'{escape(verification_text, quote=True)}</span>'
    )

    review_due_at = _iso_date(event.get("review_due_at"))
    if (
        reference_date is not None
        and review_due_at is not None
        and review_due_at < reference_date
    ):
        lines.append(
            '            <span class="status-warning">確認期限超過</span>'
        )

    lines.append("          </div>")
    return lines


def sort_events(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        events,
        key=lambda event: (
            _text(event.get("event_date")),
            _text(event.get("start_time")),
            _text(event.get("organization_id")),
            _text(event.get("event_id")),
        ),
    )


def render_event_card(
    event: dict[str, Any],
    *,
    reference_date: dt.date | None = None,
) -> str:
    lines = [
        f'        <article class="card" data-event-id="{escape(_text(event.get("event_id")), quote=True)}">',
        f'          <div class="event-kind">{escape(type_label(event))}</div>',
        f'          <div class="date">{escape(format_event_date(event), quote=True)}</div>',
        (
            '          <div class="org">'
            f'{escape(_text(event.get("organization_name")), quote=True)}'
            '</div>'
        ),
    ]

    title = _text(event.get("title"))
    if title:
        lines.append(
            f'          <div class="title">{escape(title, quote=True)}</div>'
        )

    lines.extend(
        render_event_status(
            event,
            reference_date=reference_date,
        )
    )
    lines.extend(
        [
            (
                '          <div class="row"><span class="label">時間</span>'
                f'{escape(format_event_time(event), quote=True)}</div>'
            ),
            (
                '          <div class="row"><span class="label">会場</span>'
                f'{escape(_text(event.get("venue"), "未取得"), quote=True)}</div>'
            ),
            (
                '          <div class="row"><span class="label">エリア</span>'
                f'{escape(_text(event.get("area"), "未設定"), quote=True)}</div>'
            ),
        ]
    )

    access = _text(event.get("access"))
    if access:
        lines.append(
            '          <div class="row"><span class="label">アクセス</span>'
            f'{escape(access, quote=True)}</div>'
        )

    fee = _text(event.get("fee"))
    if fee:
        lines.append(
            '          <div class="row"><span class="label">参加費</span>'
            f'{escape(fee, quote=True)}</div>'
        )

    source_url = safe_http_url(event.get("source_url"))
    if source_url:
        lines.extend(
            [
                '          <div class="row">',
                '            <span class="label">公式</span>',
                (
                    f'            <a href="{escape(source_url, quote=True)}" '
                    'target="_blank" rel="noopener noreferrer">'
                    '公式情報を確認</a>'
                ),
                '          </div>',
            ]
        )

    lines.append("        </article>")
    return "\n".join(lines)


def render_event_cards(
    events: list[dict[str, Any]],
    *,
    reference_date: dt.date | None = None,
) -> str:
    if not events:
        return '        <div class="empty">現在掲載中のイベントはありません。</div>'

    return "\n".join(
        render_event_card(event, reference_date=reference_date)
        for event in events
    )


def _replace_marked_content(
    html: str,
    *,
    start_marker: str,
    end_marker: str,
    content: str,
    indent: str,
) -> str:
    start_index = html.find(start_marker)
    end_index = html.find(end_marker)

    if start_index == -1:
        raise ValueError(f"開始マーカーが見つかりません: {start_marker}")
    if end_index == -1:
        raise ValueError(f"終了マーカーが見つかりません: {end_marker}")
    if end_index <= start_index:
        raise ValueError(f"マーカー順序が不正です: {start_marker}")

    content_start = start_index + len(start_marker)
    return (
        html[:content_start]
        + "\n"
        + content.rstrip()
        + "\n"
        + indent
        + html[end_index:]
    )


def render_static_index(
    template_html: str,
    payload: dict[str, Any],
    *,
    category: str = "all",
    site_url: str = "https://kendo-keiko.com/",
) -> str:
    template_html = render_page_shell(template_html, category, site_url)
    raw_events = payload.get("events", [])
    if not isinstance(raw_events, list):
        raise ValueError("events payloadのeventsは配列が必要です")

    events: list[dict[str, Any]] = []
    for event in raw_events:
        if not isinstance(event, dict):
            raise ValueError("events payloadの各要素はオブジェクトが必要です")
        events.append(event)

    events = sort_events(select_events(events, category))
    generated_at = _text(payload.get("generated_at"), "-")
    reference_date = _iso_date(generated_at)
    event_count = len(events)

    html = _replace_marked_content(
        template_html,
        start_marker=EVENT_META_START,
        end_marker=EVENT_META_END,
        content=(
            '      <div class="meta" id="meta">'
            f'更新日時: {escape(generated_at, quote=True)} / '
            f'掲載件数: {event_count}件</div>'
        ),
        indent="      ",
    )
    html = _replace_marked_content(
        html,
        start_marker=EVENT_COUNT_START,
        end_marker=EVENT_COUNT_END,
        content=f'        <div class="count" id="count">{event_count}件掲載中</div>',
        indent="        ",
    )
    html = _replace_marked_content(
        html,
        start_marker=EVENT_CARDS_START,
        end_marker=EVENT_CARDS_END,
        content=render_event_cards(
            events,
            reference_date=reference_date,
        ),
        indent="        ",
    )
    return render_filter_options(html, events)


def build_sitemap_xml(
    *,
    site_url: str = "https://kendo-keiko.com/",
    lastmod: dt.date | None = None,
) -> str:
    lastmod = lastmod or dt.date.today()
    entries = "\n".join(
        "  <url>\n"
        f"    <loc>{escape(urljoin(site_url, page['path']), quote=True)}</loc>\n"
        f"    <lastmod>{lastmod.isoformat()}</lastmod>\n"
        "  </url>"
        for page in PAGES.values()
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + entries + '\n</urlset>\n'
    )


def render_static_index_file(
    *,
    template_path: Path,
    output_path: Path,
    payload: dict[str, Any],
    site_url: str = "https://kendo-keiko.com/",
) -> None:
    rendered = render_static_index(
        template_path.read_text(encoding="utf-8"),
        payload,
        site_url=site_url,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")


def render_filter_options(html: str, events: list[dict[str, Any]]) -> str:
    """Match static options to the same page scope used by the browser."""
    participation_types = {participation_type_for_display(event) for event in events}
    if any(event.get("application_required") is True for event in events):
        participation_types.add("registration_required")
    options = {
        "organization": [("", "すべての団体")] + [
            (name, name) for name in sorted({
                _text(event.get("organization_name")) for event in events
                if _text(event.get("organization_name"))
            })
        ],
        "area": [("", "すべての地域")] + [
            (area, area) for area in sorted({
                _text(event.get("area")) for event in events if _text(event.get("area"))
            })
        ],
        "participation": [("", "すべての参加条件")] + [
            (value, label) for value, label in PARTICIPATION_LABELS.items()
            if value in participation_types
        ],
    }
    for select_id, values in options.items():
        content = "\n".join(
            f'            <option value="{escape(value, quote=True)}">{escape(label)}</option>'
            for value, label in values
        )
        html = re.sub(
            rf'(<select id="{select_id}">).*?(</select>)',
            lambda match: match[1] + "\n" + content + "\n          " + match[2],
            html,
            flags=re.S,
        )
    return html


def render_page_shell(template: str, category: str, site_url: str) -> str:
    page = PAGES[category]
    canonical = urljoin(site_url, page["path"])
    # Complete marked regions keep generation idempotent, even from a rendered page.
    metadata = [
        f'  <title>{escape(page["title"])}</title>',
        f'  <meta name="description" content="{escape(page["description"], quote=True)}">',
        f'  <link rel="canonical" href="{escape(canonical, quote=True)}">',
    ]
    for attr, value in (
        ("og:title", page["title"]),
        ("og:description", page["description"]),
        ("og:url", canonical),
        ("twitter:title", page["title"]),
        ("twitter:description", page["description"]),
    ):
        name = "name" if attr.startswith("twitter:") else "property"
        metadata.append(f'  <meta {name}="{attr}" content="{escape(value, quote=True)}">')
    config = json.dumps(
        {"category": category, "categories": CATEGORIES,
         "typeLabels": TYPE_LABELS, "unknownTypeLabel": UNKNOWN_TYPE_LABEL},
        ensure_ascii=False,
    ).replace("<", "\\u003c")
    navigation = ['    <nav class="listing-nav" aria-label="イベント一覧">']
    for key, item in PAGES.items():
        current = ' aria-current="page"' if key == category else ''
        label = "総合一覧" if key == "all" else CATEGORIES[key]["label"]
        navigation.append(f'      <a href="{item["path"]}"{current}>{label}</a>')
    navigation.append('    </nav>')
    controls = []
    if category == "all":
        controls.append(
            '      <fieldset class="kind-filter"><legend>種別</legend>\n'
            '        <div class="kind-buttons">'
        )
        for key, item in CATEGORIES.items():
            controls.append(
                f'          <button type="button" class="date-shortcut-button" data-category="{key}" '
                f'aria-pressed="{str(key == "all").lower()}">{item["label"]}</button>'
            )
        controls.append('        </div>\n      </fieldset>')
    for marker, content, indent in (
        ("PAGE_META", "\n".join(metadata), "  "),
        ("LISTING_CONFIG", f'  <script type="application/json" id="listing-config">{config}</script>', "  "),
        ("LISTING_NAV", "\n".join(navigation), "    "),
        ("KIND_FILTER", "\n".join(controls), "      "),
    ):
        template = _replace_marked_content(
            template,
            start_marker=f"<!-- {marker}_START -->",
            end_marker=f"<!-- {marker}_END -->",
            content=content,
            indent=indent,
        )
    template = re.sub(
        r'(<h2 id="search-heading">).*?(</h2>)',
        lambda match: match[1] + escape(page["heading"]) + match[2],
        template,
    )
    return re.sub(
        r'(<p class="lead">).*?(</p>)',
        lambda match: match[1] + escape(page["description"]) +
        ' 参加前には必ず主催者の公式情報をご確認ください。' + match[2],
        template,
        flags=re.S,
    )


def render_listing_pages(
    template: str,
    payload: dict[str, Any],
    *,
    site_url: str = "https://kendo-keiko.com/",
) -> dict[str, str]:
    return {
        page["key"]: render_static_index(template, payload, category=category, site_url=site_url)
        for category, page in PAGES.items()
    }
