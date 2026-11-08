# Presentation website

The English presentation and public demo are built for GitHub Pages, without
a package install, external font service, API server, or live database.

## Build and preview

From the repository root, with the project's existing Python runtime:

```sh
python scripts/build_website.py
python -m http.server 8080 --directory .website-build
```

Open `http://localhost:8080/`. To check a repository-prefixed deployment, serve
the repository root instead and open `http://localhost:8080/.website-build/`.
All page, script, stylesheet, and snapshot references are relative.

## Shared viewer

`scripts/build_website.py` copies the **current** `scripts/viewer/` application
and its bundled Cytoscape distribution. The generated demo HTML loads a static
API adapter and public-demo chrome before the shared application. The original
viewer sources are never rewritten by the website build. Improvements to the
local renderer, layouts, inspector, and interactions flow into the next build;
changes to the local API contract should also update the adapter's tests.

`website/demo/` contains only the static data adapter and presentation overrides.
Local SQL execution and live database polling are not available in the public
snapshot. Saved graph replay and the public activity timeline use the shared
viewer controls. The demo has no SQLite engine or write endpoint.

The hero plays the supplied prerecorded MP4. Farther down, the landing page
embeds `demo/?embed=1` as an interactive preview of the saved graph. This opt-in
presentation mode uses the same application and snapshot, with compact chrome
so the graph stays visible inside a smaller frame. The dedicated `demo/` page
retains the complete public exploration interface. Keep both modes working when
updating the shared viewer; do not add a separate landing-page graph renderer.

## Public data

`data/demo.json` contains the entire saved graph from EvoMneme's own authorized
project database, including every stored node and relationship and their public
evidence attachments. Its metadata
identifies the source repository, revision, counts, and limits. This is a static
snapshot, not live indexing or a claim that the stored knowledge is complete or
infallible. Source links are pinned only when the recorded file hash matches the
public Git revision; unpublished or different file versions retain their stored
provenance without a misleading source link.

`data/replay.json` contains all saved node and relationship changes, including
typed before/after values needed by the existing replay engine. Replay starts at
the actual earliest saved baseline; it does not invent changes from before the
journal existed. `data/history.json` contains the saved changes and call timeline
with public operational fields. Only a bounded latest-events preview accompanies
the initial graph; full history loads when earlier pages are requested, and
replay loads when opened. Existing cursor controls expose earlier events. The
timeline retains a bounded display window while allowing older pages to replace
newer entries in that window; all saved events remain in the export. Runtime identities,
local paths, and private non-graph payloads are excluded from public history.

The website build copies these reviewed JSON files; it does not search for or
open a local host database. Regenerating them is a separate review step using
`scripts/export_website_demo.py`. Review the exported diff before publishing:
only public graph contents, replay deltas, and allowlisted history fields belong
here. Do not copy the original database, host instructions, conversation
identities, credentials, local paths, or unrelated knowledge.

Regenerate all three files from this project's authorized database, from the
repository root:

```sh
python scripts/export_website_demo.py --database .evomneme/knowledge.sqlite3 --output website/data/demo.json
```

Export reads that database without modifying it. The output is deterministic
for the same saved source data.

`--database` selects the input store and `--output` selects the main JSON file;
`replay.json` and `history.json` are written beside it. The exporter verifies the
store's identity against the project's excluded connection receipt. It does not
require editing a selection, a list of IDs, or a content digest for each run.

After publishing a new source revision, pass its full commit SHA explicitly to
refresh source-link proofs without editing the script:

```sh
python scripts/export_website_demo.py --database .evomneme/knowledge.sqlite3 --output website/data/demo.json --public-revision <published-40-character-commit-sha>
```

The caller must verify that this commit is publicly available. Export performs
local Git blob/hash checks, without network access; only exact matches receive
source links. The analyzed revision in the saved scope remains separate from
the public revision used for those links. Run `--help` for the command options.

The exporter requires the complete controlled EvoMneme v3 schema, including
both version markers and all mandatory tables and columns. It validates the
source before selecting data and never migrates a host database. An older or
partially migrated store must first receive a compatible published migration.
Setting a version number alone does not make an old store compatible.

The checked-in JSON remains a reviewed static snapshot independent of the host
database schema. A website build does not regenerate it. Updating the exporter
does not by itself replace that snapshot or imply that the source was migrated.

## GitHub Pages

The prepared workflow `.github/workflows/pages.yml` builds and uploads
`.website-build/` when presentation sources or the shared viewer change on
`main`, and can also run manually. In the GitHub repository, select
**Settings → Pages → Build and deployment → Source → GitHub Actions**.
The workflow requires GitHub Actions to be enabled and permission to deploy to
the `github-pages` environment. The expected repository URL is
`https://artemrizhov.github.io/EvoMneme/` with the graph at `demo/`.

The workflow deploys the committed snapshot, presentation, shared viewer, and
hero video. Regenerate and review the three JSON files before committing a demo
update; deployment does not read the local database or refresh the snapshot.
Verify the public website after the deployment job completes.

## Search indexing

The canonical landing URL is `https://artemrizhov.github.io/EvoMneme/`.
The static HTML contains the project name in its title, H1, description and body,
Open Graph/Twitter cards using the existing graph screenshot, and Schema.org
`SoftwareSourceCode` JSON-LD linking the project, repository and MIT license.
The primary content and GitHub/documentation links do not require JavaScript.
The interactive demo does require JavaScript; its canonical is `/EvoMneme/demo/`,
including for `index.html` and query variants such as `?embed=1`. It is a separate
tool, not a duplicate of the landing page. The sitemap lists only the static
landing and Privacy & Cookies page, not the JS-dependent demo or its viewer state URLs. No page uses
`noindex` or `nofollow`.

`/EvoMneme/index.html` can serve the same landing content; its canonical and the
sitemap consistently select `/EvoMneme/`. GitHub Pages enforces HTTPS and adds
the directory slash. Do not add script redirects or block duplicate URLs in
robots.txt: crawlers need to read their canonical. Canonical is a preference,
not a guarantee of the search engine's selection.

The build copies `robots.txt` and `sitemap.xml` to the deployment directory.
**Project Pages cannot publish the effective host-root robots.txt from this
repository.** Crawlers request `https://artemrizhov.github.io/robots.txt`, not
`/EvoMneme/robots.txt`. A missing root file (404) does not prohibit crawling.
If a user-site repository `artemrizhov.github.io` is maintained, add the absolute
Sitemap directive there, preserving any rules for other projects. Do not claim
the project-level file controls crawlers. The landing HTML also links the sitemap.

After deployment, the site owner can verify the URL-prefix property
`https://artemrizhov.github.io/EvoMneme/` in Google Search Console using its HTML
file or meta-tag method (DNS verification is unavailable for `github.io`).
Publish the exact verification file/tag supplied by Google, submit `sitemap.xml`,
then inspect the canonical landing URL and choose **Request indexing**. Account
verification and that request cannot be performed by this repository's build.
Optionally submit the same sitemap to Bing Webmaster Tools. These steps help
discovery but do not guarantee indexing, ranking or a particular crawl time.

See Google's guidance on [robots.txt location](https://developers.google.com/crawling/docs/robots-txt/create-robots-txt),
[canonical URLs](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls)
and [sitemaps](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap),
and the [SoftwareSourceCode vocabulary](https://schema.org/SoftwareSourceCode).

## Optional analytics

`privacy/index.html` is the static public Privacy & Cookies notice, linked from
the landing/demo footers and the consent panel. It identifies the owner using
user-supplied public contact details, describes Google/GitHub processing, optional
analytics and first-party cookies, local consent storage and withdrawal/rights.
The owner confirmed GA4 user/event retention of 2 months with reset on new user
activity enabled. The reset renews user-identifier retention, not individual
event records; cookie lifetimes and aggregated-report retention are separate.
Consent v2 asks everyone, including EEA visitors, again for this owner-specific
notice and removes the old v1 choice without carrying a grant forward. No GeoIP
service is needed: the same consent gate applies to every visitor. The page is
built with its own canonical and included in the sitemap.

The public landing page and standalone demo use GA4 stream `G-EXAMPLE000`
through `analytics.js`. The previously supplied GTM container is not installed.
The local graph explorer, local previews and embedded demo do not load Analytics.
This is optional website instrumentation requested by the maintainer; project
knowledge storage, CLI and viewer operation have no Google dependency.

The full-width **Cookies on this site** bar describes optional cookies for visit
statistics and website improvement. It links only to this website's Privacy &
Cookies notice, where Google Analytics and external provider links are disclosed.
It occupies at most half the viewport, remains visible while scrolling and has
a mint-green accept action and a clear reject action, without a backdrop or page scroll lock.
Visitors choose **Accept optional
cookies** or **Reject optional cookies**. No Google tag is loaded and
no analytics requests are sent before consent or after a saved denial (basic
consent mode). The choice is stored in project-namespaced localStorage. If storage
is blocked it applies only to the current page and the settings control notes
that the choice was not saved. Withdrawal still disables collection, but does
not reload into an older saved grant when storage cannot be changed.
The unobtrusive **Cookie settings** footer link beside the privacy link reopens
the choice; withdrawal disables collection, deletes this project's Analytics
cookies and reloads to unload the tag. Changes in another tab are applied too.
There is no floating settings button. The footer link falls back to the static
policy's choices section when JavaScript is unavailable; restoring keyboard focus
after a choice does not scroll the page to the footer.
Advertising consent remains denied; Google signals and ad personalization are
disabled. Cookies use a project prefix, host-only domain and `/EvoMneme/` path.

After deployment, allow analytics and check **Reports → Realtime** in the GA4
property. Browser network inspection can verify a `g/collect` request with
`tid=G-EXAMPLE000`; it cannot establish that the owner's reports have processed
the data. Ad blockers and declined consent can legitimately prevent collection.
Automatic/enhanced measurement beyond the initial page view is controlled by the
property's settings; review history-based page views if demo navigation should
not count as additional page views.

## Verification

```sh
python -m unittest discover -s tests -p test_website_export.py
node tests/test_website_static.js
node tests/test_website_analytics.js
python scripts/build_website.py
python -m unittest discover -s tests -p test_website_seo.py
```

Also inspect the rendered landing page and demo at desktop and mobile sizes,
exercise filters, selection, neighborhood exploration, and source links, and
check browser console/network errors. The static demo must work with only the
build directory served and no local viewer process running.
