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
    base: EventLayout
    category_label: str
    height: int

    @property
    def event(self) -> Any:
        return self.base.event


def layout_reel_event(draw: ImageDraw.ImageDraw, event: ReelEvent, fonts: dict[str, Any]) -> ReelLayout:
    base = layout_event(draw, event.story_event, fonts)
    height = base.height + 44
    available = CONTENT_BOTTOM - CONTENT_TOP
    if height > available:
        raise LayoutOverflowError(f"event does not fit on one Reel page: {event.event_id}")
    return ReelLayout(base, event.category_label, height)


def _paginate_reel_layouts(layouts: Iterable[ReelLayout]) -> list[list[ReelLayout]]:
    available = CONTENT_BOTTOM - CONTENT_TOP
    pages: list[list[ReelLayout]] = []
    current: list[ReelLayout] = []
    used = 0
    for layout in layouts:
        required = layout.height + (CARD_GAP if current else 0)
        if current and (len(current) >= MAX_EVENTS_PER_PAGE or used + required > available):
            pages.append(current)
            current = []
            used = 0
            required = layout.height
        if required > available:
            raise LayoutOverflowError(f"event does not fit on one Reel page: {layout.event.event_id}")
        current.append(layout)
        used += required
    if current:
        pages.append(current)
    if len(pages) >= 2 and len(pages[-1]) == 1 and len(pages[-2]) >= 3:
        moved = pages[-2][-1]
        candidate = [moved, *pages[-1]]
        candidate_height = sum(item.height for item in candidate) + CARD_GAP * (len(candidate) - 1)
        if candidate_height <= available:
            pages[-2].pop()
            pages[-1] = candidate
    return pages


def _page_start_and_gap(page: list[ReelLayout]) -> tuple[int, int]:
    content_height = CONTENT_BOTTOM - CONTENT_TOP
    cards_height = sum(layout.height for layout in page)
    base_gaps = CARD_GAP * max(0, len(page) - 1)
    unused = max(0, content_height - cards_height - base_gaps)
    top_offset = min(180, unused // 2)
    if len(page) <= 1:
        return CONTENT_TOP + top_offset, CARD_GAP
    extra_gap = min(72, max(0, unused - top_offset) // (len(page) - 1))
    return CONTENT_TOP + top_offset, CARD_GAP + extra_gap


def _format_reel_date(event: Any) -> str:
    return f"{_format_event_day(event.event_date)}  {_format_time(event)}"


def render_reel_frames(events: Sequence[ReelEvent], target_friday: dt.date) -> list[Image.Image]:
    if not events:
        raise NoEventsError("no publishable events for the target weekend")
    measuring = Image.new("RGB", (STORY_WIDTH, STORY_HEIGHT), PAPER)
    draw = ImageDraw.Draw(measuring)
    fonts = _font_set(DEFAULT_FONT_PATH, DEFAULT_SERIF_FONT_PATH)
    layouts = [layout_reel_event(draw, event, fonts) for event in events]
    pages = _paginate_reel_layouts(layouts)
    heading_font = load_font(DEFAULT_SERIF_FONT_PATH, 64, weight=700)
    site_font = load_font(DEFAULT_SERIF_FONT_PATH, 36, weight=700)
    domain_font = load_font(DEFAULT_FONT_PATH, 22, weight=500)
    date_font = load_font(DEFAULT_SERIF_FONT_PATH, 40, weight=600)
    footer_font = load_font(DEFAULT_FONT_PATH, 24, weight=500)
    footer_site_font = load_font(DEFAULT_SERIF_FONT_PATH, 32, weight=600)
    page_font = load_font(DEFAULT_SERIF_FONT_PATH, 31, weight=700)
    small_font = fonts["small"]
    if not DEFAULT_ICON_PATH.is_file():
        raise ReelError("official brand icon not found")
    with Image.open(DEFAULT_ICON_PATH) as source_icon:
        brand_icon = source_icon.convert("RGBA").resize((146, 146), Image.Resampling.LANCZOS)
        footer_icon = source_icon.convert("RGBA").resize((82, 82), Image.Resampling.LANCZOS)
    images: list[Image.Image] = []
    for page_number, page in enumerate(pages, start=1):
        image = Image.new("RGB", (STORY_WIDTH, STORY_HEIGHT), PAPER)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, STORY_WIDTH, 18), fill=INK)
        draw.rectangle((0, 18, STORY_WIDTH, 29), fill=ACCENT)
        image.paste(brand_icon, (CONTENT_LEFT, 54), brand_icon)
        draw.text((CONTENT_LEFT + 174, 76), "剣道稽古ナビ", font=site_font, fill=INK)
        draw.text((CONTENT_LEFT + 174, 132), "kendo-keiko.com", font=domain_font, fill=ACCENT)
        page_text = f"{page_number}/{len(pages)}"
        page_width = draw.textlength(page_text, font=page_font)
        pill_left = CONTENT_RIGHT - page_width - 46
        draw.rounded_rectangle((pill_left, 72, CONTENT_RIGHT, 126), radius=27, fill=ACCENT)
        draw.text((pill_left + 23, 76), page_text, font=page_font, fill=SURFACE)
        _draw_centered_text(draw, "今週末（金〜日）の稽古会", y=226, font=heading_font, fill=INK)
        _draw_divider(draw, 340)
        _draw_centered_text(draw, target_date_label(target_friday), y=370, font=date_font, fill=ACCENT)
        y, page_gap = _page_start_and_gap(page)
        for layout in page:
            bottom = y + layout.height
            draw.rounded_rectangle((CONTENT_LEFT + 6, y + 8, CONTENT_RIGHT + 6, bottom + 8), radius=18, fill=SHADOW)
            draw.rounded_rectangle((CONTENT_LEFT, y, CONTENT_RIGHT, bottom), radius=18, fill=SURFACE, outline=WARM_LINE, width=2)
            _draw_card_corners(draw, CONTENT_LEFT, y, CONTENT_RIGHT, bottom)
            datetime_text = _format_reel_date(layout.event)
            datetime_width = round(draw.textlength(datetime_text, font=small_font)) + 34
            draw.rounded_rectangle((CARD_LEFT_X, y + 24, CARD_LEFT_X + datetime_width, y + 64), radius=14, fill=ACCENT)
            draw.text((CARD_LEFT_X + 17, y + 27), datetime_text, font=small_font, fill=SURFACE)
            left_cursor = y + 82
            left_cursor = _draw_lines(draw, layout.base.organization_lines or ("",), x=CARD_LEFT_X, y=left_cursor, font=fonts["org"], fill=INK, line_height=52)
            left_cursor = _draw_lines(draw, layout.base.title_lines, x=CARD_LEFT_X, y=left_cursor, font=fonts["title"], fill=INK_SOFT, line_height=42)
            draw.text((CARD_LEFT_X, left_cursor + 5), layout.category_label, font=small_font, fill=ACCENT)
            labels = (*layout.event.participation_labels,)
            _draw_participation_badges(draw, labels, x=CARD_LEFT_X, y=left_cursor + 37, font=small_font)
            draw.line((CARD_DIVIDER_X, y + 86, CARD_DIVIDER_X, bottom - 28), fill=LINE, width=2)
            right_cursor = y + 88
            draw.text((CARD_RIGHT_X, right_cursor), "会場", font=fonts["body"], fill=ACCENT)
            right_cursor = _draw_lines(draw, layout.base.venue_lines or ("未取得",), x=CARD_VALUE_X, y=right_cursor, font=fonts["body"], fill=INK_SOFT, line_height=38)
            draw.text((CARD_RIGHT_X, right_cursor), "地域", font=small_font, fill=ACCENT)
            right_cursor = _draw_lines(draw, layout.base.area_lines or ("未設定",), x=CARD_VALUE_X, y=right_cursor, font=small_font, fill=INK_SOFT, line_height=36)
            if layout.base.fee_lines:
                draw.text((CARD_RIGHT_X, right_cursor), "参加費", font=small_font, fill=ACCENT)
                right_cursor = _draw_lines(draw, layout.base.fee_lines, x=CARD_VALUE_X, y=right_cursor, font=small_font, fill=INK_SOFT, line_height=35)
            if layout.base.access_lines:
                draw.text((CARD_RIGHT_X, right_cursor), "アクセス", font=small_font, fill=ACCENT)
                _draw_lines(draw, layout.base.access_lines, x=CARD_VALUE_X, y=right_cursor, font=small_font, fill=INK_SOFT, line_height=35)
            y = bottom + page_gap
        draw.rectangle((0, 1682, STORY_WIDTH, 1820), fill=ACCENT)
        image.paste(footer_icon, (145, 1710), footer_icon)
        draw.text((247, 1726), "剣道稽古ナビ", font=footer_site_font, fill=SURFACE)
        draw.line((520, 1718, 520, 1788), fill=SURFACE, width=2)
        draw.text((552, 1730), "kendo-keiko.com", font=domain_font, fill=SURFACE)
        draw.rectangle((0, 1820, STORY_WIDTH, STORY_HEIGHT), fill=INK)
        warning = "参加前に必ず主催者の公式情報をご確認ください"
        warning_width = draw.textlength(warning, font=footer_font)
        draw.text(((STORY_WIDTH - warning_width) / 2, 1857), warning, font=footer_font, fill=SURFACE)
        images.append(image)
    return images


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
    frames = render_reel_frames(selection.events, selection.target_friday)
    caption = caption_for_reel(selection)
    with tempfile.TemporaryDirectory(prefix="kendo-reel-frames-") as frame_dir:
        frame_root = Path(frame_dir)
        for number, image in enumerate(frames, start=1):
            image.save(frame_root / f"frame-{number:05d}.png", format="PNG")
        cover_path = output_dir / "cover.png"
        frames[0].save(cover_path, format="PNG", optimize=True)
        video_path = output_dir / "reel.mp4"
        ffmpeg = get_ffmpeg_path()
        frame_rate = f"1/{page_seconds:g}"
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-framerate",
                frame_rate,
                "-i",
                str(frame_root / "frame-%05d.png"),
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
