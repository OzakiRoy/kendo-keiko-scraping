import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from bs4 import BeautifulSoup
from kendo_keiko.manual_events import merge_public_events
from kendo_keiko.publication import publish_public_site
from kendo_keiko.static_site import render_listing_pages, build_sitemap_xml

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {'index.html': ['adult', 'missing', 'open', 'unknown', 'federation', 'adult-later'],
            'keiko/index.html': ['open', 'federation'],
            'renseikai/index.html': ['adult', 'adult-later']}


def public_fixture():
    payload = json.loads((ROOT / 'tests/fixtures/listing_events.json').read_text())
    payload['events'] = merge_public_events(automatic_events=payload['events'], manual_events=[], from_date='2026-09-20')
    payload['event_count'] = len(payload['events'])
    return payload


def fixture_pages():
    return render_listing_pages((ROOT / 'public/index.html').read_text(), public_fixture())


class ListingPagesTests(unittest.TestCase):
    def test_static_scope_counts_seo_and_idempotence(self):
        payload = public_fixture()
        original = copy.deepcopy(payload)
        pages = fixture_pages()
        for key, html in pages.items():
            with self.subTest(key=key):
                soup = BeautifulSoup(html, 'html.parser')
                self.assertEqual(EXPECTED[key], [c['data-event-id'] for c in soup.select('.card')])
                self.assertIn(str(len(EXPECTED[key]))+'件', soup.select_one('#count').text)
                url = 'https://kendo-keiko.com/' + key.replace('index.html','')
                self.assertEqual(url, soup.select_one('[rel=canonical]')['href'])
                self.assertEqual(url, soup.select_one('[property="og:url"]')['content'])
                self.assertEqual(soup.title.text, soup.select_one('[property="og:title"]')['content'])
                self.assertEqual(soup.select_one('[name=description]')['content'], soup.select_one('[property="og:description"]')['content'])
                self.assertEqual(3, len(soup.select('.listing-nav a')))
                self.assertEqual(1, len(soup.select('.listing-nav [aria-current=page]')))
                for asset in soup.select('img[src], link[rel=icon], link[rel=manifest]'):
                    self.assertTrue((asset.get('src') or asset['href']).startswith('/'))
                self.assertEqual(html, render_listing_pages(html, payload)[key])
        self.assertEqual(original, payload)
        self.assertEqual(2, pages['index.html'].count('class="event-kind">種別未分類'))
        self.assertEqual(3, len({BeautifulSoup(h,'html.parser').title.text for h in pages.values()}))
        root = ElementTree.fromstring(build_sitemap_xml())
        self.assertEqual(3, len(root))

    def test_cli_generates_all_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'events.json'
            source.write_text(json.dumps(public_fixture()))
            subprocess.run([sys.executable, str(ROOT/'scripts/generate_event_section.py'), '--events', str(source), '--output-dir', str(root/'site')], cwd='/tmp', check=True, capture_output=True)
            for key, expected in fixture_pages().items():
                self.assertEqual(expected, (root/'site'/key).read_text())
            self.assertTrue((root/'site/sitemap.xml').exists())

    def test_publisher_outputs_every_page_from_same_public_payload(self):
        objects = {}
        def upload(**kwargs): objects[kwargs['key']] = kwargs
        with patch('kendo_keiko.publication.query_events_from_dynamodb', return_value=public_fixture()['events']), patch('kendo_keiko.publication.load_manual_events', return_value=[]), patch('kendo_keiko.publication.upload_text_to_s3', side_effect=upload), patch('kendo_keiko.publication.publish_public_assets', return_value=[]):
            result = publish_public_site(table_name='test', region_name='ap-northeast-1', from_date='2026-09-20', events_bucket='test')
        self.assertTrue(result['listing_pages_published'])
        self.assertEqual(set(EXPECTED), set(result['listing_page_keys']))
        payload = json.loads(objects['events.json']['body'])
        rendered = render_listing_pages((ROOT/'public/index.html').read_text(), payload)
        for key, html in rendered.items():
            self.assertEqual(html, objects[key]['body'])
            self.assertEqual('text/html; charset=utf-8', objects[key]['content_type'])
        self.assertNotIn('cancelled', [e['event_id'] for e in payload['events']])
        self.assertNotIn('past', [e['event_id'] for e in payload['events']])

    def test_template_definition_is_current_and_missing_types_are_not_inferred(self):
        from kendo_keiko.static_site import render_page_shell
        from kendo_keiko.listing import select_events, type_label
        template = (ROOT/'public/index.html').read_text()
        self.assertEqual(template, render_page_shell(template, 'all', 'https://kendo-keiko.com/'))
        for event in ({}, {'event_type': None}, {'event_type': 'future_type'},
                      {'event_type': ['open_keiko']}):
            self.assertEqual([event], select_events([event], 'all'))
            self.assertEqual([], select_events([event], 'keiko'))
            self.assertEqual([], select_events([event], 'renseikai'))
            self.assertEqual('種別未分類', type_label(event))
