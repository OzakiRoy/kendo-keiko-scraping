#!/usr/bin/env python3
"""Generate the committed favicon and OGP assets for kendo-keiko.com.

Pillow is only required when regenerating the assets locally. It is not needed by
Lambda at runtime and must not be added to requirements.txt.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT_DIR = Path(__file__).resolve().parents[1]
PUBLIC_DIR = ROOT_DIR / "public"

PAPER = "#f3f1ec"
SURFACE = "#fffdfa"
INK = "#1b1b1b"
INK_SOFT = "#42403c"
MUTED = "#706d67"
ACCENT = "#8c1d24"
LINE = "#d6d1c8"

SERIF_REGULAR = Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc")
SERIF_BOLD = Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc")
SANS_REGULAR = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
SANS_BOLD = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")


def load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    if not path.exists():
        raise FileNotFoundError(f"Japanese font not found: {path}")
    return ImageFont.truetype(str(path), size=size)


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
    *,
    y_offset: int = 0,
) -> None:
    left, top, right, bottom = box
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    x = left + ((right - left) - width) / 2 - bbox[0]
    y = top + ((bottom - top) - height) / 2 - bbox[1] + y_offset
    draw.text((x, y), text, font=font, fill=fill)


def make_logo(size: int = 1024) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = round(size * 0.055)
    ring_width = max(2, round(size * 0.024))

    draw.ellipse(
        (margin, margin, size - margin, size - margin),
        fill=ACCENT,
    )
    draw.ellipse(
        (
            margin + ring_width,
            margin + ring_width,
            size - margin - ring_width,
            size - margin - ring_width,
        ),
        outline=SURFACE,
        width=ring_width,
    )

    font = load_font(SERIF_BOLD, round(size * 0.58))
    draw_centered_text(
        draw,
        (margin, margin, size - margin, size - margin),
        "稽",
        font,
        SURFACE,
        y_offset=round(size * 0.012),
    )
    return image


def save_logo_assets() -> None:
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    master = make_logo()

    for filename, size in (
        ("favicon-32x32.png", 32),
        ("apple-touch-icon.png", 180),
        ("icon-192.png", 192),
        ("icon-512.png", 512),
    ):
        resized = master.resize((size, size), Image.Resampling.LANCZOS)
        resized.save(PUBLIC_DIR / filename, optimize=True)

    master.save(
        PUBLIC_DIR / "favicon.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48)],
    )

    # SVG is the preferred modern favicon; PNG/ICO remain reliable fallbacks.
    (PUBLIC_DIR / "favicon.svg").write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="剣道稽古ナビ">
  <circle cx="32" cy="32" r="29" fill="#8c1d24"/>
  <circle cx="32" cy="32" r="25.5" fill="none" stroke="#fffdfa" stroke-width="2"/>
  <text x="32" y="44" text-anchor="middle" fill="#fffdfa" font-family="Yu Mincho, Hiragino Mincho ProN, Noto Serif JP, serif" font-size="36" font-weight="700">稽</text>
</svg>
""",
        encoding="utf-8",
    )

    manifest = {
        "name": "剣道稽古ナビ",
        "short_name": "剣道稽古ナビ",
        "description": "参加できる剣道のオープン稽古会・合同稽古会を探せる情報サイト",
        "start_url": "/",
        "display": "standalone",
        "background_color": PAPER,
        "theme_color": ACCENT,
        "icons": [
            {
                "src": "/icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
            },
            {
                "src": "/icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
            },
        ],
    }
    (PUBLIC_DIR / "site.webmanifest").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def make_ogp() -> None:
    width, height = 1200, 630
    image = Image.new("RGB", (width, height), PAPER)
    draw = ImageDraw.Draw(image)

    # Formal, restrained framing that matches the public-site design.
    draw.rectangle((0, 0, width, 14), fill=INK)
    draw.rectangle((0, 14, width, 22), fill=ACCENT)
    draw.line((82, 500, 1118, 500), fill=LINE, width=2)
    draw.rectangle((82, 90, 88, 465), fill=ACCENT)

    logo = make_logo(1024).resize((154, 154), Image.Resampling.LANCZOS)
    image.paste(logo, (112, 112), logo)

    kicker_font = load_font(SANS_BOLD, 24)
    title_font = load_font(SERIF_BOLD, 76)
    tagline_font = load_font(SERIF_REGULAR, 36)
    descriptor_font = load_font(SANS_BOLD, 25)
    domain_font = load_font(SANS_REGULAR, 23)

    draw.text((310, 112), "KENDO KEIKO NAVI", font=kicker_font, fill=ACCENT)
    draw.text((306, 160), "剣道稽古ナビ", font=title_font, fill=INK)
    draw.text(
        (310, 286),
        "参加できる稽古会を、",
        font=tagline_font,
        fill=INK_SOFT,
    )
    draw.text(
        (310, 344),
        "日付・地域・参加条件から探す",
        font=tagline_font,
        fill=INK_SOFT,
    )

    draw.text(
        (84, 526),
        "オープン稽古会・合同稽古会情報",
        font=descriptor_font,
        fill=INK,
    )
    domain_text = "kendo-keiko.com"
    domain_bbox = draw.textbbox((0, 0), domain_text, font=domain_font)
    domain_width = domain_bbox[2] - domain_bbox[0]
    draw.text(
        (1118 - domain_width, 530),
        domain_text,
        font=domain_font,
        fill=MUTED,
    )

    image.save(PUBLIC_DIR / "ogp.png", optimize=True)


def main() -> None:
    save_logo_assets()
    make_ogp()
    print(f"Generated brand assets in {PUBLIC_DIR}")


if __name__ == "__main__":
    main()
