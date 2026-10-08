"""Regression checks for the shared listing and organization styles."""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "public/assets/site.css"


class SiteCssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS.read_text(encoding="utf-8")

    def test_card_spacing_uses_content_driven_grid(self) -> None:
        card = re.search(r"\.card \{(?P<body>.*?)\n\}", self.css, re.S)
        self.assertIsNotNone(card)
        body = card.group("body")
        for declaration in (
            "row-gap: 0;",
            "column-gap: 24px;",
            "align-content: start;",
            "padding: 22px 24px;",
        ):
            self.assertIn(declaration, body)
        self.assertIn("grid-row: 1 / span 20", self.css)

    def test_card_statuses_are_centered_and_distinct(self) -> None:
        for declaration in (
            "display: inline-flex;",
            "align-items: center;",
            "justify-content: center;",
            "min-height: 28px;",
            "padding: 5px 10px;",
            "line-height: 1.25;",
            "white-space: nowrap;",
        ):
            self.assertIn(declaration, self.css)
        for selector, color, background, border in (
            (".status-badge--anyone", "#22583a", "#eaf4ed", "#b9d6c3"),
            (".status-badge--contact_required", "#775019", "#fff2dc", "#e6ca94"),
            (".status-badge--registration_required", "#8c1d24", "#f8e9ea", "#d5a4a8"),
            (".status-badge--unknown", "#454e5a", "#eef1f4", "#cbd2da"),
        ):
            self.assertRegex(
                self.css,
                rf"{re.escape(selector)}.*?color: {re.escape(color)};.*?"
                rf"background: {re.escape(background)};.*?"
                rf"border-color: {re.escape(border)};",
            )
        self.assertIn(".card .row + .row { margin-top: 5px; }", self.css)
        self.assertIn(
            ".verification-status { padding: 5px 0; border: 0; border-radius: 0;",
            self.css,
        )

    def test_organization_spacing_and_mobile_overrides(self) -> None:
        self.assertIn(
            ".organization-intro { margin: 16px 0 20px;",
            self.css,
        )
        self.assertIn("line-height: 1.85;", self.css)
        self.assertIn(
            ".organization-source-note { margin: 20px 0 0; padding: 16px 20px;",
            self.css,
        )
        self.assertIn(
            ".organization-source-note { padding: 14px 16px; }",
            self.css,
        )
        self.assertIn(
            ".card .date { display: block; margin: 0 0 10px; padding: 0 0 10px;",
            self.css,
        )
        self.assertIn(".card { display: block; padding: 18px; }", self.css)


if __name__ == "__main__":
    unittest.main()
