#!/usr/bin/env python3
"""Build the GitHub Pages site from presentation sources and the current viewer.

No database is read during a build. The reviewed public snapshot is the only
knowledge artifact copied into the output.
"""
from pathlib import Path
from hashlib import sha256
import shutil
import json
import os
import re
from html import escape

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / '.website-build'


def deployment_config():
    """Deployment-only information; never load an operator's config in a fork."""
    raw = os.environ.get('WEBSITE_DEPLOYMENT_CONFIG', '')
    config = json.loads(raw) if raw else {}
    if not isinstance(config, dict):
        raise ValueError('Website configuration must be a JSON object')
    if config:
        for field in ('measurement_id', 'operator_name', 'operator_email', 'site_url'):
            if not isinstance(config.get(field), str) or not config[field].strip():
                raise ValueError('Missing website configuration field: ' + field)
        if not re.fullmatch(r'G-[A-Z0-9]+', config['measurement_id']):
            raise ValueError('Invalid measurement ID')
        if config['site_url'] != 'https://artemrizhov.github.io/EvoMneme/':
            raise ValueError('Deployment configuration is not bound to this website')
        if not re.fullmatch(r'[^\s<>"@]+@[^\s<>"@]+', config['operator_email']):
            raise ValueError('Invalid operator email')
    return config


def build():
    config = deployment_config()
    source = ROOT / 'website'
    viewer = ROOT / 'scripts' / 'viewer'
    # Deliberately fixed output: never recursively remove a caller-supplied path.
    if OUTPUT.is_symlink() or OUTPUT.resolve().parent != ROOT.resolve():
        raise ValueError('Website output must remain inside this checkout')
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir()
    for name in ('index.html', 'site.css', 'site.js', 'analytics.js', 'analytics.css', 'privacy.css', 'robots.txt', 'sitemap.xml'):
        shutil.copy2(source / name, OUTPUT / name)
    (OUTPUT / 'privacy').mkdir()
    shutil.copy2(source / 'privacy' / 'index.html', OUTPUT / 'privacy' / 'index.html')
    if (source / 'assets').exists():
        shutil.copytree(source / 'assets', OUTPUT / 'assets')
    (OUTPUT / 'assets' / 'images').mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'assets' / 'images' / 'evomneme-graph.png',
                 OUTPUT / 'assets' / 'images' / 'evomneme-graph.png')
    (OUTPUT / 'assets' / 'videos').mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'assets' / 'videos' / 'evomneme-graph.mp4',
                 OUTPUT / 'assets' / 'videos' / 'evomneme-graph.mp4')
    (OUTPUT / 'data').mkdir()
    for name in ('demo.json', 'replay.json', 'history.json'):
        shutil.copy2(source / 'data' / name, OUTPUT / 'data' / name)
    demo = OUTPUT / 'demo'
    demo.mkdir()
    for name in ('app.js', 'graph-layout.js', 'layout-worker.js', 'style.css'):
        shutil.copy2(viewer / name, demo / name)
    shutil.copy2(viewer / 'vendor' / 'cytoscape.min.js', demo / 'cytoscape.min.js')
    shutil.copy2(viewer / 'vendor' / 'LICENSE.cytoscape', demo / 'LICENSE.cytoscape')
    for name in ('static-api.js', 'demo.js', 'demo.css'):
        shutil.copy2(source / 'demo' / name, demo / name)
    html = (viewer / 'index.html').read_text(encoding='utf-8')
    html = html.replace('<title>EvoMneme · Memory explorer</title>',
                        '<title>EvoMneme · Interactive public graph</title>')
    html = html.replace('<h1 id="projectName" class="project-title"></h1>',
                        '<h1 id="projectName" class="project-title">EvoMneme</h1>')
    intro = (source / 'demo' / 'intro.html').read_text(encoding='utf-8')
    html = html.replace('<body>', '<body>\n' + intro, 1)
    demo_css_version = sha256((source / 'demo' / 'demo.css').read_bytes()).hexdigest()[:12]
    for asset in ('style.css', 'cytoscape.min.js', 'graph-layout.js', 'app.js'):
        html = html.replace('"/' + asset + '"', '"./' + asset + '"')
    marker = '<script defer src="./app.js"></script>'
    if marker not in html:
        raise ValueError('Viewer entrypoint changed; update the website adapter injection')
    html = html.replace(marker,
                        f'<link rel="stylesheet" href="./demo.css?v={demo_css_version}">'
                        '<script defer src="./static-api.js"></script>'
                        '<script defer src="./demo.js"></script>'
                        '<script defer src="./app.js"></script>')
    html = html.replace('</head>',
                        '<link rel="icon" href="../assets/mark.svg" type="image/svg+xml">'
                        '<link rel="canonical" href="https://artemrizhov.github.io/EvoMneme/demo/">'
                        '<meta name="description" content="Explore EvoMneme’s read-only project knowledge graph and saved history. This interactive demo requires JavaScript.">'
                        '<link rel="stylesheet" href="../analytics.css">'
                        '<script defer src="../analytics.js"></script>'
                        '</head>')
    html = html.replace('</footer>', '<a href="../privacy/">Privacy &amp; Cookies</a>'
                        '<a href="../privacy/#choices" data-cookie-settings>Cookie settings</a></footer>')
    (demo / 'index.html').write_text(html, encoding='utf-8')
    for page in (OUTPUT / 'index.html', OUTPUT / 'privacy/index.html', demo / 'index.html'):
        text = page.read_text(encoding='utf-8')
        if page == OUTPUT / 'privacy/index.html':
            if config:
                for key in ('operator_name', 'operator_email'):
                    text = text.replace('{{' + key + '}}', escape(config[key], quote=True))
                text = text.replace('{{measurement_suffix}}', escape(config['measurement_id'][2:]))
            else:
                text = re.sub(r'<main\b.*?</main>', '''<main id="main" class="privacy-content">
    <h1>Privacy &amp; Cookies</h1>
    <p>This build has no optional analytics enabled and does not set analytics cookies.
    No analytics consent preference is stored.</p>
    <h2>Hosting and external links</h2>
    <p>The hosting provider receives connection information needed to deliver pages.
    On GitHub Pages, see the <a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement">GitHub Privacy Statement</a>.
    External services have their own privacy terms.</p>
    <h2 id="choices">Your choices</h2>
    <p>There are no optional analytics cookies to accept in this build.</p>
    <p>Operators of other deployments are responsible for their own processing and privacy notice.</p>
  </main>''', text, flags=re.S)
                text = re.sub(r'<a href="mailto:.*?</a>', '', text)
                text = text.replace('{{operator_email}}', '')
        if not config:
            text = re.sub(r'<a\b[^>]*data-cookie-settings[^>]*>.*?</a>', '', text)
        if page == OUTPUT / 'index.html' and config.get('search_verification'):
            text = text.replace('</head>', '<meta name="google-site-verification" content="'
                                + escape(config['search_verification'], quote=True) + '"></head>')
        if config:
            # JSON in an external JS file: escape HTML-sensitive characters as well.
            relative = '../' if page.parent != OUTPUT else ''
            text = text.replace('<script', '<script defer src="' + relative + 'deployment-config.js"></script>\n<script', 1)
        page.write_text(text, encoding='utf-8')
    if config:
        public = {'measurementId': config['measurement_id']}
        payload = json.dumps(public).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
        (OUTPUT / 'deployment-config.js').write_text('window.evomnemeDeployment = ' + payload + ';\n', encoding='utf-8')
    (OUTPUT / '.nojekyll').touch()
    print(f'Built website: {OUTPUT}')


if __name__ == '__main__':
    build()
