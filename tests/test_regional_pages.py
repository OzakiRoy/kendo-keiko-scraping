import copy
import json
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from kendo_keiko.listing import KANTO_PREFECTURES, REGIONS, event_prefecture, select_region_events
from kendo_keiko.regional import render_regional_page
from kendo_keiko.static_site import render_listing_pages
from tests.test_listing_pages import ROOT, REGIONAL_EXPECTED, fixture_pages, public_fixture


class RegionalPagesTests(unittest.TestCase):
    def test_venue_region_is_strict_and_never_inferred_from_organization(self):
        for prefecture in KANTO_PREFECTURES:
            for suffix in ('', ' 市民体育館', '中央区'):
                with self.subTest(area=prefecture+suffix):
                    self.assertEqual(prefecture, event_prefecture({'area': prefecture+suffix}))
        for area in (None, '', 123, '関東', '全国', '大阪府', '新宿区', '東京都・埼玉県',
                     '東京都 / 大阪府', '東京都（神奈川県も開催）', '開催地：東京都'):
            self.assertEqual('', event_prefecture({'area':area, 'organization_name':'東京都団体'}))
        events=[{'event_id':'local','area':'東京都'}, {'event_id':'osaka','area':'大阪府'},
                {'event_id':'unknown','area':None}, {'event_id':'saitama','area':'埼玉県'}]
        before=copy.deepcopy(events)
        self.assertEqual(['local'],[e['event_id'] for e in select_region_events(events,'tokyo')])
        self.assertEqual(['local','saitama'],[e['event_id'] for e in select_region_events(events,'kanto')])
        self.assertEqual(before,events)

    def test_static_cards_meta_organizations_navigation_and_footer(self):
        template=(ROOT/'public/index.html').read_text()
        footer=BeautifulSoup(template,'html.parser').select_one('.site-footer')
        pages=fixture_pages()
        for region, definition in REGIONS.items():
            html=pages[definition['key']]
            soup=BeautifulSoup(html,'html.parser')
            with self.subTest(region=region):
                self.assertEqual(REGIONAL_EXPECTED[definition['key']], [e['data-event-id'] for e in soup.select('#static-fallback .card')])
                self.assertEqual(str(len(REGIONAL_EXPECTED[definition['key']])),soup.select_one('#scope-total').text)
                self.assertEqual('https://kendo-keiko.com'+definition['path'],soup.select_one('[rel=canonical]')['href'])
                self.assertEqual(definition['title'],soup.title.text)
                self.assertIn(definition['name'],soup.h1.text)
                self.assertIn('2026-09-20T09:00:00+09:00',soup.select_one('.area-meta').text)
                self.assertEqual(str(footer),str(soup.select_one('.site-footer')))
                self.assertEqual(['/area/kanto/','/area/tokyo/'],[a['href'] for a in soup.select('.scope-nav a')])
                self.assertEqual(1,len(soup.select('.scope-nav [aria-current=page]')))
                self.assertEqual(1,len(soup.select('link[href="/assets/site.css"]')))
                self.assertEqual(1,len(soup.select('link[href="/assets/calendar.css"]')))
                self.assertNotIn('noindex',html)
                self.assertNotIn('fonts.googleapis.com',html)
                self.assertNotIn('preview',html)
                self.assertEqual(len(soup.select('[id]')),len({e['id'] for e in soup.select('[id]')}))
                self.assertEqual(html,render_regional_page(html,public_fixture(),region,site_url='https://kendo-keiko.com/'))
                config=json.loads(soup.select_one('#regional-data').string)
                self.assertEqual(region,config['region'])
                self.assertEqual({e['organization_id'] for e in config['events']}, {o['organization_id'] for o in config['organizations']})
                self.assertNotIn('gsi1_pk',config['events'][0])
        for html in pages.values():
            soup=BeautifulSoup(html,'html.parser')
            self.assertTrue(soup.select_one('a[href="/area/kanto/"]'))
            self.assertTrue(soup.select_one('a[href="/area/tokyo/"]'))

    def test_empty_region_still_has_content_and_links(self):
        pages=render_listing_pages((ROOT/'public/index.html').read_text(),{'events':[]})
        for definition in REGIONS.values():
            soup=BeautifulSoup(pages[definition['key']],'html.parser')
            self.assertIn('現在の掲載情報はありません',soup.select_one('#static-fallback').text)
            self.assertEqual('0',soup.select_one('#scope-total').text)
            self.assertTrue(soup.select_one('#static-fallback a[href="/"]'))
            self.assertTrue(soup.select_one('.regional-information'))

    def test_official_notes_html_escaping_and_safe_links_survive(self):
        payload=public_fixture()
        item=next(e for e in payload['events'] if e['event_id']=='open')
        item.update(title='女子対象 <公式>', raw_note='対象条件 </script><script>window.bad=true</script>',
                    source_url='javascript:alert(1)',gsi1_pk='INTERNAL')
        html=render_listing_pages((ROOT/'public/index.html').read_text(),payload)['area/tokyo/index.html']
        soup=BeautifulSoup(html,'html.parser')
        card=soup.select_one('[data-event-id="open"]')
        self.assertIn('女子対象 <公式>',card.text)
        self.assertIn('対象条件 </script><script>window.bad=true</script>',card.text)
        self.assertFalse(card.select('script'))
        self.assertFalse(card.select('a'))
        self.assertNotIn('INTERNAL',html)
        self.assertNotIn('<script>window.bad=true</script>',html)
        self.assertIn('女子対象 <公式>',json.loads(soup.select_one('#regional-data').string)['events'][2]['title'])

    def test_scope_json_matches_public_cards_including_federations_and_unknown_types(self):
        for key,expected in REGIONAL_EXPECTED.items():
            soup=BeautifulSoup(fixture_pages()[key],'html.parser')
            config=json.loads(soup.select_one('#regional-data').string)
            self.assertEqual(expected,[e['event_id'] for e in config['events']])
            self.assertEqual(len(expected),len(soup.select('#static-fallback .card')))
            self.assertNotIn('cancelled',expected)
            self.assertNotIn('past',expected)
        self.assertIn('federation',REGIONAL_EXPECTED['area/kanto/index.html'])
        self.assertIn('unknown',REGIONAL_EXPECTED['area/tokyo/index.html'])
