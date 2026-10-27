#!/usr/bin/env python3
"""Build the GitHub Pages site from presentation sources and the current viewer.

No database is read during a build. The reviewed public snapshot is the only
knowledge artifact copied into the output.
"""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / '.website-build'


def build():
    source = ROOT / 'website'
    viewer = ROOT / 'scripts' / 'viewer'
    # Deliberately fixed output: never recursively remove a caller-supplied path.
    if OUTPUT.is_symlink() or OUTPUT.resolve().parent != ROOT.resolve():
        raise ValueError('Website output must remain inside this checkout')
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir()
    for name in ('index.html', 'site.css', 'site.js'):
        shutil.copy2(source / name, OUTPUT / name)
    if (source / 'assets').exists():
        shutil.copytree(source / 'assets', OUTPUT / 'assets')
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
    for asset in ('style.css', 'cytoscape.min.js', 'graph-layout.js', 'app.js'):
        html = html.replace('"/' + asset + '"', '"./' + asset + '"')
    marker = '<script defer src="./app.js"></script>'
    if marker not in html:
        raise ValueError('Viewer entrypoint changed; update the website adapter injection')
    html = html.replace(marker,
                        '<link rel="stylesheet" href="./demo.css">'
                        '<script defer src="./static-api.js"></script>'
                        '<script defer src="./demo.js"></script>'
                        '<script defer src="./app.js"></script>')
    html = html.replace('</head>', '<link rel="icon" href="../assets/mark.svg" type="image/svg+xml"></head>')
    (demo / 'index.html').write_text(html, encoding='utf-8')
    (OUTPUT / '.nojekyll').touch()
    print(f'Built website: {OUTPUT}')


if __name__ == '__main__':
    build()
