"""Check the actual Pages artifact, not only presentation templates.

Run scripts/build_website.py first. Uses only the Python standard library.
"""
from html.parser import HTMLParser
import json
from pathlib import Path
import unittest
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / '.website-build'
SITE = 'https://artemrizhov.github.io/EvoMneme/'


class Page(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.tags = []
        self.ids = set()
        self.headings = []
        self.title = []
        self.content = []
        self.jsonld = []
        self.stack = []
        self.feed(path.read_text(encoding='utf-8'))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if 'id' in attrs:
            self.ids.add(attrs['id'])
        if tag in ('script', 'style', 'title') or tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self.stack.append(tag)
        if tag.startswith('h') and tag[1:] in ('1', '2', '3', '4', '5', '6'):
            self.headings.append([int(tag[1]), ''])
        if tag == 'script' and attrs.get('type') == 'application/ld+json':
            self.jsonld.append('')

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()

    def handle_data(self, data):
        if self.stack and self.stack[-1] == 'script':
            if self.jsonld:
                self.jsonld[-1] += data
        elif not (self.stack and self.stack[-1] == 'style'):
            if self.stack and self.stack[-1] == 'title':
                self.title.append(data)
            elif self.stack and self.stack[-1].startswith('h'):
                self.headings[-1][1] += data
            self.content.append(data)

    def meta(self, key):
        return [a['content'] for t, a in self.tags if t == 'meta'
                and (a.get('name') == key or a.get('property') == key)]

    def canonical(self):
        return [a['href'] for t, a in self.tags if t == 'link' and a.get('rel') == 'canonical']


class WebsiteSEO(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (OUTPUT / 'index.html').is_file():
            raise RuntimeError('Run python scripts/build_website.py before SEO checks')
        cls.landing = Page(OUTPUT / 'index.html')
        cls.demo = Page(OUTPUT / 'demo/index.html')

    def test_static_identity_and_social_metadata(self):
        p = self.landing
        self.assertIn('EvoMneme', ''.join(p.title))
        h1 = [text for level, text in p.headings if level == 1]
        self.assertEqual(len(h1), 1)
        self.assertIn('EvoMneme', h1[0])
        self.assertIn('local SQLite graph', ''.join(p.content))
        previous = 0
        for level, text in p.headings:
            self.assertLessEqual(level, previous + 1, text)
            previous = level
        self.assertEqual(p.canonical(), [SITE])
        for key in ('description', 'og:description', 'twitter:description'):
            self.assertEqual(len(p.meta(key)), 1)
            self.assertIn('EvoMneme', p.meta(key)[0])
        self.assertEqual(p.meta('og:url'), [SITE])
        self.assertEqual(p.meta('og:site_name'), ['EvoMneme'])
        self.assertEqual(p.meta('og:title'), [''.join(p.title)])
        self.assertEqual(p.meta('twitter:title'), p.meta('og:title'))
        self.assertEqual(p.meta('twitter:card'), ['summary_large_image'])
        self.assertEqual(p.meta('twitter:image'), p.meta('og:image'))
        image = p.meta('og:image')[0]
        self.assertTrue(image.startswith(SITE))
        self.assertTrue((OUTPUT / image.removeprefix(SITE)).is_file())

    def test_structured_project_and_sitemap(self):
        self.assertEqual(len(self.landing.jsonld), 1)
        project = json.loads(self.landing.jsonld[0])
        self.assertEqual(project['@context'], 'https://schema.org')
        self.assertEqual(project['@type'], 'SoftwareSourceCode')
        self.assertEqual(project['name'], 'EvoMneme')
        self.assertEqual(project['url'], SITE)
        self.assertEqual(project['codeRepository'], 'https://github.com/artemrizhov/EvoMneme')
        self.assertIn('EvoMneme', project['description'])
        urls = ET.parse(OUTPUT / 'sitemap.xml').findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc')
        self.assertEqual([u.text for u in urls], [SITE])
        self.assertIn(('link', {'rel': 'sitemap', 'type': 'application/xml', 'href': 'sitemap.xml'}), self.landing.tags)
        robots = (OUTPUT / 'robots.txt').read_text(encoding='utf-8')
        self.assertIn('Sitemap: ' + SITE + 'sitemap.xml', robots)
        self.assertFalse(any(line.lower().startswith('disallow:') and line.split(':', 1)[1].strip()
                             for line in robots.splitlines()))

    def test_demo_has_separate_canonical_and_no_crawl_block(self):
        self.assertEqual(self.demo.canonical(), [SITE + 'demo/'])
        self.assertIn('requires JavaScript', self.demo.meta('description')[0])
        for p in (self.landing, self.demo):
            for tag, attrs in p.tags:
                if tag == 'meta' and attrs.get('name', '').lower() in ('robots', 'googlebot', 'bingbot'):
                    self.assertNotIn('noindex', attrs.get('content', '').lower())
                    self.assertNotIn('nofollow', attrs.get('content', '').lower())
                if tag == 'a':
                    self.assertNotIn('nofollow', attrs.get('rel', '').split())

    def test_landing_local_links_assets_and_repository_targets(self):
        for tag, attrs in self.landing.tags:
            for field in ('href', 'src'):
                if field not in attrs:
                    continue
                url = urlsplit(attrs[field])
                if url.netloc == 'github.com' and url.path.startswith('/artemrizhov/EvoMneme/blob/main/'):
                    path = unquote(url.path.split('/blob/main/', 1)[1])
                    self.assertTrue((ROOT / path).is_file(), attrs[field])
                if url.scheme or url.netloc:
                    continue
                path = OUTPUT / unquote(url.path)
                if path.is_dir():
                    path /= 'index.html'
                self.assertTrue(path.is_file(), attrs[field])
                if url.fragment:
                    self.assertIn(unquote(url.fragment), Page(path).ids, attrs[field])


if __name__ == '__main__':
    unittest.main()
