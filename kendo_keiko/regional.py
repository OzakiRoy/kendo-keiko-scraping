"""Regional static pages, rendered from the same merged public payload."""
from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path
from string import Template
from typing import Any
from urllib.parse import urljoin

from kendo_keiko.listing import CATEGORIES, REGIONS, TYPE_LABELS, select_region_events


PUBLIC_EVENT_FIELDS = (
    "event_id", "organization_id", "organization_name", "event_type", "title", "event_date",
    "weekday", "start_time", "end_time", "venue", "area", "access", "fee", "application_required",
    "source_url", "status", "update_mode", "participation_type", "verified_at", "review_due_at", "raw_note",
)


def render_regional_page(template: str, payload: dict[str, Any], region: str, *, site_url: str) -> str:
    # Imported here so the existing static-site API can delegate to this module.
    from kendo_keiko.static_site import (
        PARTICIPATION_LABELS, _replace_marked_content, _iso_date,
        render_event_card, safe_http_url, sort_events,
    )

    definition = REGIONS[region]
    events = sort_events(select_region_events(payload["events"], region))
    canonical = urljoin(site_url, definition["path"])
    head_match = re.search(r"<!doctype html>.*?</head>", template, flags=re.S | re.I)
    header_match = re.search(r'<header class="site-header">.*?</header>', template, flags=re.S)
    footer_match = re.search(r'<footer class="site-footer">.*?</footer>', template, flags=re.S)
    if not all((head_match, header_match, footer_match)):
        raise ValueError("地域ページに必要な共通head・header・footerがありません")
    head = head_match.group()
    # Regional controls use the shared design CSS plus their own small stylesheet.
    head = re.sub(r"\s*<style>.*?</style>", "", head, flags=re.S)
    metadata = [
        f'  <title>{escape(definition["title"])}</title>',
        f'  <meta name="description" content="{escape(definition["description"], quote=True)}">',
        f'  <link rel="canonical" href="{escape(canonical, quote=True)}">',
    ]
    for name, value in (("og:title", definition["title"]), ("og:description", definition["description"]),
                        ("og:url", canonical), ("twitter:title", definition["title"]),
                        ("twitter:description", definition["description"])):
        attr = "name" if name.startswith("twitter:") else "property"
        metadata.append(f'  <meta {attr}="{name}" content="{escape(value, quote=True)}">')
    head = _replace_marked_content(head, start_marker="<!-- PAGE_META_START -->",
                                   end_marker="<!-- PAGE_META_END -->", content="\n".join(metadata), indent="  ")
    if 'href="/assets/calendar.css"' not in head:
        head = head.replace("</head>", '  <link rel="stylesheet" href="/assets/calendar.css">\n</head>')

    organizations = json.loads((Path(__file__).resolve().parent.parent / "data/organizations.json").read_text(encoding="utf-8"))
    master = {item["organization_id"]: item for item in organizations}
    by_org: dict[str, dict] = {}
    for event in events:
        org_id = str(event.get("organization_id") or "")
        if org_id not in by_org:
            record = master.get(org_id, {})
            by_org[org_id] = {
                "organization_id": org_id, "name": record.get("name") or event.get("organization_name") or "名称未確認",
                "website_url": record.get("website_url") or event.get("source_url"),
                "public_description": record.get("public_description") or "開催予定の参加条件と公式案内をご確認ください。",
            }
    org_items = []
    for item in by_org.values():
        url = safe_http_url(item["website_url"])
        link = (f'<p><a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">公式案内 ↗</a></p>' if url else "")
        org_items.append('<li class="organization-item"><h3>' + escape(item["name"]) + '</h3><p>' +
                         escape(item["public_description"]) + '</p>' + link + '</li>')
    if not org_items:
        org_items.append('<li class="organization-item">現在、開催予定を掲載している団体はありません。</li>')

    generated_at = str(payload.get("generated_at") or "-")
    reference = _iso_date(generated_at)
    cards = []
    for event in events:
        card = render_event_card(event, reference_date=reference)
        # Preserve official eligibility notes without adding another card renderer.
        if event.get("raw_note"):
            note = ('          <p class="row row--note"><span class="label">補足</span><span>' +
                    escape(str(event["raw_note"]), quote=True) + '</span></p>\n')
            card = card.removesuffix("        </article>") + note + "        </article>"
        cards.append(card)
    static_cards = "\n".join(cards) or '<p class="empty">現在の掲載情報はありません。<a href="/">総合一覧もご覧ください。</a></p>'
    region_links = "\n".join(
        f'<a href="{item["path"]}"' + (' aria-current="page"' if key == region else '') + '>' +
        ('関東全体' if key == "kanto" else item["name"]) + '</a>'
        for key, item in REGIONS.items()
    )
    breadcrumb = ('<li><a href="/area/kanto/">関東</a></li>' if region == "tokyo" else "")
    config = {
        "region": region, "categories": CATEGORIES, "typeLabels": TYPE_LABELS,
        "participationLabels": PARTICIPATION_LABELS,
        "events": [{**{key: event.get(key) for key in PUBLIC_EVENT_FIELDS},
                    "status": event.get("status", "active")} for event in events],
        "organizations": list(by_org.values()),
    }
    config_json = json.dumps(config, ensure_ascii=False).replace("<", "\\u003c")
    fragment = Template((Path(__file__).resolve().parent / "templates/area.html").read_text(encoding="utf-8"))
    main = fragment.substitute(
        name=escape(definition["name"]), eyebrow=definition["eyebrow"],
        description=escape(definition["description"]), guidance=escape(definition["guidance"]),
        breadcrumb=breadcrumb, event_count=len(events), org_count=len(by_org),
        generated_at=escape(generated_at), region_links=region_links,
        static_cards=static_cards, organizations="\n".join(org_items),
    )
    return (head + '\n<body class="site-page site-page--area">\n' + header_match.group() + '\n' + main + '\n' +
            footer_match.group() + '\n<script type="application/json" id="regional-data">' + config_json + '</script>\n' +
            '<script src="/assets/calendar-core.js" defer></script>\n<script src="/assets/regional-calendar.js" defer></script>\n</body>\n</html>\n')
