"""Real Chromium regression tests; install requirements-dev.txt and Chromium first."""
import datetime as dt
import os
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright
from tests.test_listing_pages import ROOT, EXPECTED, fixture_pages, public_fixture

os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / '.venv/browsers'))


class ListingBrowserTests(unittest.TestCase):
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

    def load_page(self, key='index.html', *, javascript=True, failure=False, empty=False, mobile=False):
        context = self.browser.new_context(java_script_enabled=javascript, viewport={'width':375 if mobile else 1280, 'height':812})
        self.addCleanup(context.close)
        context.set_default_timeout(30_000)
        pages = fixture_pages()
        payload = public_fixture()
        if empty:
            from kendo_keiko.static_site import render_listing_pages
            payload['events'] = []
            pages = render_listing_pages((ROOT/'public/index.html').read_text(), payload)
        # WSL may have no Japanese system font. Reuse repository fonts only in tests.
        font_style = """<style>
          @font-face { font-family: 'Noto Serif JP'; src: url('/__test-serif.ttf'); font-weight: 200 900; }
          @font-face { font-family: 'Noto Sans JP'; src: url('/__test-font.ttf'); font-weight: 100 900; }
          body, button, input, select { font-family: 'Noto Sans JP', sans-serif !important; }
        </style>"""
        def route(request):
            path = urlsplit(request.request.url).path
            if path == '/__test-serif.ttf':
                request.fulfill(path=ROOT/'assets/fonts/NotoSerifJP[wght].ttf', content_type='font/ttf')
            elif path == '/__test-font.ttf':
                request.fulfill(path=ROOT/'assets/fonts/NotoSansJP[wght].ttf', content_type='font/ttf')
            elif path == '/events.json':
                if failure: request.abort()
                else: request.fulfill(json=payload)
            elif path.endswith('/') or path.endswith('/index.html'):
                requested = path.lstrip('/') + ('index.html' if path.endswith('/') else '')
                request.fulfill(body=pages[requested].replace('</head>',font_style+'</head>'), content_type='text/html')
            else:
                asset = ROOT/'public'/path.lstrip('/')
                if asset.is_file(): request.fulfill(path=asset)
                else: request.fulfill(status=404)
        context.route('**/*', route)
        page = context.new_page()
        errors=[]
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.clock.install(time=dt.datetime(2026, 9, 20, tzinfo=dt.timezone.utc))
        page.goto('https://listing.test/' + key.replace('index.html',''))
        if javascript:
            page.wait_for_function("document.querySelector('#meta').textContent.includes('生成日時') || document.querySelector('#meta').textContent.includes('失敗')")
        self.assertEqual([], errors)
        if javascript:
            page.evaluate('document.fonts.ready')
        return page

    def ids(self, page):
        return page.locator('#cards .card').evaluate_all('(cards) => cards.map(card => card.dataset.eventId)')

    def test_js_scope_counts_options_and_reset(self):
        for key, expected in EXPECTED.items():
            with self.subTest(key=key):
                page = self.load_page(key)
                self.assertEqual(expected, self.ids(page))
                self.assertIn(f'{len(expected)}件',page.locator('#count').inner_text())
                events=[e for e in public_fixture()['events'] if e['event_id'] in expected]
                for select, field in [('organization','organization_name'),('area','area')]:
                    options=page.locator(f'#{select} option').evaluate_all('(options) => options.map(o=>o.value).filter(Boolean)')
                    self.assertEqual(sorted({e[field] for e in events}), sorted(options))
                from bs4 import BeautifulSoup
                static = BeautifulSoup(fixture_pages()[key], 'html.parser')
                for select in ['organization', 'area', 'participation']:
                    self.assertEqual(
                        sorted(option['value'] for option in static.select(f'#{select} option')),
                        sorted(page.locator(f'#{select} option').evaluate_all('(options)=>options.map(o=>o.value)')),
                    )
                page.locator('#keyword').fill('no match')
                self.assertEqual([],self.ids(page))
                self.assertIn('0件',page.locator('#count').inner_text())
                page.locator('[data-reset-filters]').click()
                self.assertEqual(expected,self.ids(page))
                self.assertTrue(page.locator('#keyword').evaluate('(el)=>el===document.activeElement'))
                self.assertTrue(page.locator('#clear-filters').is_disabled())

    def test_compound_filters_and_keyboard(self):
        page=self.load_page(mobile=True)
        button=page.locator('[data-category="renseikai"]')
        button.focus()
        page.keyboard.press('Tab')
        self.assertTrue(page.locator('[data-date-shortcut=""]').evaluate('(el)=>el===document.activeElement'))
        button.focus()
        page.keyboard.press('Enter')
        self.assertEqual(['adult','adult-later'],self.ids(page))
        self.assertEqual('true',button.get_attribute('aria-pressed'))
        page.locator('#area').select_option('東京都')
        page.locator('#organization').select_option('合同団体')
        page.locator('#participation').select_option('registration_required')
        page.locator('[data-date-shortcut="7days"]').click()
        page.locator('#keyword').fill('中央')
        self.assertEqual(['adult'],self.ids(page))
        page.locator('#keyword').fill('不存在')
        self.assertEqual([],self.ids(page))
        page.locator('#clear-filters').focus()
        page.keyboard.press('Space')
        self.assertEqual(EXPECTED['index.html'],self.ids(page))
        self.assertEqual('true',page.locator('[data-category="all"]').get_attribute('aria-pressed'))
        page.locator('.listing-nav a[href="/keiko/"]').focus()
        page.keyboard.press('Enter')
        page.wait_for_function("document.querySelector('#meta').textContent.includes('生成日時')")
        self.assertEqual(EXPECTED['keiko/index.html'],self.ids(page))
        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
    def test_page_layout_at_mobile_and_desktop_widths(self):
        for key in EXPECTED:
            for mobile in (True, False):
                with self.subTest(key=key, mobile=mobile):
                    page = self.load_page(key, mobile=mobile)
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                    self.assertTrue(page.locator('#search-heading').is_visible())
                    for link in page.locator('.listing-nav a').all():
                        self.assertTrue(link.is_visible())
                    for button in page.locator('[data-category]').all():
                        self.assertGreaterEqual(button.bounding_box()['height'], 44)
                    screenshot_dir = os.environ.get('LISTING_SCREENSHOTS')
                    if screenshot_dir:
                        Path(screenshot_dir).mkdir(parents=True, exist_ok=True)
                        name = key.split('/')[0].replace('index.html', 'all')
                        width = 'mobile' if mobile else 'desktop'
                        # Capture the listing rather than the long organization directory.
                        page.set_viewport_size({'width':375 if mobile else 1280, 'height':2000 if mobile else 1400})
                        page.screenshot(path=str(Path(screenshot_dir)/f'{name}-{width}.png'))

    def test_static_fallback_and_empty_pages(self):
        for key, expected in EXPECTED.items():
            for javascript,failure in [(False,False),(True,True)]:
                with self.subTest(key=key,javascript=javascript):
                    page=self.load_page(key,javascript=javascript,failure=failure)
                    self.assertEqual(expected,self.ids(page))
                    self.assertTrue(page.locator('#cards .card').first.is_visible())
                    self.assertEqual(3,page.locator('.listing-nav a').count())
        page=self.load_page('renseikai/index.html',empty=True,failure=True)
        self.assertEqual([],self.ids(page))
        self.assertIn('現在掲載中のイベントはありません',page.locator('#cards').inner_text())
        page=self.load_page('renseikai/index.html',empty=True)
        self.assertEqual([],self.ids(page))
        self.assertIn('0件',page.locator('#count').inner_text())

    def test_cloudfront_function_executes_with_queries_and_unrelated_paths(self):
        page=self.browser.new_page()
        self.addCleanup(page.close)
        code=(ROOT/'infra/cloudfront/category-urls.js').read_text()
        def invoke(uri,query=None,method='GET'):
            return page.evaluate('(event) => {'+code+'; return handler(event);}',{'request':{'uri':uri,'method':method,'querystring':query or {},'headers':{}}})
        query={'q':{'value':'%E5%89%A3%E9%81%93+%26%3D'},'tag':{'value':'one','multiValue':[{'value':'one'},{'value':'two'}]},'empty':{'value':''}}
        for category in ['keiko','renseikai']:
            for method in ['GET','HEAD']:
                response=invoke('/'+category,query,method)
                self.assertEqual(301,response['statusCode'])
                self.assertEqual('/'+category+'/?q=%E5%89%A3%E9%81%93+%26%3D&tag=one&tag=two&empty=',response['headers']['location']['value'])
                rewritten=invoke('/'+category+'/',query,method)
                self.assertEqual('/'+category+'/index.html',rewritten['uri'])
                self.assertEqual(query,rewritten['querystring'])
            self.assertEqual('/'+category+'/',invoke('/'+category)['headers']['location']['value'])
        for uri in ['/','/events.json','/keiko/index.html','/keiko/other','/keikoo','/renseikai-other','/favicon.svg','/unknown/']:
            self.assertEqual({'uri':uri,'method':'GET','querystring':query,'headers':{}},invoke(uri,query))
        self.assertEqual('/keiko',invoke('/keiko',method='POST')['uri'])
