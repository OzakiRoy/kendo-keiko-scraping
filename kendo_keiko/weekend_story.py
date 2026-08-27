from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import requests
from PIL import Image, ImageDraw, ImageFont

from kendo_keiko.static_site import (
    PARTICIPATION_LABELS,
    participation_type_for_display,
)


STORY_WIDTH = 1080
STORY_HEIGHT = 1920
MAX_EVENTS_PER_PAGE = 5
EXPECTED_SCHEMA_VERSION = "public-events-0.3"
EXPECTED_TIMEZONE = "Asia/Tokyo"
DEFAULT_EVENTS_URL = "https://kendo-keiko.com/events.json"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_FONT_PATH = ROOT_DIR / "assets" / "fonts" / "NotoSansJP[wght].ttf"
DEFAULT_SERIF_FONT_PATH = (
    ROOT_DIR / "assets" / "fonts" / "NotoSerifJP[wght].ttf"
)
DEFAULT_ICON_PATH = ROOT_DIR / "public" / "icon-512.png"

PAPER = "#f3f1ec"
SURFACE = "#fffdfa"
INK = "#1b1b1b"
INK_SOFT = "#42403c"
MUTED = "#706d67"
ACCENT = "#8c1d24"
ACCENT_SOFT = "#f4e5e5"
LINE = "#d6d1c8"
SHADOW = "#ded9d0"
WARM_LINE = "#c5ae80"

CONTENT_LEFT = 64
CONTENT_RIGHT = STORY_WIDTH - 64
CONTENT_TOP = 505
CONTENT_BOTTOM = 1650
CARD_GAP = 26
MIN_CARD_HEIGHT = 340
CARD_DIVIDER_X = 526
CARD_LEFT_X = CONTENT_LEFT + 38
CARD_RIGHT_X = CARD_DIVIDER_X + 34
CARD_VALUE_X = CARD_RIGHT_X + 92


class StoryError(ValueError):
    pass


class NoEventsError(StoryError):
    pass


class LayoutOverflowError(StoryError):
    pass


@dataclass(frozen=True)
class StoryEvent:
    event_id: str
    organization_id: str
    organization_name: str
    title: str
    event_date: str
    start_time: str
    end_time: str
    venue: str
    area: str
    fee: str | None
    access: str | None
    participation_type: str
    application_required: bool | None
    participation_labels: tuple[str, ...]


@dataclass(frozen=True)
class EventLayout:
    event: StoryEvent
    height: int
    organization_lines: tuple[str, ...]
    title_lines: tuple[str, ...]
    venue_lines: tuple[str, ...]
    area_lines: tuple[str, ...]
    fee_lines: tuple[str, ...]
    access_lines: tuple[str, ...]


def parse_target_saturday(value: str) -> dt.date:
    try:
        target = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise StoryError("--date must use YYYY-MM-DD") from exc
    if target.weekday() != 5:
        raise StoryError("--date must be a Saturday")
    return target


def validate_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise StoryError("events.json top level must be an object")
    if payload.get("schema_version") != EXPECTED_SCHEMA_VERSION:
        raise StoryError(
            "unsupported schema_version: "
            f"{payload.get('schema_version')!r}"
        )
    if payload.get("timezone") != EXPECTED_TIMEZONE:
        raise StoryError(
            f"timezone must be {EXPECTED_TIMEZONE}: "
            f"{payload.get('timezone')!r}"
        )
    events = payload.get("events")
    if not isinstance(events, list):
        raise StoryError("events must be an array")
    if not all(isinstance(event, dict) for event in events):
        raise StoryError("every event must be an object")
    return events


def load_events_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StoryError(f"failed to read events file: {path}") from exc
    validate_payload(payload)
    return payload


def fetch_events_payload(
    url: str = DEFAULT_EVENTS_URL,
    *,
    timeout: tuple[float, float] = (5.0, 20.0),
) -> dict[str, Any]:
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise StoryError(f"failed to fetch events.json: {url}") from exc

    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            reported_size = int(content_length)
        except ValueError as exc:
            raise StoryError("events.json has an invalid Content-Length") from exc
        if reported_size > MAX_RESPONSE_BYTES:
            raise StoryError("events.json exceeds the response size limit")
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise StoryError("events.json exceeds the response size limit")
    try:
        payload = response.json()
    except requests.JSONDecodeError as exc:
        raise StoryError("events.json is not valid JSON") from exc
    validate_payload(payload)
    return payload


def _preserved_text(
    event: dict[str, Any],
    key: str,
    *,
    required: bool = False,
) -> str:
    value = event.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and value == ""):
        raise StoryError(f"event {key} must be a string")
    return value


def _optional_preserved_text(
    event: dict[str, Any], key: str
) -> str | None:
    value = event.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise StoryError(f"event {key} must be a string or null")
    return value


def event_for_story(event: dict[str, Any]) -> StoryEvent:
    participation = participation_type_for_display(event)
    labels = [PARTICIPATION_LABELS[participation]]
    application_required = event.get("application_required")
    if application_required not in {True, False, None}:
        raise StoryError("event application_required must be boolean or null")
    if application_required is True and participation != "registration_required":
        labels.append(PARTICIPATION_LABELS["registration_required"])

    return StoryEvent(
        event_id=_preserved_text(event, "event_id", required=True),
        organization_id=_preserved_text(
            event, "organization_id", required=True
        ),
        organization_name=_preserved_text(
            event, "organization_name", required=True
        ),
        title=_preserved_text(event, "title"),
        event_date=_preserved_text(event, "event_date", required=True),
        start_time=_preserved_text(event, "start_time"),
        end_time=_preserved_text(event, "end_time"),
        venue=_preserved_text(event, "venue"),
        area=_preserved_text(event, "area"),
        fee=_optional_preserved_text(event, "fee"),
        access=_optional_preserved_text(event, "access"),
        participation_type=participation,
        application_required=application_required,
        participation_labels=tuple(labels),
    )


def select_weekend_events(
    payload: dict[str, Any], target_saturday: dt.date
) -> list[StoryEvent]:
    events = validate_payload(payload)
    sunday = target_saturday + dt.timedelta(days=1)
    target_dates = {target_saturday.isoformat(), sunday.isoformat()}
    selected = [
        event_for_story(event)
        for event in events
        if event.get("event_date") in target_dates
    ]
    return sorted(
        selected,
        key=lambda event: (
            event.event_date,
            event.start_time,
            event.organization_id,
            event.event_id,
        ),
    )


def load_font(path: Path, size: int, *, weight: int = 400) -> ImageFont.FreeTypeFont:
    if not path.is_file():
        raise StoryError(f"bundled Japanese font not found: {path}")
    font = ImageFont.truetype(str(path), size=size)
    try:
        font.set_variation_by_axes([float(weight)])
    except (AttributeError, OSError, ValueError) as exc:
        raise StoryError(f"font does not support the expected weight axis: {path}") from exc
    return font


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> tuple[str, ...]:
    if text == "":
        return ()
    lines: list[str] = []
    current = ""
    for character in text:
        candidate = current + character
        width = draw.textlength(candidate, font=font)
        if width <= max_width:
            current = candidate
            continue
        if not current:
            raise LayoutOverflowError(
                f"a character cannot fit within {max_width}px"
            )
        lines.append(current)
        current = character
    if current:
        lines.append(current)
    if "".join(lines) != text:
        raise AssertionError("text wrapping changed the source string")
    return tuple(lines)


def _font_set(
    font_path: Path,
    serif_font_path: Path,
) -> dict[str, ImageFont.FreeTypeFont]:
    return {
        "org": load_font(serif_font_path, 40, weight=700),
        "title": load_font(serif_font_path, 29, weight=600),
        "body": load_font(font_path, 27, weight=400),
        "small": load_font(font_path, 23, weight=500),
    }


def layout_event(
    draw: ImageDraw.ImageDraw,
    event: StoryEvent,
    fonts: dict[str, ImageFont.FreeTypeFont],
) -> EventLayout:
    left_text_width = CARD_DIVIDER_X - CARD_LEFT_X - 28
    right_text_width = CONTENT_RIGHT - 34 - CARD_VALUE_X
    organization_lines = wrap_text(
        draw, event.organization_name, fonts["org"], left_text_width
    )
    title_lines = wrap_text(
        draw, event.title, fonts["title"], left_text_width
    )
    venue_lines = wrap_text(
        draw, event.venue, fonts["body"], right_text_width
    )
    area_lines = wrap_text(
        draw, event.area, fonts["small"], right_text_width
    )
    fee_lines = wrap_text(
        draw, event.fee or "", fonts["small"], right_text_width
    )
    access_lines = wrap_text(
        draw, event.access or "", fonts["small"], right_text_width
    )

    left_height = max(1, len(organization_lines)) * 52
    left_height += len(title_lines) * 42
    left_height += 54
    right_height = max(1, len(venue_lines)) * 38
    right_height += max(1, len(area_lines)) * 36
    right_height += len(fee_lines) * 35
    right_height += len(access_lines) * 35
    height = 78 + max(left_height, right_height) + 28
    height = max(MIN_CARD_HEIGHT, height)

    available = CONTENT_BOTTOM - CONTENT_TOP
    if height > available:
        raise LayoutOverflowError(
            f"event does not fit on one Story page: {event.event_id}"
        )
    return EventLayout(
        event=event,
        height=height,
        organization_lines=organization_lines,
        title_lines=title_lines,
        venue_lines=venue_lines,
        area_lines=area_lines,
        fee_lines=fee_lines,
        access_lines=access_lines,
    )


def paginate_layouts(layouts: Iterable[EventLayout]) -> list[list[EventLayout]]:
    available = CONTENT_BOTTOM - CONTENT_TOP
    pages: list[list[EventLayout]] = []
    current: list[EventLayout] = []
    used = 0

    for layout in layouts:
        required = layout.height + (CARD_GAP if current else 0)
        if current and (
            len(current) >= MAX_EVENTS_PER_PAGE or used + required > available
        ):
            pages.append(current)
            current = []
            used = 0
            required = layout.height
        if required > available:
            raise LayoutOverflowError(
                f"event does not fit on one Story page: {layout.event.event_id}"
            )
        current.append(layout)
        used += required

    if current:
        pages.append(current)

    # Avoid a visually weak single-card final page when two balanced pages fit.
    if len(pages) >= 2 and len(pages[-1]) == 1 and len(pages[-2]) >= 3:
        moved = pages[-2][-1]
        candidate = [moved, *pages[-1]]
        candidate_height = sum(layout.height for layout in candidate)
        candidate_height += CARD_GAP * (len(candidate) - 1)
        if candidate_height <= available:
            pages[-2].pop()
            pages[-1] = candidate
    return pages


def _draw_lines(
    draw: ImageDraw.ImageDraw,
    lines: tuple[str, ...],
    *,
    x: int,
    y: int,
    font: ImageFont.FreeTypeFont,
    fill: str,
    line_height: int,
) -> int:
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


def _format_time(event: StoryEvent) -> str:
    if event.start_time and event.end_time:
        return f"{event.start_time} - {event.end_time}"
    if event.start_time:
        return event.start_time
    return "時間未定"


def _format_event_day(event_date: str) -> str:
    parsed = dt.date.fromisoformat(event_date)
    weekday = "月火水木金土日"[parsed.weekday()]
    return f"{parsed.month}/{parsed.day}（{weekday}）"


def _format_target_dates(target: dt.date) -> str:
    sunday = target + dt.timedelta(days=1)
    return f"{target.month}月{target.day}日（土）・{sunday.month}月{sunday.day}日（日）"


def _page_start_and_gap(page: list[EventLayout]) -> tuple[int, int]:
    content_height = CONTENT_BOTTOM - CONTENT_TOP
    cards_height = sum(layout.height for layout in page)
    base_gaps = CARD_GAP * max(0, len(page) - 1)
    unused = max(0, content_height - cards_height - base_gaps)
    top_offset = min(180, unused // 2)
    if len(page) <= 1:
        return CONTENT_TOP + top_offset, CARD_GAP
    extra_gap = min(72, max(0, unused - top_offset) // (len(page) - 1))
    return CONTENT_TOP + top_offset, CARD_GAP + extra_gap


def _draw_participation_badges(
    draw: ImageDraw.ImageDraw,
    labels: tuple[str, ...],
    *,
    x: int,
    y: int,
    font: ImageFont.FreeTypeFont,
) -> None:
    cursor = x
    for label in labels:
        width = round(draw.textlength(label, font=font)) + 38
        draw.rounded_rectangle(
            (cursor, y, cursor + width, y + 38),
            radius=18,
            fill=SURFACE,
            outline=ACCENT,
            width=2,
        )
        draw.text((cursor + 19, y + 4), label, font=font, fill=ACCENT)
        cursor += width + 12


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    y: int,
    font: ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    width = draw.textlength(text, font=font)
    draw.text(((STORY_WIDTH - width) / 2, y), text, font=font, fill=fill)


def _draw_divider(draw: ImageDraw.ImageDraw, y: int) -> None:
    center = STORY_WIDTH // 2
    draw.line((92, y, center - 28, y), fill=ACCENT, width=2)
    draw.line((center + 28, y, STORY_WIDTH - 92, y), fill=ACCENT, width=2)
    draw.polygon(
        ((center, y - 10), (center + 10, y), (center, y + 10), (center - 10, y)),
        fill=ACCENT,
    )


def _draw_card_corners(
    draw: ImageDraw.ImageDraw,
    left: int,
    top: int,
    right: int,
    bottom: int,
) -> None:
    length = 22
    inset = 12
    for x1, y1, x2, y2 in (
        (left + inset, top + inset, left + inset + length, top + inset),
        (left + inset, top + inset, left + inset, top + inset + length),
        (right - inset - length, top + inset, right - inset, top + inset),
        (right - inset, top + inset, right - inset, top + inset + length),
        (left + inset, bottom - inset, left + inset + length, bottom - inset),
        (left + inset, bottom - inset - length, left + inset, bottom - inset),
        (right - inset - length, bottom - inset, right - inset, bottom - inset),
        (right - inset, bottom - inset - length, right - inset, bottom - inset),
    ):
        draw.line((x1, y1, x2, y2), fill=WARM_LINE, width=2)


def render_story_pages(
    events: list[StoryEvent],
    target_saturday: dt.date,
    *,
    font_path: Path = DEFAULT_FONT_PATH,
    serif_font_path: Path = DEFAULT_SERIF_FONT_PATH,
    icon_path: Path = DEFAULT_ICON_PATH,
) -> list[Image.Image]:
    if not events:
        raise NoEventsError("no published events for the target weekend")

    measuring_image = Image.new("RGB", (STORY_WIDTH, STORY_HEIGHT), PAPER)
    measuring_draw = ImageDraw.Draw(measuring_image)
    fonts = _font_set(font_path, serif_font_path)
    layouts = [layout_event(measuring_draw, event, fonts) for event in events]
    pages = paginate_layouts(layouts)

    heading_font = load_font(serif_font_path, 66, weight=700)
    site_font = load_font(serif_font_path, 36, weight=700)
    domain_font = load_font(font_path, 22, weight=500)
    date_font = load_font(serif_font_path, 42, weight=600)
    footer_font = load_font(font_path, 24, weight=500)
    footer_site_font = load_font(serif_font_path, 32, weight=600)
    page_font = load_font(serif_font_path, 31, weight=700)
    if not icon_path.is_file():
        raise StoryError(f"official brand icon not found: {icon_path}")
    with Image.open(icon_path) as source_icon:
        brand_icon = source_icon.convert("RGBA").resize(
            (146, 146), Image.Resampling.LANCZOS
        )
        footer_icon = source_icon.convert("RGBA").resize(
            (82, 82), Image.Resampling.LANCZOS
        )
    images: list[Image.Image] = []

    for page_number, page in enumerate(pages, start=1):
        image = Image.new("RGB", (STORY_WIDTH, STORY_HEIGHT), PAPER)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, STORY_WIDTH, 18), fill=INK)
        draw.rectangle((0, 18, STORY_WIDTH, 29), fill=ACCENT)
        image.paste(brand_icon, (CONTENT_LEFT, 54), brand_icon)
        draw.text(
            (CONTENT_LEFT + 174, 76),
            "剣道稽古ナビ",
            font=site_font,
            fill=INK,
        )
        draw.text(
            (CONTENT_LEFT + 174, 132),
            "kendo-keiko.com",
            font=domain_font,
            fill=ACCENT,
        )
        page_text = f"{page_number}/{len(pages)}"
        page_width = draw.textlength(page_text, font=page_font)
        pill_left = CONTENT_RIGHT - page_width - 46
        draw.rounded_rectangle(
            (pill_left, 72, CONTENT_RIGHT, 126),
            radius=27,
            fill=ACCENT,
        )
        draw.text((pill_left + 23, 76), page_text, font=page_font, fill=SURFACE)
        _draw_centered_text(
            draw,
            "今週末参加できる稽古会",
            y=226,
            font=heading_font,
            fill=INK,
        )
        _draw_divider(draw, 340)
        _draw_centered_text(
            draw,
            _format_target_dates(target_saturday),
            y=370,
            font=date_font,
            fill=ACCENT,
        )

        y, page_gap = _page_start_and_gap(page)
        for layout in page:
            bottom = y + layout.height
            draw.rounded_rectangle(
                (CONTENT_LEFT + 6, y + 8, CONTENT_RIGHT + 6, bottom + 8),
                radius=18,
                fill=SHADOW,
            )
            draw.rounded_rectangle(
                (CONTENT_LEFT, y, CONTENT_RIGHT, bottom),
                radius=18,
                fill=SURFACE,
                outline=WARM_LINE,
                width=2,
            )
            _draw_card_corners(draw, CONTENT_LEFT, y, CONTENT_RIGHT, bottom)
            datetime_text = (
                f"{_format_event_day(layout.event.event_date)}  "
                f"{_format_time(layout.event)}"
            )
            datetime_width = round(
                draw.textlength(datetime_text, font=fonts["small"])
            ) + 34
            draw.rounded_rectangle(
                (CARD_LEFT_X, y + 24, CARD_LEFT_X + datetime_width, y + 64),
                radius=14,
                fill=ACCENT,
            )
            draw.text(
                (CARD_LEFT_X + 17, y + 27),
                datetime_text,
                font=fonts["small"],
                fill=SURFACE,
            )
            left_cursor = y + 82
            left_cursor = _draw_lines(
                draw,
                layout.organization_lines or ("",),
                x=CARD_LEFT_X,
                y=left_cursor,
                font=fonts["org"],
                fill=INK,
                line_height=52,
            )
            left_cursor = _draw_lines(
                draw,
                layout.title_lines,
                x=CARD_LEFT_X,
                y=left_cursor,
                font=fonts["title"],
                fill=INK_SOFT,
                line_height=42,
            )
            _draw_participation_badges(
                draw,
                layout.event.participation_labels,
                x=CARD_LEFT_X,
                y=left_cursor + 9,
                font=fonts["small"],
            )
            draw.line(
                (CARD_DIVIDER_X, y + 86, CARD_DIVIDER_X, bottom - 28),
                fill=LINE,
                width=2,
            )
            right_cursor = y + 88
            draw.text(
                (CARD_RIGHT_X, right_cursor),
                "会場",
                font=fonts["body"],
                fill=ACCENT,
            )
            right_cursor = _draw_lines(
                draw,
                layout.venue_lines or ("未取得",),
                x=CARD_VALUE_X,
                y=right_cursor,
                font=fonts["body"],
                fill=INK_SOFT,
                line_height=38,
            )
            draw.text(
                (CARD_RIGHT_X, right_cursor),
                "地域",
                font=fonts["small"],
                fill=ACCENT,
            )
            right_cursor = _draw_lines(
                draw,
                layout.area_lines or ("未設定",),
                x=CARD_VALUE_X,
                y=right_cursor,
                font=fonts["small"],
                fill=INK_SOFT,
                line_height=36,
            )
            if layout.fee_lines:
                draw.text(
                    (CARD_RIGHT_X, right_cursor),
                    "参加費",
                    font=fonts["small"],
                    fill=ACCENT,
                )
                right_cursor = _draw_lines(
                    draw,
                    layout.fee_lines,
                    x=CARD_VALUE_X,
                    y=right_cursor,
                    font=fonts["small"],
                    fill=INK_SOFT,
                    line_height=35,
                )
            if layout.access_lines:
                draw.text(
                    (CARD_RIGHT_X, right_cursor),
                    "アクセス",
                    font=fonts["small"],
                    fill=ACCENT,
                )
                _draw_lines(
                    draw,
                    layout.access_lines,
                    x=CARD_VALUE_X,
                    y=right_cursor,
                    font=fonts["small"],
                    fill=INK_SOFT,
                    line_height=35,
                )
            y = bottom + page_gap

        draw.rectangle((0, 1682, STORY_WIDTH, 1820), fill=ACCENT)
        image.paste(footer_icon, (145, 1710), footer_icon)
        draw.text((247, 1726), "剣道稽古ナビ", font=footer_site_font, fill=SURFACE)
        draw.line((520, 1718, 520, 1788), fill=SURFACE, width=2)
        draw.text((552, 1730), "kendo-keiko.com", font=domain_font, fill=SURFACE)
        draw.rectangle((0, 1820, STORY_WIDTH, STORY_HEIGHT), fill=INK)
        warning = "参加前に必ず主催者の公式情報をご確認ください"
        warning_width = draw.textlength(warning, font=footer_font)
        draw.text(
            ((STORY_WIDTH - warning_width) / 2, 1857),
            "参加前に必ず主催者の公式情報をご確認ください",
            font=footer_font,
            fill=SURFACE,
        )
        images.append(image)

    return images


def output_paths(output: Path, page_count: int) -> list[Path]:
    if page_count < 1:
        raise StoryError("page_count must be at least 1")
    if output.suffix.lower() != ".png":
        raise StoryError("--output must end in .png")
    if page_count == 1:
        return [output]
    return [
        output.with_name(f"{output.stem}-{number:02d}{output.suffix}")
        for number in range(1, page_count + 1)
    ]


def save_story_pages(images: list[Image.Image], output: Path) -> list[Path]:
    paths = output_paths(output, len(images))
    output.parent.mkdir(parents=True, exist_ok=True)
    for image, path in zip(images, paths, strict=True):
        image.save(path, format="PNG", optimize=True)
    return paths
