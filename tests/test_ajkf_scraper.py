import unittest

from kendo_keiko.scrapers.ajkf import (
    extract_ajkf_area,
    extract_ajkf_date,
    extract_ajkf_keiko_links,
    extract_ajkf_venue,
)


class AjkfScraperTests(unittest.TestCase):
    def test_extracts_date_from_event_url(self) -> None:
        result = extract_ajkf_date(
            text="開催日：2025年1月1日",
            url=(
                "https://www.kendo.or.jp/keiko-kai/"
                "kendo-lesson-kinki-20260801-kyoto/"
            ),
        )

        self.assertEqual("2026-08-01", result)

    def test_extracts_prefecture_from_title(self) -> None:
        result = extract_ajkf_area(
            title="剣道合同稽古会 東海地区（愛知県）",
            text="",
            venue="名古屋市北スポーツセンター",
            url=(
                "https://www.kendo.or.jp/keiko-kai/"
                "kendo-lesson-toukai-20260905-aichi/"
            ),
        )

        self.assertEqual("愛知県", result)

    def test_extracts_venue_before_address(self) -> None:
        text = """
        会場名
        京都市武道センター
        〒606-8323 京都府京都市
        開催日
        2026年8月1日
        """

        self.assertEqual(
            "京都市武道センター",
            extract_ajkf_venue(text),
        )

    def test_collects_only_ajkf_event_links(self) -> None:
        html = """
        <a href="/keiko-kai/kendo-lesson-kinki-20260801-kyoto/">
          稽古会
        </a>
        <a href="https://example.com/other">対象外</a>
        """

        links = extract_ajkf_keiko_links(html)

        self.assertEqual(
            [
                "https://www.kendo.or.jp/"
                "keiko-kai/kendo-lesson-kinki-20260801-kyoto/"
            ],
            links,
        )


if __name__ == "__main__":
    unittest.main()
