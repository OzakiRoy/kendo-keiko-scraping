from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
PUBLIC_DIR = ROOT_DIR / "public"
INDEX_PATH = PUBLIC_DIR / "index.html"


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"not a PNG file: {path}")
    if data[12:16] != b"IHDR":
        raise AssertionError(f"PNG has no IHDR at expected offset: {path}")
    return struct.unpack(">II", data[16:24])


class BrandAssetsTests(unittest.TestCase):
    def test_html_uses_canonical_brand_metadata(self) -> None:
        html = INDEX_PATH.read_text(encoding="utf-8")

        self.assertIn(
            "<title>剣道稽古ナビ｜オープン稽古会・合同稽古会を地域と日付から検索</title>",
            html,
        )
        self.assertIn("<h1>剣道稽古ナビ</h1>", html)
        self.assertIn(
            "参加できる稽古会を、日付・地域・参加条件から探す",
            html,
        )
        self.assertIn('content="剣道稽古ナビ"', html)
        self.assertIn('content="summary_large_image"', html)
        self.assertIn('href="/site.webmanifest"', html)
        self.assertIn('src="/icon-192.png"', html)

    def test_committed_png_dimensions(self) -> None:
        expected = {
            "favicon-32x32.png": (32, 32),
            "apple-touch-icon.png": (180, 180),
            "icon-192.png": (192, 192),
            "icon-512.png": (512, 512),
            "ogp.png": (1200, 630),
        }
        for filename, dimensions in expected.items():
            with self.subTest(filename=filename):
                self.assertEqual(dimensions, png_dimensions(PUBLIC_DIR / filename))

    def test_favicon_and_manifest_are_valid(self) -> None:
        svg = (PUBLIC_DIR / "favicon.svg").read_text(encoding="utf-8")
        self.assertTrue(svg.startswith("<svg "))
        self.assertIn(">稽</text>", svg)

        ico = (PUBLIC_DIR / "favicon.ico").read_bytes()
        reserved, image_type, count = struct.unpack("<HHH", ico[:6])
        self.assertEqual(0, reserved)
        self.assertEqual(1, image_type)
        self.assertGreaterEqual(count, 3)

        manifest = json.loads(
            (PUBLIC_DIR / "site.webmanifest").read_text(encoding="utf-8")
        )
        self.assertEqual("剣道稽古ナビ", manifest["name"])
        self.assertEqual("#8c1d24", manifest["theme_color"])
        self.assertEqual(
            {"/icon-192.png", "/icon-512.png"},
            {icon["src"] for icon in manifest["icons"]},
        )


if __name__ == "__main__":
    unittest.main()
