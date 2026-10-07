"""Browser-level checks for the standalone team builder tool."""

import os
import unittest
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".venv/browsers"))


class TeamBuilderAssetTests(unittest.TestCase):
    def test_public_assets_and_links(self):
        html = (PUBLIC / "tools/team-builder.html").read_text(encoding="utf-8")
        self.assertIn('<link rel="canonical" href="https://kendo-keiko.com/tools/team-builder.html">', html)
        self.assertIn('<link rel="stylesheet" href="/assets/team-builder.css">', html)
        self.assertIn('<script src="/assets/team-builder.js" defer></script>', html)
        self.assertEqual(1, html.count("gtag('config', 'G-HY0WCBCXKW')"))
        self.assertNotIn("試作品", html)
        self.assertIn('href="/tools/team-builder.html"', (PUBLIC / "index.html").read_text(encoding="utf-8"))
        self.assertIn("https://kendo-keiko.com/tools/team-builder.html", (PUBLIC / "sitemap.xml").read_text(encoding="utf-8"))
        self.assertTrue((PUBLIC / "assets/team-builder.css").is_file())
        self.assertTrue((PUBLIC / "assets/team-builder.js").is_file())


class TeamBuilderBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(timeout=30_000)
        except Exception:
            cls.playwright.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def page(self, *, mobile: bool = False):
        context = self.browser.new_context(
            viewport={"width": 360 if mobile else 1280, "height": 900}
        )
        self.addCleanup(context.close)
        context.set_default_timeout(30_000)

        def route(request):
            path = request.request.url.split("?", 1)[0].split("#", 1)[0]
            if "googletagmanager.com" in path:
                request.abort()
                return
            relative = path.removeprefix("https://team-builder.test/")
            asset = PUBLIC / relative
            if asset.is_file():
                request.fulfill(path=asset)
            else:
                request.fulfill(status=404)

        context.route("**/*", route)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("https://team-builder.test/tools/team-builder.html")
        page.wait_for_function("document.querySelectorAll('#kb-board .kb-team').length === 4")
        self.assertEqual([], errors)
        return page

    @staticmethod
    def roster_ids(page):
        return page.locator("#kb-board .kb-member").evaluate_all(
            "members => members.map(member => member.dataset.playerId)"
        )

    def test_initial_sample_and_balanced_team_sizes(self):
        page = self.page(mobile=True)
        self.assertTrue(page.locator("#kb-print").is_visible())
        self.assertEqual(12, len(self.roster_ids(page)))
        self.assertEqual(12, len(set(self.roster_ids(page))))
        self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))

        page.locator("#kb-count").fill("3")
        page.locator("#kb-count").dispatch_event("change")
        page.wait_for_function("document.querySelectorAll('#kb-board .kb-team').length === 3")
        sizes = page.locator("#kb-board .kb-team").evaluate_all(
            "teams => teams.map(team => team.querySelectorAll('.kb-member').length)"
        )
        self.assertEqual(12, sum(sizes))
        self.assertLessEqual(max(sizes) - min(sizes), 1)
        self.assertEqual(12, len(set(self.roster_ids(page))))

    def test_known_age_and_dan_balance(self):
        page = self.page()
        page.locator("#kb-editor").evaluate("el => { el.open = true; }")
        rows = page.locator("#kb-roster .kb-roster-row")
        for index in range(11, 5, -1):
            rows.nth(index).locator(".kb-remove").click()
        values = [(20, 1), (20, 1), (20, 1), (60, 6), (60, 6), (60, 6)]
        for index, (age, dan) in enumerate(values, start=1):
            row = page.locator("#kb-roster .kb-roster-row").nth(index - 1)
            row.locator("input").nth(1).fill(str(age))
            row.locator("input").nth(2).fill(str(dan))
        page.locator("#kb-count").fill("3")
        page.locator("#kb-count").dispatch_event("change")
        page.wait_for_function("document.querySelectorAll('#kb-board .kb-team').length === 3")
        self.assertEqual(
            ["平均年齢 40.0歳"] * 3,
            page.locator(".kb-mean-age").all_inner_texts(),
        )
        self.assertEqual(
            ["平均段位 3.5"] * 3,
            page.locator(".kb-mean-dan").all_inner_texts(),
        )

    def test_manual_swap_and_beforeunload_warning(self):
        page = self.page()
        initial = page.evaluate(
            """() => {
              const event = new Event('beforeunload', {cancelable: true});
              window.dispatchEvent(event);
              return event.defaultPrevented;
            }"""
        )
        self.assertFalse(initial)

        page.locator("#kb-count").fill("3")
        page.locator("#kb-count").dispatch_event("change")
        warned = page.evaluate(
            """() => {
              const event = new Event('beforeunload', {cancelable: true});
              window.dispatchEvent(event);
              return {prevented: event.defaultPrevented, returnValue: event.returnValue};
            }"""
        )
        self.assertTrue(warned["prevented"])
        self.assertIn(warned["returnValue"], ("", False))

        page.locator("#kb-manual").evaluate("el => { el.open = true; }")
        page.locator("#kb-swap-a").select_option("1")
        page.locator("#kb-swap-b").select_option("2")
        page.locator("#kb-swap").click()
        self.assertIn("を入れ替えました", page.locator("#kb-swap-status").inner_text())
        self.assertEqual(12, len(set(self.roster_ids(page))))

    def test_empty_roster_clears_beforeunload_warning(self):
        page = self.page()
        page.locator("#kb-editor").evaluate("el => { el.open = true; }")
        while page.locator("#kb-roster .kb-roster-row").count():
            page.locator("#kb-roster .kb-remove").last.click()
        self.assertEqual(0, page.locator("#kb-roster .kb-roster-row").count())
        self.assertTrue(page.locator("#kb-results").is_hidden())
        self.assertFalse(
            page.evaluate(
                """() => {
                  const event = new Event('beforeunload', {cancelable: true});
                  window.dispatchEvent(event);
                  return event.defaultPrevented;
                }"""
            )
        )

    def test_real_reload_dialog_cancel_preserves_and_accept_resets(self):
        page = self.page()
        page.locator("#kb-count").fill("3")
        page.locator("#kb-count").dispatch_event("change")
        page.locator("#kb-editor").evaluate("el => { el.open = true; }")
        page.locator("#kb-name-1").fill("変更済み")

        cancelled = []

        def dismiss(dialog):
            cancelled.append(dialog.type)
            dialog.dismiss()

        page.once("dialog", dismiss)
        try:
            page.reload(timeout=1_000)
        except PlaywrightTimeoutError:
            pass
        self.assertEqual(["beforeunload"], cancelled)
        self.assertEqual("変更済み", page.locator("#kb-name-1").input_value())
        self.assertEqual("3", page.locator("#kb-count").input_value())

        accepted = []

        def accept(dialog):
            accepted.append(dialog.type)
            dialog.accept()

        page.once("dialog", accept)
        page.reload()
        page.wait_for_function("document.querySelectorAll('#kb-board .kb-team').length === 4")
        self.assertEqual(["beforeunload"], accepted)
        self.assertEqual("選手A", page.locator("#kb-name-1").input_value())
        self.assertEqual("4", page.locator("#kb-count").input_value())

    def test_invalid_input_print_media_and_narrow_layout(self):
        page = self.page(mobile=True)
        page.locator("#kb-roster-summary").click()
        page.locator("#kb-age-1").fill("")
        page.locator("#kb-use-age").check()
        page.locator("#kb-generate").click()
        self.assertTrue(page.locator("#kb-error").is_visible())
        self.assertIn("年齢を条件に使うため", page.locator("#kb-error").inner_text())

        page.locator("#kb-age-1").fill("21")
        page.locator("#kb-generate").click()
        page.emulate_media(media="print")
        self.assertEqual("none", page.locator(".kb-config").evaluate("el => getComputedStyle(el).display"))
        self.assertEqual("none", page.locator("#kb-manual").evaluate("el => getComputedStyle(el).display"))
        self.assertEqual(4, page.locator("#kb-board .kb-team").count())
        self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))

    def test_seven_players_one_team_and_condition_off(self):
        page = self.page()
        page.locator("#kb-editor").evaluate("el => { el.open = true; }")
        rows = page.locator("#kb-roster .kb-roster-row")
        for index in range(11, 6, -1):
            rows.nth(index).locator(".kb-remove").click()
        page.locator("#kb-use-age").uncheck()
        page.locator("#kb-use-dan").uncheck()
        page.locator("#kb-count").fill("3")
        page.locator("#kb-count").dispatch_event("change")
        page.wait_for_function("document.querySelectorAll('#kb-board .kb-team').length === 3")
        sizes = page.locator("#kb-board .kb-team").evaluate_all(
            "teams => teams.map(team => team.querySelectorAll('.kb-member').length)"
        )
        self.assertEqual([3, 2, 2], sorted(sizes, reverse=True))
        page.locator("#kb-count").fill("1")
        page.locator("#kb-count").dispatch_event("change")
        page.wait_for_function("document.querySelectorAll('#kb-board .kb-team').length === 1")
        self.assertEqual(7, page.locator("#kb-board .kb-member").count())

    def test_maximum_sixty_players(self):
        page = self.page()
        page.locator("#kb-editor").evaluate("el => { el.open = true; }")
        page.locator("#kb-use-age").uncheck()
        page.locator("#kb-use-dan").uncheck()
        for _ in range(48):
            page.locator("#kb-add").click()
        self.assertEqual(60, page.locator("#kb-roster .kb-roster-row").count())
        page.evaluate(
            """() => [...document.querySelectorAll('#kb-roster .kb-roster-row')]
              .slice(12)
              .forEach((row, index) => {
                const input = row.querySelector('input');
                input.value = '選手' + (index + 13);
                input.dispatchEvent(new Event('input', {bubbles: true}));
              })"""
        )
        page.locator("#kb-count").fill("3")
        page.locator("#kb-generate").click()
        page.wait_for_function("document.querySelectorAll('#kb-board .kb-team').length === 3")
        sizes = page.locator("#kb-board .kb-team").evaluate_all(
            "teams => teams.map(team => team.querySelectorAll('.kb-member').length)"
        )
        self.assertEqual([20, 20, 20], sizes)
        self.assertEqual(60, len(set(self.roster_ids(page))))


if __name__ == "__main__":
    unittest.main()
