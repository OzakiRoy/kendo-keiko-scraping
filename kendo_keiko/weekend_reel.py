from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from random import Random
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence
from urllib.parse import urljoin

import requests
from PIL import Image, ImageDraw

from kendo_keiko.static_site import PARTICIPATION_LABELS
from kendo_keiko.weekend_story import (
    ACCENT,
    ACCENT_SOFT,
    CARD_DIVIDER_X,
    CARD_GAP,
    CARD_LEFT_X,
    CARD_RIGHT_X,
    CARD_VALUE_X,
    CONTENT_BOTTOM,
    CONTENT_LEFT,
    CONTENT_RIGHT,
    CONTENT_TOP,
    DEFAULT_EVENTS_URL,
    DEFAULT_FONT_PATH,
    DEFAULT_ICON_PATH,
    DEFAULT_SERIF_FONT_PATH,
    INK,
    INK_SOFT,
    LINE,
    MAX_EVENTS_PER_PAGE,
    MIN_CARD_HEIGHT,
    PAPER,
    SHADOW,
    STORY_HEIGHT,
    STORY_WIDTH,
    SURFACE,
    WARM_LINE,
    EventLayout,
    LayoutOverflowError,
    NoEventsError,
    StoryError,
    _draw_card_corners,
    _draw_centered_text,
    _draw_divider,
    _draw_lines,
    _draw_participation_badges,
    _font_set,
    _format_event_day,
    _format_time,
    event_for_story,
    layout_event,
    load_font,
    paginate_layouts,
    validate_payload,
)


REEL_SCHEMA_VERSION = "instagram-reel-0.1"
REEL_VIDEO_WIDTH = STORY_WIDTH
REEL_VIDEO_HEIGHT = STORY_HEIGHT
REEL_FPS = 30
DEFAULT_PAGE_SECONDS = 6.0
MAX_VIDEO_SECONDS = 15 * 60
NO_EVENTS_EXIT_CODE = 3
SKIPPED_EXIT_CODE = 4
CONFIG_EXIT_CODE = 5
EXPECTED_STATUSES = frozenset({"active", "cancelled", "archived"})
OPEN_EVENT_TYPES = frozenset({"open_keiko", "federation_keiko"})


class ReelError(StoryError):
    """A deterministic, user-actionable Reel generation or publishing error."""


class ReelConfigError(ReelError):
    pass


class ReelUnknownResult(ReelError):
    """The API outcome cannot safely be retried without inspection."""

    def __init__(self, message: str, *, container_id: str | None = None) -> None:
        super().__init__(message)
        self.container_id = container_id


class DuplicateRunError(ReelError):
    pass


@dataclass(frozen=True)
class ReelEvent:
    story_event: Any
    event_type: str
    category_label: str

    @property
    def event_id(self) -> str:
        return self.story_event.event_id

    @property
    def event_date(self) -> str:
        return self.story_event.event_date


@dataclass(frozen=True)
class ReelSelection:
    target_friday: dt.date
    events: tuple[ReelEvent, ...]
    excluded: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class ScheduleDecision:
    target_friday: dt.date | None
    status: str
    reason: str | None = None


@dataclass(frozen=True)
class VideoProbe:
    width: int
    height: int
    duration_seconds: float
    video_codec: str
    audio_codec: str | None


@dataclass(frozen=True)
class ReelAssets:
    output_dir: Path
    video_path: Path
    cover_path: Path
    caption_path: Path
    manifest_path: Path
    manifest: dict[str, Any]
    probe: VideoProbe


def now_jst() -> dt.datetime:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))


def parse_target_friday(value: str) -> dt.date:
    try:
        target = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ReelError("--target-friday must use YYYY-MM-DD") from exc
    if target.weekday() != 4:
        raise ReelError("--target-friday must be a Friday")
    return target


def resolve_schedule(
    *, now: dt.datetime | None = None, explicit_friday: str | None = None
) -> ScheduleDecision:
    if explicit_friday is not None:
        return ScheduleDecision(parse_target_friday(explicit_friday), "explicit")
    current = (now or now_jst()).astimezone(dt.timezone(dt.timedelta(hours=9)))
    if current.weekday() == 2:  # Wednesday
        return ScheduleDecision((current + dt.timedelta(days=2)).date(), "scheduled")
    if current.weekday() == 3:  # Thursday catch-up
        return ScheduleDecision((current + dt.timedelta(days=1)).date(), "delayed")
    if current.weekday() >= 4:  # Do not publish after the target starts.
        return ScheduleDecision(
            current.date() - dt.timedelta(days=current.weekday() - 4),
            "skipped_late",
            "normal execution is limited to Wednesday or Thursday",
        )
    return ScheduleDecision(None, "skipped_early", "normal execution is Wednesday only")


def target_dates(target_friday: dt.date) -> tuple[dt.date, dt.date, dt.date]:
    return (
        target_friday,
        target_friday + dt.timedelta(days=1),
        target_friday + dt.timedelta(days=2),
    )


def target_date_label(target_friday: dt.date) -> str:
    sunday = target_friday + dt.timedelta(days=2)
    weekdays = "月火水木金土日"
    return (
        f"{target_friday.month}月{target_friday.day}日（{weekdays[target_friday.weekday()]}）"
        f"〜{sunday.month}月{sunday.day}日（{weekdays[sunday.weekday()]}）"
    )


def _required_string(event: Mapping[str, Any], key: str) -> str:
    value = event.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(key)
    return value


def _event_kind(event_type: str) -> tuple[str, str] | None:
    if event_type in OPEN_EVENT_TYPES:
        return event_type, "稽古会"
    if event_type == "adult_renseikai":
        return event_type, "大人向け錬成会・練習試合"
    return None


def _load_and_hash_bytes(path: Path) -> tuple[dict[str, Any], str]:
    try:
        data = path.read_bytes()
        payload = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReelError(f"failed to read events file: {path}") from exc
    try:
        validate_payload(payload)
    except StoryError as exc:
        raise ReelError(str(exc)) from exc
    return payload, hashlib.sha256(data).hexdigest()


def fetch_reel_payload(
    url: str = DEFAULT_EVENTS_URL,
    *,
    timeout: tuple[float, float] = (5.0, 20.0),
    session: requests.Session | None = None,
) -> tuple[dict[str, Any], str]:
    client = session or requests
    try:
        response = client.get(url, timeout=timeout)
        response.raise_for_status()
        data = response.content
    except requests.RequestException as exc:
        raise ReelError("failed to fetch events.json") from exc
    if len(data) > 5 * 1024 * 1024:
        raise ReelError("events.json exceeds the response size limit")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReelError("events.json is not valid JSON") from exc
    try:
        validate_payload(payload)
    except StoryError as exc:
        raise ReelError(str(exc)) from exc
    return payload, hashlib.sha256(data).hexdigest()


def select_reel_events(
    payload: dict[str, Any],
    target_friday: dt.date,
    *,
    areas: Sequence[str] | None = None,
) -> ReelSelection:
    try:
        validate_payload(payload)
    except StoryError as exc:
        raise ReelError(str(exc)) from exc
    dates = {date.isoformat() for date in target_dates(target_friday)}
    area_filter = {area for area in (areas or ()) if area}
    selected: list[ReelEvent] = []
    excluded: list[dict[str, str]] = []
    for index, raw in enumerate(payload["events"]):
        if not isinstance(raw, dict):
            raise ReelError(f"event at index {index} must be an object")
        event_date = raw.get("event_date")
        try:
            parsed_date = dt.date.fromisoformat(event_date)
        except (TypeError, ValueError) as exc:
            raise ReelError(f"event at index {index} has an invalid event_date") from exc
        if parsed_date.isoformat() not in dates:
            continue
        event_id = str(raw.get("event_id") or f"index-{index}")
        status = raw.get("status", "active")
        if status not in EXPECTED_STATUSES:
            raise ReelError(f"event {event_id} has an invalid status")
        if status != "active":
            excluded.append({"event_id": event_id, "reason": f"status={status}"})
            continue
        area = raw.get("area")
        if not isinstance(area, str) or not area.strip():
            excluded.append({"event_id": event_id, "reason": "area is missing"})
            continue
        if area_filter and area not in area_filter:
            excluded.append({"event_id": event_id, "reason": "area filtered"})
            continue
        kind = _event_kind(str(raw.get("event_type") or ""))
        if kind is None:
            excluded.append({"event_id": event_id, "reason": "event_type is not publishable"})
            continue
        missing: list[str] = []
        for key in ("event_id", "organization_id", "organization_name", "title", "venue"):
            try:
                _required_string(raw, key)
            except ValueError:
                missing.append(key)
        if missing:
            excluded.append({"event_id": event_id, "reason": "missing=" + ",".join(missing)})
            continue
        try:
            story_event = event_for_story(raw)
        except StoryError as exc:
            excluded.append({"event_id": event_id, "reason": f"invalid metadata: {exc}"})
            continue
        selected.append(
            ReelEvent(story_event=story_event, event_type=kind[0], category_label=kind[1])
        )
    selected.sort(
        key=lambda event: (
            event.story_event.event_date,
            event.story_event.start_time,
            event.story_event.organization_id,
            event.story_event.event_id,
        )
    )
    return ReelSelection(target_friday, tuple(selected), tuple(excluded))


@dataclass(frozen=True)
class ReelLayout:
    event: ReelEvent
    organization_lines: tuple[str, ...]
    title_lines: tuple[str, ...]
    details: tuple[tuple[str, str, tuple[str, ...]], ...]
    height: int


@dataclass(frozen=True)
class ReelPage:
    kind: str
    date: dt.date | None
    events: tuple[ReelEvent, ...] = ()
    part_label: str | None = None


def _reel_wrap_text(draw: ImageDraw.ImageDraw, text: str, font: Any, max_width: int) -> tuple[str, ...]:
    """Wrap Japanese at characters but keep latin words such as ``kent`` intact."""
    if not text:
        return ()
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9&'./_+-]*|[0-9]+|.", text, flags=re.S)
    lines: list[str] = []
    current = ""
    for token in tokens:
        candidate = current + token
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
            continue
        if current.strip():
            lines.append(current.rstrip())
            current = token.lstrip()
        else:
            # A genuinely oversized token is the only case where character wrapping is allowed.
            for character in token:
                if current and draw.textlength(current + character, font=font) > max_width:
                    lines.append(current)
                    current = ""
                current += character
    if current:
        lines.append(current.rstrip())
    return tuple(lines)


def _draw_centered(draw: ImageDraw.ImageDraw, text: str, y: int, font: Any, fill: str) -> None:
    width = draw.textlength(text, font=font)
    draw.text(((STORY_WIDTH - width) / 2, y), text, font=font, fill=fill)


def _paper_background(seed: int) -> Image.Image:
    rng = Random(seed)
    texture = Image.new("RGB", (180, 320), PAPER)
    pixels = texture.load()
    for y in range(texture.height):
        for x in range(texture.width):
            delta = rng.randrange(-5, 6)
            pixels[x, y] = tuple(max(0, min(255, int(value) + delta)) for value in (243, 241, 236))
    return texture.resize((STORY_WIDTH, STORY_HEIGHT), Image.Resampling.BICUBIC)


def _draw_cloud(draw: ImageDraw.ImageDraw, x: int, y: int, scale: float = 1.0) -> None:
    fill = "#eee6df"
    for left, top, width, height in ((0, 34, 180, 28), (46, 0, 116, 38), (112, 48, 180, 28), (210, 22, 140, 28)):
        draw.rounded_rectangle(
            (x + int(left * scale), y + int(top * scale), x + int((left + width) * scale), y + int((top + height) * scale)),
            radius=int(14 * scale), fill=fill,
        )


def _draw_mountains(draw: ImageDraw.ImageDraw) -> None:
    draw.polygon([(0, 1570), (170, 1405), (310, 1540), (490, 1370), (650, 1530), (835, 1390), (1080, 1535), (1080, 1810), (0, 1810)], fill="#e7ddd5")
    draw.polygon([(0, 1650), (190, 1480), (380, 1610), (545, 1450), (740, 1630), (900, 1485), (1080, 1600), (1080, 1810), (0, 1810)], fill="#eee7df")
    for offset, color in ((0, "#cfc0b4"), (30, "#d9cbc0"), (64, "#ded2c8")):
        points = [(0, 1690 + offset), (140, 1530 + offset), (260, 1660 + offset), (430, 1515 + offset), (590, 1680 + offset), (760, 1535 + offset), (930, 1685 + offset), (1080, 1560 + offset)]
        draw.line(points, fill=color, width=3, joint="curve")


def _draw_enso(draw: ImageDraw.ImageDraw) -> None:
    draw.arc((350, 1410, 810, 1870), start=198, end=520, fill="#d7c7bd", width=14)
    draw.arc((366, 1426, 794, 1854), start=200, end=515, fill="#e5d8d0", width=5)


def _draw_shinai_and_men(draw: ImageDraw.ImageDraw) -> None:
    # Minimal line-art decorations keep the supplied reference's kendo motif without baking text into a background.
    draw.line((120, 1770, 930, 1515), fill="#5c3429", width=24)
    draw.line((120, 1770, 930, 1515), fill="#9a6550", width=7)
    draw.line((205, 1788, 1000, 1580), fill="#4e2b25", width=14)
    draw.ellipse((855, 1435, 1110, 1795), fill="#482b29", outline="#2d1b1b", width=8)
    draw.ellipse((882, 1462, 1085, 1765), outline="#b58f7e", width=12)
    for x in range(895, 1088, 30):
        draw.line((x, 1475, x - 2, 1755), fill="#d5b3a0", width=7)
    for y in range(1510, 1755, 34):
        draw.line((887, y, 1080, y + 4), fill="#8e6659", width=5)


def _draw_background(image: Image.Image, *, seed: int, footer: bool = True) -> ImageDraw.ImageDraw:
    texture = _paper_background(seed)
    image.paste(texture)
    draw = ImageDraw.Draw(image)
    _draw_cloud(draw, -95, 45, 0.9)
    _draw_cloud(draw, 870, 280, 0.75)
    _draw_mountains(draw)
    _draw_enso(draw)
    _draw_shinai_and_men(draw)
    if footer:
        draw.rectangle((0, 1780, STORY_WIDTH, STORY_HEIGHT), fill=ACCENT)
        draw.line((72, 1820, 250, 1820), fill="#f7e8e3", width=2)
        draw.line((830, 1820, 1008, 1820), fill="#f7e8e3", width=2)
    return draw


def _draw_header(image: Image.Image, draw: ImageDraw.ImageDraw, icon: Image.Image, *, y: int = 88) -> None:
    icon_size = 130
    scaled_icon = icon.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
    image.paste(scaled_icon, (92, y), scaled_icon)
    title_font = load_font(DEFAULT_SERIF_FONT_PATH, 48, weight=700)
    english_font = load_font(DEFAULT_FONT_PATH, 18, weight=500)
    draw.text((252, y + 22), "剣道稽古ナビ", font=title_font, fill=INK)
    draw.line((254, y + 98, 300, y + 98), fill=ACCENT, width=3)
    draw.text((315, y + 88), "KENDO KEIKO NAVI", font=english_font, fill=INK_SOFT)
    draw.line((690, y + 98, 735, y + 98), fill=ACCENT, width=3)
    draw.line((982, y - 18, 982, y + 145), fill=ACCENT, width=3)
    vertical = "稽古でつながる\n剣道の今を、\nもっと身近に。"
    small = load_font(DEFAULT_SERIF_FONT_PATH, 25, weight=600)
    for row, line in enumerate(vertical.splitlines()):
        draw.text((865, y - 9 + row * 42), line, font=small, fill=INK)


def _draw_footer(draw: ImageDraw.ImageDraw, *, cta: bool = False) -> None:
    footer_font = load_font(DEFAULT_SERIF_FONT_PATH, 30 if cta else 25, weight=600)
    domain_font = load_font(DEFAULT_SERIF_FONT_PATH, 32, weight=600)
    globe_x, globe_y = 320, 1834
    draw.ellipse((globe_x - 22, globe_y - 22, globe_x + 22, globe_y + 22), outline="#fffaf4", width=3)
    draw.arc((globe_x - 11, globe_y - 21, globe_x + 11, globe_y + 21), 90, 270, fill="#fffaf4", width=2)
    draw.arc((globe_x - 11, globe_y - 21, globe_x + 11, globe_y + 21), 270, 90, fill="#fffaf4", width=2)
    draw.line((globe_x - 20, globe_y, globe_x + 20, globe_y), fill="#fffaf4", width=2)
    draw.line((370, 1805, 370, 1865), fill="#fffaf4", width=2)
    draw.text((402, 1812), "kendo-keiko.com", font=domain_font, fill="#fffaf4")
    if cta:
        warning = "参加前に必ず公式情報をご確認ください"
        width = draw.textlength(warning, font=footer_font)
        draw.text(((STORY_WIDTH - width) / 2, 1870), warning, font=footer_font, fill="#fffaf4")
    else:
        draw.text((690, 1870), "参加前に公式情報をご確認ください", font=load_font(DEFAULT_FONT_PATH, 20, weight=500), fill="#fffaf4")


def _draw_icon(draw: ImageDraw.ImageDraw, x: int, y: int, kind: str) -> None:
    draw.ellipse((x - 25, y - 25, x + 25, y + 25), fill=ACCENT)
    white = "#fffaf4"
    if kind == "time":
        draw.rectangle((x - 11, y - 10, x + 11, y + 12), outline=white, width=3)
        draw.line((x - 7, y - 15, x - 7, y - 7), fill=white, width=3)
        draw.line((x + 7, y - 15, x + 7, y - 7), fill=white, width=3)
        draw.line((x - 7, y - 1, x + 7, y - 1), fill=white, width=2)
    elif kind == "venue":
        draw.ellipse((x - 10, y - 15, x + 10, y + 7), outline=white, width=3)
        draw.polygon([(x - 10, y), (x, y + 17), (x + 10, y)], outline=white)
        draw.ellipse((x - 3, y - 8, x + 3, y - 2), outline=white, width=2)
    elif kind == "area":
        draw.line((x - 15, y - 10, x - 4, y - 15, x + 7, y - 10, x + 15, y - 15), fill=white, width=3)
        draw.line((x - 15, y + 12, x - 4, y + 7, x + 7, y + 12, x + 15, y + 7), fill=white, width=3)
        draw.line((x - 15, y - 10, x - 15, y + 12), fill=white, width=3)
        draw.line((x + 7, y - 10, x + 7, y + 12), fill=white, width=3)
    elif kind == "people":
        draw.ellipse((x - 11, y - 12, x - 1, y - 2), fill=white)
        draw.ellipse((x + 2, y - 11, x + 12, y - 1), fill=white)
        draw.arc((x - 16, y - 1, x + 5, y + 15), 180, 360, fill=white, width=3)
        draw.arc((x - 1, y, x + 18, y + 15), 180, 360, fill=white, width=3)
    else:
        draw.ellipse((x - 13, y - 10, x + 13, y - 1), outline=white, width=3)
        draw.arc((x - 13, y - 4, x + 13, y + 11), 0, 180, fill=white, width=3)
        draw.line((x - 13, y - 5, x - 13, y + 8), fill=white, width=3)
        draw.line((x + 13, y - 5, x + 13, y + 8), fill=white, width=3)


def layout_reel_event(draw: ImageDraw.ImageDraw, event: ReelEvent, fonts: dict[str, Any], *, min_height: int = 340) -> ReelLayout:
    value_width = 560
    organization_lines = _reel_wrap_text(draw, event.story_event.organization_name, fonts["org"], 760)
    title_lines = _reel_wrap_text(draw, event.story_event.title or "（名称未設定）", fonts["title"], 760)
    details: list[tuple[str, str, tuple[str, ...]]] = []
    values = (
        ("time", "時間", f"{event.story_event.start_time} - {event.story_event.end_time}".strip(" -"), fonts["body"]),
        ("venue", "会場", event.story_event.venue or "公式情報を確認", fonts["body"]),
        ("area", "エリア", event.story_event.area or "公式情報を確認", fonts["body"]),
        ("people", "参加条件", "／".join(event.story_event.participation_labels), fonts["body"]),
    )
    if event.story_event.fee:
        values += (("coin", "参加費", event.story_event.fee, fonts["body"]),)
    else:
        values += (("coin", "参加費", "公式情報を確認", fonts["body"]),)
    if event.story_event.access:
        values += (("area", "アクセス", event.story_event.access, fonts["body"]),)
    for kind, label, value, font in values:
        lines = _reel_wrap_text(draw, value, font, value_width) or ("公式情報を確認",)
        details.append((kind, label, lines))
    details_height = sum(max(28, len(lines) * 25) for _, _, lines in details)
    height = max(min_height, 70 + len(organization_lines) * 32 + len(title_lines) * 30 + details_height + 16)
    if height > 920:
        raise LayoutOverflowError(f"event card does not fit on one Reel page: {event.event_id}")
    return ReelLayout(event, organization_lines, title_lines, tuple(details), height)


def build_reel_pages(events: Sequence[ReelEvent], target_friday: dt.date) -> tuple[ReelPage, ...]:
    if not events:
        raise NoEventsError("no publishable events for the target weekend")
    pages: list[ReelPage] = [ReelPage("cover", None)]
    weekdays = "月火水木金土日"
    measuring = ImageDraw.Draw(Image.new("RGB", (STORY_WIDTH, STORY_HEIGHT), PAPER))
    fonts = {
        "org": load_font(DEFAULT_SERIF_FONT_PATH, 31, weight=700),
        "title": load_font(DEFAULT_SERIF_FONT_PATH, 39, weight=700),
        "body": load_font(DEFAULT_FONT_PATH, 27, weight=500),
    }
    for day in target_dates(target_friday):
        day_events = tuple(event for event in events if event.story_event.event_date == day.isoformat())
        if not day_events:
            continue
        chunks: list[tuple[ReelEvent, ...]] = []
        current: list[ReelEvent] = []
        for event in day_events:
            candidate = [*current, event]
            minimum = {1: 790, 2: 505, 3: 340}[min(3, len(candidate))]
            layouts = [layout_reel_event(measuring, item, fonts, min_height=minimum) for item in candidate]
            candidate_height = sum(item.height for item in layouts) + 24 * (len(layouts) - 1)
            if current and (len(candidate) > 3 or candidate_height > 1080):
                chunks.append(tuple(current))
                current = [event]
            else:
                current = candidate
        if current:
            chunks.append(tuple(current))
        for index, chunk in enumerate(chunks, start=1):
            label = f"{weekdays[day.weekday()]}曜" if len(chunks) == 1 else f"{weekdays[day.weekday()]}曜 {index}/{len(chunks)}"
            pages.append(ReelPage("day", day, tuple(chunk), label))
    pages.append(ReelPage("cta", None))
    return tuple(pages)


def reel_page_durations(pages: Sequence[ReelPage], page_seconds: float) -> tuple[float, ...]:
    durations: list[float] = []
    for page in pages:
        if page.kind == "cover" or page.kind == "cta":
            multiplier = 0.95
        else:
            multiplier = {1: 1.25, 2: 1.12, 3: 1.0}[min(3, len(page.events))]
        durations.append(round(max(3.0, page_seconds * multiplier), 2))
    return tuple(durations)


def _draw_event_card(draw: ImageDraw.ImageDraw, layout: ReelLayout, *, x: int, y: int, number: int) -> None:
    right = STORY_WIDTH - 52
    bottom = y + layout.height
    draw.rounded_rectangle((x + 5, y + 7, right + 5, bottom + 7), radius=18, fill="#d9cec6")
    draw.rounded_rectangle((x, y, right, bottom), radius=18, fill="#fffdfa", outline="#bea999", width=2)
    strip_right = x + 138
    draw.rounded_rectangle((x + 8, y + 8, strip_right, bottom - 8), radius=13, fill=ACCENT)
    draw.rectangle((x + 8, y + 40, strip_right, bottom - 40), fill=ACCENT)
    draw.text((x + 40, y + 48), f"{number:02d}", font=load_font(DEFAULT_SERIF_FONT_PATH, 56, weight=700), fill="#fffaf4")
    draw.line((x + 36, y + 128, x + 108, y + 128), fill="#fffaf4", width=2)
    cursor = y + 30
    content_x = strip_right + 42
    draw.text((content_x, cursor), "稽古会" if layout.event.event_type != "adult_renseikai" else "大人向け錬成会・練習試合", font=load_font(DEFAULT_FONT_PATH, 20, weight=600), fill=ACCENT)
    cursor += 30
    cursor = _draw_lines(draw, layout.organization_lines, x=content_x, y=cursor, font=load_font(DEFAULT_SERIF_FONT_PATH, 31, weight=700), fill=ACCENT, line_height=36)
    cursor += 4
    cursor = _draw_lines(draw, layout.title_lines, x=content_x, y=cursor, font=load_font(DEFAULT_SERIF_FONT_PATH, 36, weight=700), fill=INK, line_height=39)
    draw.line((content_x, cursor + 8, right - 32, cursor + 8), fill=ACCENT, width=2)
    cursor += 28
    label_x = content_x + 5
    value_x = content_x + 188
    for kind, label, lines in layout.details:
        row_height = max(28, len(lines) * 25)
        center = cursor + row_height // 2
        _draw_icon(draw, label_x, center, kind)
        draw.text((content_x + 38, cursor + 5), label, font=load_font(DEFAULT_FONT_PATH, 23, weight=500), fill=INK_SOFT)
        draw.line((value_x - 20, cursor + 2, value_x - 20, cursor + row_height - 6), fill=ACCENT, width=2)
        _draw_lines(draw, lines, x=value_x, y=cursor + 2, font=load_font(DEFAULT_FONT_PATH, 23, weight=500), fill=INK, line_height=25)
        cursor += row_height


def _render_cover(target_friday: dt.date, icon: Image.Image) -> Image.Image:
    image = Image.new("RGB", (STORY_WIDTH, STORY_HEIGHT))
    draw = _draw_background(image, seed=17)
    _draw_header(image, draw, icon, y=105)
    large = load_font(DEFAULT_SERIF_FONT_PATH, 94, weight=700)
    huge_ink = load_font(DEFAULT_SERIF_FONT_PATH, 164, weight=700)
    date_font = load_font(DEFAULT_SERIF_FONT_PATH, 54, weight=700)
    _draw_centered(draw, "今週末の", 380, large, ACCENT)
    _draw_centered(draw, "稽古会", 485, huge_ink, INK)
    draw.line((130, 680, 950, 680), fill=ACCENT, width=3)
    dates = "・".join(f"{day.month}/{day.day}（{('月火水木金土日')[day.weekday()]}）" for day in target_dates(target_friday))
    _draw_centered(draw, dates, 710, date_font, ACCENT)
    _draw_centered(draw, "参加できる稽古会をピックアップ", 825, load_font(DEFAULT_SERIF_FONT_PATH, 39, weight=600), INK)
    for index, (kind, text) in enumerate((("search", "日付・地域で探せる"), ("people", "参加条件も見やすく"), ("paper", "詳細はWebでチェック"))):
        cy = 990 + index * 102
        _draw_icon(draw, 215, cy, "area" if kind == "search" else "people" if kind == "people" else "coin")
        draw.line((260, cy - 25, 260, cy + 25), fill=ACCENT, width=2)
        draw.text((300, cy - 28), text, font=load_font(DEFAULT_SERIF_FONT_PATH, 31, weight=600), fill=INK)
    _draw_footer(draw)
    return image


def _render_day_page(page: ReelPage, total_pages: int, icon: Image.Image) -> Image.Image:
    image = Image.new("RGB", (STORY_WIDTH, STORY_HEIGHT))
    draw = _draw_background(image, seed=100 + int(page.date.strftime("%d")))
    _draw_header(image, draw, icon, y=64)
    day = page.date
    assert day is not None
    date_font = load_font(DEFAULT_SERIF_FONT_PATH, 142, weight=700)
    weekday_font = load_font(DEFAULT_SERIF_FONT_PATH, 54, weight=700)
    count_font = load_font(DEFAULT_SERIF_FONT_PATH, 34, weight=700)
    draw.text((150, 245), f"{day.month}/{day.day}", font=date_font, fill=ACCENT)
    draw.text((720, 325), f"（{('月火水木金土日')[day.weekday()]}）", font=weekday_font, fill=INK)
    count = f"{page.part_label}  {len(page.events)}件"
    count_width = draw.textlength(count, font=count_font) + 74
    left = (STORY_WIDTH - count_width) / 2
    draw.rounded_rectangle((left, 405, left + count_width, 470), radius=15, fill=ACCENT)
    draw.text((left + 37, 415), count, font=count_font, fill="#fffaf4")
    tagline = "今週末も、よい稽古を。" if len(page.events) <= 2 else "参加できる稽古会をピックアップ"
    _draw_centered(draw, tagline, 500, load_font(DEFAULT_SERIF_FONT_PATH, 34, weight=600), INK)
    draw.line((150, 550, 930, 550), fill=ACCENT, width=2)
    measuring = ImageDraw.Draw(Image.new("RGB", (STORY_WIDTH, STORY_HEIGHT), PAPER))
    fonts = {"org": load_font(DEFAULT_SERIF_FONT_PATH, 31, weight=700), "title": load_font(DEFAULT_SERIF_FONT_PATH, 39, weight=700), "body": load_font(DEFAULT_FONT_PATH, 27, weight=500)}
    min_height = {1: 790, 2: 505, 3: 340}[min(3, len(page.events))]
    layouts = [layout_reel_event(measuring, event, fonts, min_height=min_height) for event in page.events]
    total_height = sum(item.height for item in layouts) + 24 * (len(layouts) - 1)
    y = 590 + max(0, min(70, (1080 - total_height) // 2))
    for number, layout in enumerate(layouts, start=1):
        _draw_event_card(draw, layout, x=46, y=y, number=number)
        y += layout.height + 24
    _draw_footer(draw)
    return image


def _render_cta(icon: Image.Image) -> Image.Image:
    image = Image.new("RGB", (STORY_WIDTH, STORY_HEIGHT))
    draw = _draw_background(image, seed=99)
    _draw_header(image, draw, icon, y=105)
    _draw_centered(draw, "稽古会を探すなら", 390, load_font(DEFAULT_SERIF_FONT_PATH, 66, weight=700), INK)
    draw.text((92, 505), "剣道稽古", font=load_font(DEFAULT_SERIF_FONT_PATH, 130, weight=700), fill=ACCENT)
    draw.text((690, 505), "ナビ", font=load_font(DEFAULT_SERIF_FONT_PATH, 130, weight=700), fill=INK)
    draw.line((100, 670, 960, 670), fill="#d39b94", width=3)
    for index, text in enumerate(("日付・地域で探せる", "参加条件も見やすく整理", "掲載希望・情報修正はDMへ")):
        cy = 790 + index * 125
        _draw_icon(draw, 175, cy, ("area", "paper", "people")[index])
        draw.line((235, cy - 27, 235, cy + 27), fill=INK_SOFT, width=2)
        draw.text((280, cy - 31), text, font=load_font(DEFAULT_SERIF_FONT_PATH, 34, weight=600), fill=INK)
    draw.rounded_rectangle((90, 1180, 990, 1360), radius=24, fill=ACCENT)
    draw.text((170, 1205), "↗", font=load_font(DEFAULT_FONT_PATH, 78, weight=400), fill="#fffaf4")
    draw.line((286, 1210, 286, 1332), fill="#fffaf4", width=2)
    draw.text((350, 1200), "プロフィールの", font=load_font(DEFAULT_SERIF_FONT_PATH, 44, weight=700), fill="#fffaf4")
    draw.text((350, 1262), "リンクからチェック", font=load_font(DEFAULT_SERIF_FONT_PATH, 44, weight=700), fill="#fffaf4")
    _draw_centered(draw, "kendo-keiko.com", 1415, load_font(DEFAULT_SERIF_FONT_PATH, 44, weight=600), INK)
    _draw_centered(draw, "参加前に必ず主催者の公式情報をご確認ください", 1490, load_font(DEFAULT_SERIF_FONT_PATH, 27, weight=500), INK)
    _draw_footer(draw, cta=True)
    return image


def render_reel_frames(events: Sequence[ReelEvent], target_friday: dt.date, *, pages: Sequence[ReelPage] | None = None) -> list[Image.Image]:
    if not events:
        raise NoEventsError("no publishable events for the target weekend")
    page_list = tuple(pages or build_reel_pages(events, target_friday))
    if not DEFAULT_ICON_PATH.is_file():
        raise ReelError("official brand icon not found")
    with Image.open(DEFAULT_ICON_PATH) as source_icon:
        icon = source_icon.convert("RGBA")
        rendered: list[Image.Image] = []
        for page in page_list:
            if page.kind == "cover":
                rendered.append(_render_cover(target_friday, icon))
            elif page.kind == "day":
                rendered.append(_render_day_page(page, len(page_list), icon))
            else:
                rendered.append(_render_cta(icon))
        return rendered


def caption_for_reel(selection: ReelSelection) -> str:
    lines = [
        f"今週末（{target_date_label(selection.target_friday)}）の稽古会情報です。",
        "",
    ]
    for event in selection.events:
        item = event.story_event
        lines.append(f"{_format_event_day(item.event_date)} {_format_time(item)}")
        lines.append(f"{event.category_label}｜{item.organization_name}｜{item.title}")
        lines.append(f"会場: {item.venue}（{item.area}）")
        if item.fee:
            lines.append(f"参加費: {item.fee}")
        lines.append("参加条件: " + "／".join(item.participation_labels))
        lines.append("")
    lines.extend([
        "最新情報・詳細は公式情報とkendo-keiko.comをご確認ください。",
        "https://kendo-keiko.com/",
        "",
        "#剣道 #稽古会 #錬成会 #剣道稽古ナビ",
    ])
    return "\n".join(lines).strip() + "\n"


def get_ffmpeg_path() -> str:
    configured = os.environ.get("FFMPEG_BIN")
    if configured:
        if not Path(configured).is_file():
            raise ReelConfigError("FFMPEG_BIN does not point to a file")
        return configured
    discovered = shutil.which("ffmpeg")
    if discovered:
        return discovered
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as exc:
        raise ReelConfigError("ffmpeg is required; install requirements-story.txt") from exc


def _parse_ffmpeg_probe(stderr: str) -> VideoProbe:
    duration_match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
    video_match = re.search(r"Video: ([^,\s]+).*?(\d{2,5})x(\d{2,5})", stderr, re.S)
    audio_match = re.search(r"Audio: ([^,\s]+)", stderr)
    if not duration_match or not video_match:
        raise ReelError("could not inspect generated MP4 with ffmpeg")
    hours, minutes, seconds = duration_match.groups()
    return VideoProbe(
        width=int(video_match.group(2)),
        height=int(video_match.group(3)),
        duration_seconds=int(hours) * 3600 + int(minutes) * 60 + float(seconds),
        video_codec=video_match.group(1),
        audio_codec=audio_match.group(1) if audio_match else None,
    )


def probe_video(path: Path, *, ffmpeg_bin: str | None = None) -> VideoProbe:
    if not path.is_file() or path.stat().st_size == 0:
        raise ReelError("generated MP4 is missing or empty")
    ffprobe = os.environ.get("FFPROBE_BIN") or shutil.which("ffprobe")
    if ffprobe:
        try:
            result = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,codec_name", "-show_entries", "format=duration", "-of", "json", str(path)],
                check=True,
                capture_output=True,
                text=True,
            )
            data = json.loads(result.stdout)
            stream = data["streams"][0]
            audio = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name", "-of", "json", str(path)], check=True, capture_output=True, text=True)
            audio_data = json.loads(audio.stdout).get("streams", [])
            return VideoProbe(int(stream["width"]), int(stream["height"]), float(data["format"]["duration"]), stream["codec_name"], audio_data[0].get("codec_name") if audio_data else None)
        except (OSError, subprocess.CalledProcessError, KeyError, ValueError, json.JSONDecodeError) as exc:
            raise ReelError("ffprobe could not inspect generated MP4") from exc
    binary = ffmpeg_bin or get_ffmpeg_path()
    result = subprocess.run([binary, "-hide_banner", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True)
    return _parse_ffmpeg_probe(result.stderr)


def verify_video(probe: VideoProbe) -> None:
    if (probe.width, probe.height) != (REEL_VIDEO_WIDTH, REEL_VIDEO_HEIGHT):
        raise ReelError("Reel must be 1080x1920")
    if probe.video_codec not in {"h264", "avc1"}:
        raise ReelError(f"Reel video codec must be H.264: {probe.video_codec}")
    if probe.audio_codec not in {None, "aac"}:
        raise ReelError(f"Reel audio codec must be AAC or absent: {probe.audio_codec}")
    if not 3 <= probe.duration_seconds <= MAX_VIDEO_SECONDS:
        raise ReelError("Reel duration must be between 3 seconds and 15 minutes")


def _write_caption_and_manifest(
    output_dir: Path,
    *,
    selection: ReelSelection,
    input_sha256: str,
    source_url: str,
    caption: str,
    probe: VideoProbe,
    generated_at: str,
    mode: str,
    regions: Sequence[str],
    pages: Sequence[ReelPage],
    page_durations: Sequence[float],
) -> tuple[Path, Path, dict[str, Any]]:
    caption_path = output_dir / "caption.txt"
    manifest_path = output_dir / "manifest.json"
    caption_path.write_text(caption, encoding="utf-8")
    manifest = {
        "schema_version": REEL_SCHEMA_VERSION,
        "generated_at": generated_at,
        "mode": mode,
        "input": {
            "url": source_url,
            "sha256": input_sha256,
            "timezone": "Asia/Tokyo",
        },
        "target_friday": selection.target_friday.isoformat(),
        "target_dates": [date.isoformat() for date in target_dates(selection.target_friday)],
        "regions": list(regions),
        "pages": [
            {
                "kind": page.kind,
                "date": page.date.isoformat() if page.date else None,
                "label": page.part_label,
                "event_ids": [event.event_id for event in page.events],
                "file": f"page-{index:02d}.png",
                "duration_seconds": duration,
            }
            for index, (page, duration) in enumerate(zip(pages, page_durations), start=1)
        ],
        "events": [
            {
                "event_id": event.event_id,
                "event_date": event.story_event.event_date,
                "organization_name": event.story_event.organization_name,
                "title": event.story_event.title,
                "event_type": event.event_type,
                "category_label": event.category_label,
            }
            for event in selection.events
        ],
        "excluded": list(selection.excluded),
        "video": {
            "file": "reel.mp4",
            "cover": "cover.png",
            "width": probe.width,
            "height": probe.height,
            "duration_seconds": round(probe.duration_seconds, 3),
            "video_codec": probe.video_codec,
            "audio_codec": probe.audio_codec,
            "fps": REEL_FPS,
            "audio": "silent AAC track; no music attached",
        },
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return caption_path, manifest_path, manifest


def generate_reel_assets(
    selection: ReelSelection,
    *,
    input_sha256: str,
    output_dir: Path,
    mode: str = "dry_run",
    regions: Sequence[str] = (),
    source_url: str = DEFAULT_EVENTS_URL,
    page_seconds: float = DEFAULT_PAGE_SECONDS,
    generated_at: str | None = None,
) -> ReelAssets:
    if page_seconds < 3 or page_seconds > MAX_VIDEO_SECONDS:
        raise ReelError("page_seconds must be between 3 and 900")
    output_dir.mkdir(parents=True, exist_ok=True)
    pages = build_reel_pages(selection.events, selection.target_friday)
    page_durations = reel_page_durations(pages, page_seconds)
    frames = render_reel_frames(selection.events, selection.target_friday, pages=pages)
    caption = caption_for_reel(selection)
    with tempfile.TemporaryDirectory(prefix="kendo-reel-frames-") as frame_dir:
        frame_root = Path(frame_dir)
        for number, image in enumerate(frames, start=1):
            image.save(frame_root / f"frame-{number:05d}.png", format="PNG")
            image.save(output_dir / f"page-{number:02d}.png", format="PNG", optimize=True)
        cover_path = output_dir / "cover.png"
        frames[0].save(cover_path, format="PNG", optimize=True)
        video_path = output_dir / "reel.mp4"
        ffmpeg = get_ffmpeg_path()
        concat_path = frame_root / "frames.txt"
        concat_lines: list[str] = []
        for number, duration in enumerate(page_durations, start=1):
            frame_path = (frame_root / f"frame-{number:05d}.png").as_posix()
            concat_lines.extend((f"file '{frame_path}'", f"duration {duration:g}"))
        # The concat demuxer applies the final duration only when the final frame is repeated.
        concat_lines.append(f"file '{(frame_root / f'frame-{len(frames):05d}.png').as_posix()}'")
        concat_path.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_path),
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=48000:cl=stereo",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-profile:v",
                "high",
                "-r",
                str(REEL_FPS),
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-shortest",
                "-movflags",
                "+faststart",
                str(video_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ReelError("ffmpeg failed while encoding the Reel")
    probe = probe_video(video_path, ffmpeg_bin=ffmpeg)
    verify_video(probe)
    generated = generated_at or now_jst().isoformat(timespec="seconds")
    caption_path, manifest_path, manifest = _write_caption_and_manifest(
        output_dir,
        selection=selection,
        input_sha256=input_sha256,
        source_url=source_url,
        caption=caption,
        probe=probe,
        generated_at=generated,
        mode=mode,
        regions=regions,
        pages=pages,
        page_durations=page_durations,
    )
    return ReelAssets(output_dir, video_path, cover_path, caption_path, manifest_path, manifest, probe)


@dataclass(frozen=True)
class InstagramApiConfig:
    auth_mode: str
    api_version: str
    user_id: str
    username: str
    access_token: str = field(default="", repr=False)
    base_url: str | None = None

    @property
    def host(self) -> str:
        if self.base_url:
            return self.base_url.rstrip("/")
        return "https://graph.instagram.com" if self.auth_mode == "instagram_login" else "https://graph.facebook.com"

    @classmethod
    def from_env(cls) -> "InstagramApiConfig":
        mode = os.environ.get("INSTAGRAM_AUTH_MODE", "").strip()
        if mode not in {"instagram_login", "facebook_login"}:
            raise ReelConfigError("INSTAGRAM_AUTH_MODE must be instagram_login or facebook_login")
        version = os.environ.get("INSTAGRAM_GRAPH_API_VERSION", "v25.0").strip()
        if not re.fullmatch(r"v\d+\.\d+", version):
            raise ReelConfigError("INSTAGRAM_GRAPH_API_VERSION must look like v25.0")
        user_id = os.environ.get("INSTAGRAM_USER_ID", "").strip()
        username = os.environ.get("INSTAGRAM_USERNAME", "").strip()
        token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
        if not user_id or not username or not token:
            raise ReelConfigError("Instagram destination and token are not configured")
        return cls(mode, version, user_id, username, token)

    def validate(self) -> None:
        if self.auth_mode not in {"instagram_login", "facebook_login"}:
            raise ReelConfigError("unsupported Instagram auth mode")
        if not self.user_id or not self.username or not self.access_token:
            raise ReelConfigError("Instagram destination and token are required")


class InstagramApiClient:
    def __init__(
        self,
        config: InstagramApiConfig,
        *,
        session: requests.Session | Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        poll_interval: float = 15.0,
        poll_timeout: float = 900.0,
        max_retries: int = 2,
    ) -> None:
        config.validate()
        self.config = config
        self.session = session or requests.Session()
        self.sleep = sleep
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self.max_retries = max_retries

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        retry: bool = True,
        unknown_on_transport: bool = False,
    ) -> dict[str, Any]:
        safe_params = dict(params or {})
        safe_params["access_token"] = self.config.access_token
        url = f"{self.config.host}/{self.config.api_version}/{self.config.user_id if path.startswith('/') is False else ''}{path.lstrip('/')}"
        attempts = self.max_retries + 1 if retry else 1
        for attempt in range(attempts):
            try:
                response = self.session.request(method, url, params=safe_params, timeout=(5.0, 30.0))
                data = response.json()
            except (OSError, requests.RequestException, ValueError) as exc:
                if attempt + 1 < attempts:
                    self.sleep(min(2 ** attempt, 8))
                    continue
                if unknown_on_transport:
                    raise ReelUnknownResult(
                        f"Instagram API response is unknown: {method} {path}"
                    ) from exc
                raise ReelError(f"Instagram API request failed: {method} {path}") from exc
            if response.status_code >= 400 or "error" in data:
                raise ReelError(f"Instagram API rejected request: {method} {path}")
            return data
        raise ReelError(f"Instagram API request failed: {method} {path}")

    def verify_destination(self) -> dict[str, Any]:
        data = self._request("GET", f"/{self.config.user_id}", params={"fields": "id,username,account_type"})
        if str(data.get("id")) != self.config.user_id or str(data.get("username")) != self.config.username:
            raise ReelConfigError("configured Instagram destination does not match API response")
        account_type = data.get("account_type")
        if account_type is not None and str(account_type).upper() not in {"BUSINESS", "CREATOR"}:
            raise ReelConfigError("configured Instagram account is not a professional account")
        return {"id": data.get("id"), "username": data.get("username"), "account_type": account_type}

    def create_reel_container(self, *, video_url: str, caption: str) -> str:
        data = self._request(
            "POST",
            f"/{self.config.user_id}/media",
            params={"media_type": "REELS", "video_url": video_url, "caption": caption, "share_to_feed": "false"},
            retry=False,
            unknown_on_transport=True,
        )
        container_id = data.get("id")
        if not isinstance(container_id, str) or not container_id:
            raise ReelError("Instagram API returned no container ID")
        return container_id

    def wait_for_container(self, container_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.poll_timeout
        while True:
            data = self._request("GET", f"/{container_id}", params={"fields": "status_code,status"}, retry=True)
            status = str(data.get("status_code") or "").upper()
            if status in {"FINISHED", "READY"}:
                return data
            if status in {"ERROR", "EXPIRED"}:
                raise ReelError("Instagram Reel container processing failed")
            if time.monotonic() >= deadline:
                raise ReelUnknownResult("Instagram Reel container processing timed out", container_id=container_id)
            self.sleep(self.poll_interval)

    def publish_container(self, container_id: str) -> str:
        try:
            data = self._request("POST", f"/{self.config.user_id}/media_publish", params={"creation_id": container_id}, retry=False)
        except ReelError as exc:
            raise ReelUnknownResult("Instagram publish response is unknown", container_id=container_id) from exc
        media_id = data.get("id")
        if not isinstance(media_id, str) or not media_id:
            raise ReelUnknownResult("Instagram publish response did not include a media ID", container_id=container_id)
        return media_id

    def permalink(self, media_id: str) -> str | None:
        data = self._request("GET", f"/{media_id}", params={"fields": "id,permalink"}, retry=True)
        value = data.get("permalink")
        return value if isinstance(value, str) and value else None


class ReelStateStore:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.state_path = state_dir / "state.json"
        self.history_path = state_dir / "history.jsonl"
        self.lock_path = state_dir / ".lock"

    @contextlib.contextmanager
    def lock(self) -> Iterator[None]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ReelError("another Reel run is already in progress") from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"schema_version": REEL_SCHEMA_VERSION, "runs": {}}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReelError("Instagram Reel state file is invalid") from exc
        if data.get("schema_version") != REEL_SCHEMA_VERSION or not isinstance(data.get("runs"), dict):
            raise ReelError("unsupported Instagram Reel state schema")
        return data

    def get(self, key: str) -> dict[str, Any] | None:
        return self.load()["runs"].get(key)

    def record(self, key: str, record: dict[str, Any]) -> None:
        data = self.load()
        data["runs"][key] = record
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.state_path)
        with self.history_path.open("a", encoding="utf-8") as history:
            history.write(json.dumps({"key": key, **record}, ensure_ascii=False) + "\n")


def run_key(destination_id: str, target_friday: dt.date) -> str:
    return f"{destination_id}:{target_friday.isoformat()}"


def should_skip_existing(record: dict[str, Any] | None) -> bool:
    return record is not None and record.get("status") in {
        "published",
        "unknown",
        "publishing",
        "container_processing",
    }


class S3VideoStore:
    def __init__(self, *, bucket: str, public_base_url: str, prefix: str = "instagram-reels", s3_client: Any | None = None, http_get: Callable[..., Any] = requests.get) -> None:
        self.bucket = bucket
        self.public_base_url = public_base_url.rstrip("/")
        self.prefix = prefix.strip("/")
        self.http_get = http_get
        if s3_client is None:
            import boto3

            s3_client = boto3.client("s3")
        self.s3 = s3_client

    def upload(self, path: Path, *, target_friday: dt.date, input_sha256: str) -> str:
        key = f"{self.prefix}/{target_friday.isoformat()}-{input_sha256[:16]}.mp4"
        self.s3.upload_file(str(path), self.bucket, key, ExtraArgs={"ContentType": "video/mp4", "CacheControl": "no-store"})
        self.s3.head_object(Bucket=self.bucket, Key=key)
        url = urljoin(self.public_base_url + "/", key)
        try:
            response = self.http_get(url, headers={"Range": "bytes=0-7"}, timeout=(5.0, 20.0), stream=True)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ReelError("uploaded Reel video is not reachable from the public URL") from exc
        return url


def create_default_s3_store() -> S3VideoStore:
    bucket = os.environ.get("INSTAGRAM_REEL_VIDEO_BUCKET", "").strip()
    base = os.environ.get("INSTAGRAM_REEL_VIDEO_PUBLIC_BASE_URL", "").strip()
    if not bucket or not base:
        raise ReelConfigError("S3 video bucket and public base URL are not configured")
    return S3VideoStore(bucket=bucket, public_base_url=base, prefix=os.environ.get("INSTAGRAM_REEL_VIDEO_PREFIX", "instagram-reels"))
