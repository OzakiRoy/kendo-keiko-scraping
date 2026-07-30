from __future__ import annotations

import datetime as dt
from html import escape
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


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
        '        <article class="card">',
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
        return '        <div class="empty">現在掲載中の稽古会はありません。</div>'

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
) -> str:
    raw_events = payload.get("events", [])
    if not isinstance(raw_events, list):
        raise ValueError("events payloadのeventsは配列が必要です")

    events: list[dict[str, Any]] = []
    for event in raw_events:
        if not isinstance(event, dict):
            raise ValueError("events payloadの各要素はオブジェクトが必要です")
        events.append(event)

    events = sort_events(events)
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
    return html


def build_sitemap_xml(
    *,
    site_url: str = "https://kendo-keiko.com/",
    lastmod: dt.date | None = None,
) -> str:
    lastmod = lastmod or dt.date.today()
    safe_site_url = escape(site_url, quote=True)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        '  <url>\n'
        f'    <loc>{safe_site_url}</loc>\n'
        f'    <lastmod>{lastmod.isoformat()}</lastmod>\n'
        '    <changefreq>daily</changefreq>\n'
        '    <priority>1.0</priority>\n'
        '  </url>\n'
        '</urlset>\n'
    )


def render_static_index_file(
    *,
    template_path: Path,
    output_path: Path,
    payload: dict[str, Any],
) -> None:
    rendered = render_static_index(
        template_path.read_text(encoding="utf-8"),
        payload,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
