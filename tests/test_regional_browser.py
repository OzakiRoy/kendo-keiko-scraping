"""Regional page behavior in the repository's pinned Chromium; no live traffic."""
import datetime as dt
import os
import unittest
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from kendo_keiko.static_site import render_listing_pages
from tests.test_listing_pages import ROOT, REGIONAL_EXPECTED, public_fixture

os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(ROOT/'.venv/browsers'))


class RegionalBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright=sync_playwright().start()
        try:
            cls.browser=cls.playwright.chromium.launch(timeout=30_000)
        except Exception:
            cls.playwright.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def load_page(self,region='kanto',*,width=1280,javascript=True,failure=False,empty=False):
        context=self.browser.new_context(viewport={'width':width,'height':1000},java_script_enabled=javascript,
                                         timezone_id='America/Los_Angeles')
        self.addCleanup(context.close)
        context.set_default_timeout(15_000)
        payload=public_fixture()
        if empty:payload['events']=[]
        pages=render_listing_pages((ROOT/'public/index.html').read_text(),payload)
        asset_errors=[]
        def route(request):
            url=urlsplit(request.request.url)
            path=url.path
            if url.netloc!='regional.test':
                request.abort()
            elif path.endswith('/'):
                key=path.lstrip('/')+'index.html'
                request.fulfill(body=pages[key],content_type='text/html')
            elif failure and path=='/assets/regional-calendar.js':
                request.abort()
            elif path=='/events.json':
                request.fulfill(json=payload)
            else:
                asset=ROOT/'public'/path.lstrip('/')
                if path.startswith('/assets/fonts/'):
                    asset=ROOT/'assets/fonts/web'/path.rsplit('/',1)[-1]
                if asset.is_file():request.fulfill(path=asset)
                else:
                    asset_errors.append(path)
                    request.fulfill(status=404)
        context.route('**/*',route)
        page=context.new_page()
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.clock.install(time=dt.datetime(2026,9,20,tzinfo=dt.timezone.utc))
        page.goto('https://regional.test/area/'+region+'/')
        if javascript and not failure:
            page.locator('#interactive-content').wait_for(state='visible')
            page.evaluate('document.fonts.ready')
        self.assertEqual([],errors)
        self.assertEqual([],asset_errors)
        page._regional_errors=errors
        return page

    def ids(self,page,selector):
        return page.locator(selector+' .card').evaluate_all('(cards)=>cards.map(c=>c.dataset.eventId)')

    def ga_events(self,page):
        return page.evaluate("(window.dataLayer||[]).filter(a=>a[0]==='event').map(a=>Array.from(a))")

    def test_month_dense_day_keyboard_and_static_cards_are_preserved(self):
        page=self.load_page()
        self.assertEqual('条件に一致 5件',page.locator('#period-count').inner_text())
        self.assertEqual([],self.ga_events(page))
        self.assertEqual(REGIONAL_EXPECTED['area/kanto/index.html'],self.ids(page,'#static-fallback'))
        self.assertIn('ほか2件',page.locator('[data-date="2026-09-26"]').inner_text())
        page.locator('[data-date="2026-09-26"]').click()
        self.assertEqual(['adult','missing','open','unknown'],self.ids(page,'#day-results'))
        self.assertEqual([],self.ids(page,'#list-results'))
        self.assertTrue(page.evaluate("(()=>{const ids=[...document.querySelectorAll('[id]')].map(x=>x.id);return ids.length===new Set(ids).size})()"))
        page.keyboard.press('ArrowRight')
        self.assertEqual('2026-09-27',page.evaluate('document.activeElement.dataset.date'))
        page.keyboard.press('Enter')
        self.assertEqual(['federation'],self.ids(page,'#day-results'))
        self.assertEqual('2026-09-27',page.evaluate('document.activeElement.dataset.date'))
        self.assertEqual('schedule_day_select',self.ga_events(page)[-1][1])

    def test_filters_survive_view_and_period_switches_and_reset_keeps_month(self):
        page=self.load_page()
        page.locator('#filter-prefecture').select_option('東京都')
        page.locator('#filter-category').select_option('renseikai')
        page.locator('#filter-organization').select_option('mixed')
        page.locator('#filter-participation').select_option('registration_required')
        page.locator('#filter-keyword').fill('中央')
        self.assertEqual('条件に一致 1件',page.locator('#period-count').inner_text())
        page.locator('[data-view="list"]').click()
        self.assertEqual(['adult'],self.ids(page,'#list-results'))
        self.assertFalse(page.locator('#calendar-detail').is_visible())
        page.locator('[data-view="calendar"]').click()
        self.assertEqual(['adult'],self.ids(page,'#day-results'))
        self.assertEqual('東京都',page.locator('#filter-prefecture').input_value())
        self.assertEqual('中央',page.locator('#filter-keyword').input_value())
        page.locator('#next-period').click()
        self.assertEqual('条件に一致 0件',page.locator('#period-count').inner_text())
        page.locator('[data-action="reset-filters"]').first.click()
        self.assertEqual('2026年10月',page.locator('#period-title').inner_text())
        self.assertEqual('条件に一致 1件',page.locator('#period-count').inner_text())
        self.assertEqual(['adult-later'],self.ids(page,'#day-results'))
        page.locator('[data-period="month"]').click()
        self.assertEqual('2026年10月',page.locator('#period-title').inner_text())
        self.assertEqual(['schedule_view_change','schedule_view_change','schedule_period_change'],[e[1] for e in self.ga_events(page)])

    def test_mobile_weekends_detail_focus_and_official_link_measurement(self):
        page=self.load_page(width=390)
        self.assertIn('9/19',page.locator('#period-title').inner_text())
        self.assertIn('過去の日程',page.locator('.weekend-column').first.inner_text())
        page.locator('[data-period="next-weekend"]').click()
        self.assertEqual(2,page.locator('.weekend-column').count())
        self.assertEqual('条件に一致 5件',page.locator('#period-count').inner_text())
        page.locator('[data-event="open"]').click()
        self.assertEqual('event-open',page.evaluate('document.activeElement.id'))
        self.assertTrue(page.locator('#event-open').is_visible())
        with page.expect_popup() as popup:
            page.locator('#event-open a').click()
        popup.value.close()
        self.assertEqual('event_source_click',self.ga_events(page)[-1][1])
        self.assertEqual({'area_page':'kanto','view_mode':'calendar','period_mode':'weekend','event_type':'open_keiko'},self.ga_events(page)[-1][2])
        page.locator('[data-view="list"]').click()
        self.assertEqual(['adult','missing','open','unknown','federation'],self.ids(page,'#list-results'))
        page.locator('#next-period').click()
        self.assertEqual('条件に一致 0件',page.locator('#period-count').inner_text())
        self.assertEqual([],page._regional_errors)

    def test_javascript_disabled_failed_script_and_empty_region(self):
        for region in ('kanto','tokyo'):
            for javascript,failure in ((False,False),(True,True)):
                with self.subTest(region=region,javascript=javascript):
                    page=self.load_page(region,javascript=javascript,failure=failure)
                    self.assertTrue(page.locator('#static-fallback').is_visible())
                    self.assertEqual(REGIONAL_EXPECTED['area/'+region+'/index.html'],self.ids(page,'#static-fallback'))
                    self.assertEqual(2,page.locator('.scope-nav a').count())
                    self.assertIn('ご利用にあたって',page.locator('.site-footer').inner_text())
        page=self.load_page(empty=True)
        self.assertEqual('条件に一致 0件',page.locator('#period-count').inner_text())
        self.assertIn('掲載情報がありません',page.locator('#day-results').inner_text())

    def test_region_navigation_viewports_fonts_and_no_horizontal_scroll(self):
        for region in ('kanto','tokyo'):
            for width in (320,390,768,1440):
                with self.subTest(region=region,width=width):
                    page=self.load_page(region,width=width)
                    if region=='tokyo':self.assertTrue(page.locator('#filter-prefecture').is_disabled())
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    page.locator('[data-period="month"]').click()
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    page.locator('[data-view="list"]').click()
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    self.assertEqual([],page._regional_errors)
                    directory=os.environ.get('REGIONAL_SCREENSHOTS')
                    if directory:
                        from pathlib import Path
                        target=Path(directory);target.mkdir(parents=True,exist_ok=True)
                        page.locator('[data-view="calendar"]').click()
                        page.screenshot(path=str(target/(region+'-'+str(width)+'.png')),full_page=True)
                    page.context.close()
        page=self.load_page('tokyo')
        page.locator('.scope-nav a[href="/area/kanto/"]').click()
        page.wait_for_url('**/area/kanto/')
        self.assertIn('関東',page.locator('h1').inner_text())
        self.assertEqual('6',page.locator('#scope-total').inner_text())

    def test_calendar_core_date_boundaries_participation_and_ambiguous_areas(self):
        page=self.load_page()
        result=page.evaluate("""() => {
          const c=KendoCalendarCore;
          const base={status:'active',event_date:'2026-09-26',area:'東京都',event_type:'open_keiko',participation_type:'contact_required',application_required:true};
          return {
            leap:c.monthBounds('2028-02'), invalid:c.parseDate('2026-02-29'),
            year:c.addMonths('2026-12',1), newYear:c.addDays('2026-12-31',1),
            sunday:c.weekendOf('2026-09-20'), monday:c.weekendOf('2026-09-21'),
            jst:c.todayJst(new Date('2026-09-19T15:00:00Z')),
            grid:c.monthDays('2026-10'),
            ambiguous:c.prefecture({...base,area:'東京都 / 大阪府'}),
            registration:c.filterEvents([base],{scope:'tokyo',participation:'registration_required'}).length,
            conflicting:c.participationType({...base,participation_type:'registration_required',application_required:false}),
            dense:c.visibleDaySummary(Array.from({length:12},(_,i)=>({...base,event_id:String(i)})),2).remaining
          };
        }""")
        self.assertEqual({'from':'2028-02-01','to':'2028-02-29'},result['leap'])
        self.assertIsNone(result['invalid'])
        self.assertEqual('2027-01',result['year']);self.assertEqual('2027-01-01',result['newYear'])
        self.assertEqual({'from':'2026-09-19','to':'2026-09-20'},result['sunday'])
        self.assertEqual({'from':'2026-09-26','to':'2026-09-27'},result['monday'])
        self.assertEqual('2026-09-20',result['jst'])
        self.assertEqual('2026-09-28',result['grid'][0]);self.assertEqual('2026-11-01',result['grid'][-1])
        self.assertEqual('',result['ambiguous']);self.assertEqual(1,result['registration'])
        self.assertEqual('unknown',result['conflicting']);self.assertEqual(10,result['dense'])
