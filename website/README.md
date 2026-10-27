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

## Verification

```sh
python -m unittest discover -s tests -p test_website_export.py
node tests/test_website_static.js
python scripts/build_website.py
```

Also inspect the rendered landing page and demo at desktop and mobile sizes,
exercise filters, selection, neighborhood exploration, and source links, and
check browser console/network errors. The static demo must work with only the
build directory served and no local viewer process running.
