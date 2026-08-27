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

PAPER = "#f3f1ec"
SURFACE = "#fffdfa"
INK = "#1b1b1b"
INK_SOFT = "#42403c"
MUTED = "#706d67"
ACCENT = "#8c1d24"
LINE = "#d6d1c8"

CONTENT_LEFT = 64
CONTENT_RIGHT = STORY_WIDTH - 64
CONTENT_TOP = 300
CONTENT_BOTTOM = 1740
CARD_GAP = 22


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


def _font_set(font_path: Path) -> dict[str, ImageFont.FreeTypeFont]:
    return {
        "org": load_font(font_path, 35, weight=700),
        "title": load_font(font_path, 29, weight=600),
        "body": load_font(font_path, 26, weight=400),
        "small": load_font(font_path, 23, weight=500),
    }


def layout_event(
    draw: ImageDraw.ImageDraw,
    event: StoryEvent,
    fonts: dict[str, ImageFont.FreeTypeFont],
) -> EventLayout:
    text_width = CONTENT_RIGHT - CONTENT_LEFT - 64
    organization_lines = wrap_text(
        draw, event.organization_name, fonts["org"], text_width
    )
    title_lines = wrap_text(draw, event.title, fonts["title"], text_width)
    venue_lines = wrap_text(
        draw, event.venue, fonts["body"], text_width - 74
    )
    area_lines = wrap_text(
        draw, event.area, fonts["small"], text_width - 74
    )
    fee_lines = wrap_text(
        draw, event.fee or "", fonts["small"], text_width - 74
    )

    height = 52
    height += max(1, len(organization_lines)) * 46
    height += len(title_lines) * 39
    height += 42
    height += max(1, len(venue_lines)) * 35
    height += max(1, len(area_lines)) * 34
    height += len(fee_lines) * 32
    height += 28

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


def _format_target_dates(target: dt.date) -> str:
    sunday = target + dt.timedelta(days=1)
    return f"{target.month}月{target.day}日（土）・{sunday.month}月{sunday.day}日（日）"


def render_story_pages(
    events: list[StoryEvent],
    target_saturday: dt.date,
    *,
    font_path: Path = DEFAULT_FONT_PATH,
) -> list[Image.Image]:
    if not events:
        raise NoEventsError("no published events for the target weekend")

    measuring_image = Image.new("RGB", (STORY_WIDTH, STORY_HEIGHT), PAPER)
    measuring_draw = ImageDraw.Draw(measuring_image)
    fonts = _font_set(font_path)
    layouts = [layout_event(measuring_draw, event, fonts) for event in events]
    pages = paginate_layouts(layouts)

    heading_font = load_font(font_path, 54, weight=700)
    date_font = load_font(font_path, 31, weight=500)
    footer_font = load_font(font_path, 24, weight=500)
    page_font = load_font(font_path, 22, weight=500)
    images: list[Image.Image] = []

    for page_number, page in enumerate(pages, start=1):
        image = Image.new("RGB", (STORY_WIDTH, STORY_HEIGHT), PAPER)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, STORY_WIDTH, 18), fill=INK)
        draw.rectangle((0, 18, STORY_WIDTH, 29), fill=ACCENT)
        draw.text(
            (CONTENT_LEFT, 82),
            "今週末参加できる稽古会",
            font=heading_font,
            fill=INK,
        )
        draw.text(
            (CONTENT_LEFT, 165),
            _format_target_dates(target_saturday),
            font=date_font,
            fill=ACCENT,
        )
        draw.text(
            (CONTENT_LEFT, 222),
            f"{page_number} / {len(pages)}",
            font=page_font,
            fill=MUTED,
        )

        y = CONTENT_TOP
        for layout in page:
            bottom = y + layout.height
            draw.rounded_rectangle(
                (CONTENT_LEFT, y, CONTENT_RIGHT, bottom),
                radius=22,
                fill=SURFACE,
                outline=LINE,
                width=2,
            )
            x = CONTENT_LEFT + 32
            cursor = y + 24
            date_and_time = f"{layout.event.event_date}  {_format_time(layout.event)}"
            draw.text((x, cursor), date_and_time, font=fonts["small"], fill=ACCENT)
            cursor += 42
            cursor = _draw_lines(
                draw,
                layout.organization_lines or ("",),
                x=x,
                y=cursor,
                font=fonts["org"],
                fill=INK,
                line_height=46,
            )
            cursor = _draw_lines(
                draw,
                layout.title_lines,
                x=x,
                y=cursor,
                font=fonts["title"],
                fill=INK_SOFT,
                line_height=39,
            )
            labels = "  /  ".join(layout.event.participation_labels)
            draw.text((x, cursor + 5), labels, font=fonts["small"], fill=ACCENT)
            cursor += 42
            draw.text((x, cursor), "会場", font=fonts["body"], fill=MUTED)
            cursor = _draw_lines(
                draw,
                layout.venue_lines or ("未取得",),
                x=x + 74,
                y=cursor,
                font=fonts["body"],
                fill=INK_SOFT,
                line_height=35,
            )
            draw.text((x, cursor), "地域", font=fonts["small"], fill=MUTED)
            cursor = _draw_lines(
                draw,
                layout.area_lines or ("未設定",),
                x=x + 74,
                y=cursor,
                font=fonts["small"],
                fill=INK_SOFT,
                line_height=34,
            )
            if layout.fee_lines:
                draw.text((x, cursor), "参加費", font=fonts["small"], fill=MUTED)
                _draw_lines(
                    draw,
                    layout.fee_lines,
                    x=x + 88,
                    y=cursor,
                    font=fonts["small"],
                    fill=INK_SOFT,
                    line_height=32,
                )
            y = bottom + CARD_GAP

        draw.line((CONTENT_LEFT, 1790, CONTENT_RIGHT, 1790), fill=LINE, width=2)
        draw.text((CONTENT_LEFT, 1818), "詳しくは kendo-keiko.com", font=footer_font, fill=INK)
        draw.text(
            (CONTENT_LEFT, 1860),
            "参加前に必ず主催者の公式情報をご確認ください",
            font=footer_font,
            fill=MUTED,
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
