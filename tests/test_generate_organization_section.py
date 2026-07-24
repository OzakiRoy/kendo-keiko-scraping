import json
import tempfile
import unittest
from pathlib import Path

from scripts.generate_organization_section import (
    build_organization_section,
    generate_index,
    replace_organization_section,
)


class GenerateOrganizationSectionTests(unittest.TestCase):
    def test_filters_disabled_and_escapes_html(self) -> None:
        organizations = [
            {
                "organization_id": "enabled",
                "name": '有効団体 <script>"test"</script>',
                "area": "東京 & 埼玉",
                "website_url": "https://example.com/?a=1&b=2",
                "scraper_enabled": True,
                "public_description": (
                    "説明 <strong>太字</strong>"
                ),
            },
            {
                "organization_id": "disabled",
                "name": "無効団体",
                "area": "東京都",
                "website_url": "https://example.net/",
                "scraper_enabled": False,
                "public_description": "表示されない説明",
            },
            {
                "organization_id": "manual",
                "name": "手動掲載団体",
                "area": "埼玉県",
                "website_url": "https://manual.example.com/",
                "scraper_type": "manual",
                "scraper_enabled": False,
                "public_description": "手動登録の団体です。",
            },
        ]

        section = build_organization_section(
            organizations
        )

        self.assertIn(
            "&lt;script&gt;&quot;test&quot;"
            "&lt;/script&gt;",
            section,
        )
        self.assertIn(
            "東京 &amp; 埼玉",
            section,
        )
        self.assertIn(
            "説明 &lt;strong&gt;太字&lt;/strong&gt;",
            section,
        )
        self.assertIn(
            "https://example.com/?a=1&amp;b=2",
            section,
        )
        self.assertNotIn(
            "無効団体",
            section,
        )
        self.assertIn(
            "手動掲載団体",
            section,
        )

    def test_replace_is_idempotent(self) -> None:
        template = """<!doctype html>
<html>
<body>
<!-- ORGANIZATION_SECTION_START -->
old content
<!-- ORGANIZATION_SECTION_END -->
<div id="cards"></div>
</body>
</html>
"""

        section = """    <section id="listed-organizations">
      test
    </section>"""

        first = replace_organization_section(
            template,
            section,
        )
        second = replace_organization_section(
            first,
            section,
        )

        self.assertEqual(first, second)
        self.assertIn(
            '<div id="cards"></div>',
            second,
        )

    def test_generates_index_from_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            organizations_path = (
                root / "organizations.json"
            )
            index_path = root / "index.html"

            organizations_path.write_text(
                json.dumps(
                    [
                        {
                            "name": "東京都剣道連盟",
                            "area": "東京都",
                            "website_url": (
                                "https://example.com/"
                            ),
                            "scraper_enabled": True,
                            "public_description": (
                                "合同稽古会を掲載しています。"
                            ),
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            index_path.write_text(
                """<main>
<!-- ORGANIZATION_SECTION_START -->
<!-- ORGANIZATION_SECTION_END -->
<div id="cards"></div>
</main>
""",
                encoding="utf-8",
            )

            generate_index(
                organizations_path,
                index_path,
            )

            result = index_path.read_text(
                encoding="utf-8"
            )

            self.assertIn(
                "東京都剣道連盟",
                result,
            )
            self.assertIn(
                "合同稽古会を掲載しています。",
                result,
            )
            self.assertIn(
                '<div id="cards"></div>',
                result,
            )


if __name__ == "__main__":
    unittest.main()
