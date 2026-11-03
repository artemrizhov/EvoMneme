# Local memory explorer

The optional explorer renders an explicitly selected host SQLite database with **Cytoscape.js**. It automatically installs/maintains the published [change and activity history](change-history.md) in a compatible managed v3 database; graph/table/SQL inspection uses read-only connections. No recording flag or trace directory is needed. `--no-history` skips automatic history setup/maintenance for this process while retaining access to saved history. It never activates EvoMneme or migrates the base graph schema. Use synthetic fixtures for development tests; self-hosting requires the same explicit authorization and storage isolation as any host. Keep host databases, traces, mappings and exports in the host's excluded local working area.

## Start

Using an existing Python, from the tool checkout:

```powershell
python scripts/evomneme_viewer.py --database "C:/path/to/host/.evomneme/knowledge.sqlite3"
```

Open the complete printed URL, including `#token=...`. Stop with Ctrl+C. The server binds only to `127.0.0.1` on an allocated port (`--port` can select one). Tokens protect data APIs; Host/origin checks reject cross-origin requests. Scripts/styles are served locally. No npm installation, CDN, internet or external service is required at runtime. The requested optional Cytoscape.js 3.30.4 asset, MIT license and SHA-256 manifest are in `scripts/viewer/vendor/`. This user-directed viewer dependency adds no dependencies to SQL execution and does not amend the charter.

## Experimental features and saved settings

On first use for a database, a dialog appears three seconds after the browser's
page-load event, independently of graph rendering, and offers **Try experimental features** or
**Keep disabled**. Escape also keeps them disabled. The offer explains GPU
rendering and background layout and points to their independent switches under
**Visual perspective** in the left sidebar. Either choice dismisses the offer
for later launches; no experimental feature is enabled without opting in.

The viewer saves both on and off states, the dialog choice and **Element size**
in a local JSON file beside the database: `knowledge.sqlite3` uses
`knowledge.viewer-settings.json`. A companion `.lock` coordinates writers.
Keep these files in the project's excluded local working area. Settings survive
server restarts, port changes and different browsers; they are separate from
graph/history data and do not depend on browser storage. They are restored
before the first graph load. Unsupported GPU/worker features revert to off and
that effective state is saved too.

The token-protected, same-origin preferences API validates settings and writes
them atomically. Read failures leave the experimental/size controls disabled;
save failures leave a visible message and **Retry settings** button. Invalid
files are not silently replaced. The graph remains available while a settings
problem is corrected.

## Visual investigation

The page header shows the project name prominently in the center; the browser
title places it before **Memory Explorer**. At server startup, the viewer reads
the current root node's `title` using `scope` and `root_id` from the project's
existing `.evomneme/connection.json`, after checking its project/database paths
and stored project identity. The receipt is sought beside a `.evomneme` database,
or in `.evomneme` beside a standalone database; it is never taken from the tool's
working directory. The title is escaped into the initial HTML and cached for
the server lifetime, with no browser lookup or source/Git scan. Missing, invalid
or mismatched bindings, unavailable/empty roots and custom SQL mappings retain
the path-based fallback: the project directory for a `.evomneme` database, or
the database filename without its extension otherwise. Restart the viewer and
reload to apply a renamed root. No new project-name setting or graph entity is needed.

### Controlled schema v3

New host stores use the [shared version-3 schema](schema.md): all entities in `nodes`, all relationships in `edges`, and supported type attributes in `symbol_details` / `file_details`. The viewer projects these tables directly across every kind/layer. Both node and edge graph IDs are `json_array(scope_id,id)` in separate namespaces. Symbol selection shows qualified name, signature and language; file inspection state is available on the file itself and on entities with a matching nonempty `source_path` in the same scope, without redundant graph edges. Locator matches use current file nodes; selecting an old file still shows its own inspection state. Provenance comes from `evidence.node_id` / `evidence.edge_id`. Fingerprints include attached symbol/file attributes so their edits refresh the graph too.

New kind/layer values need no viewer code changes. Unsupported schema versions or missing contract columns produce explicit compatibility errors; update the published schema, migration and viewer together before using a new model in a host. Only schema v3 is supported. Older and unversioned stores are rejected at startup, even with custom mappings or change recording enabled. Opening a database never migrates its base graph schema; use a compatible published migration first. Automatic history extension upgrades preserve existing entries and the base `user_version`.

For v3 activity SQL, return `scope_id,id` from a single `nodes` or `edges` table, or explicit `json_array(scope_id,id) AS trace_node_id` / `AS trace_edge_id` aliases when joining details.

### Exploration controls

The explorer fits the browser viewport without page-level scrolling. The filters sidebar, central workspace and selection inspector scroll independently when their contents exceed the available height. On narrower windows the inspector moves below the workspace; on small screens the panels stack and keep their own scroll areas.

The header status uses the remaining width and stays on one line. If a message is too long for the available space, it is ellipsized; hover to read the complete current message. Live and Refresh retain their space. Small screens give the action row the full header width.

- The default graph reads all stored entities from `nodes` and all relationships from `edges`, including links between code and knowledge. **Graph layers** independently switches **Code entities**, **Knowledge**, **Cross-layer relationships**, and **Unresolved / ambiguous references**. All available layers start enabled. Disabling a node layer also hides incident relationships and removes that layer from neighborhood traversal; disabling cross-layer relationships leaves both sets of nodes visible.
- **Load complete selected graph** is on initially. It loads the entire selected graph instead of the former first-page-only view. Turn it off for bounded node pages. For graphs above 10,000 visible nodes, a linear grid overview and straight relationships reduce layout/rendering work; use zoom, layers, filters or **Whole database · by layer/type** for structural inspection. Smaller selections restore curved relationships. All selected relationships remain in the graph, with edge rendering temporarily suppressed during viewport gestures. Large graphs are added in batches with progress feedback. Snapshot comparisons retain server fingerprints rather than another complete JSON copy, including evidence counts when comparing nodes.
- Loading continues after the server response: preparing elements, applying styles/highlights, arranging positions, counting components and drawing the canvas can take substantial time on large graphs. The progress display distinguishes these stages and shows elapsed time. Work with a known item count reports completed/total; opaque Cytoscape operations remain indeterminate rather than claiming an overall percentage. Chunked browser computations yield so progress can paint between batches. The connected/ready state is reported after the final preparation, not before the component count. An empty selection or a hidden graph view also completes without waiting indefinitely for a canvas paint.
- Whole-database structural counts show scale: nodes, relationships, isolated nodes, missing endpoints, table rows and logical SQLite page size. They are **not a quality score**, proof of completeness, or physical WAL/file size.
- **Graph detail** switches to a whole-database map grouped by layer, type, scope, source, validity or confidence. Group sizes and relationship counts are computed from the full filtered SQL projections, not a browser sample. Group detail includes member counts and, when available, counts of current/stale/uncertain/unsupported members. Select a group and **Explore group members**, or double-click it, to drill into individual nodes, including unspecified-source groups. Switch to individual nodes for exact session highlights.
- Color nodes and relationships by type, validity, confidence, evidence count, scope/version, source file, component or degree. Inspect disconnected regions, stale/uncertain claims, source attribution and evidence. Evidence count includes historical/stale evidence: inspect its attributes before judging support. Stored confidence/validity are assertions, not independently verified truth.
- Search node titles, IDs, summaries and paths. Expand scope, type, validity, confidence and source filters to choose any combination of checkboxes, then **Apply filters**. Selected values within a field match by OR; separate fields combine by AND. No selected values, or **All values**, leaves that field unrestricted. Collapsed headings show the selected count. Choices and expanded state survive live refresh, including selected values no longer present (shown with a zero count). Facets list at most 200 categories plus retained selections; SQL can inspect all. Scopes retain distinct composite IDs. Relationship facets use the same controls and matching rules.
- **Structural focus** selects nodes with an explicitly known zero evidence count, or nodes isolated in the whole database. An unspecified evidence count (e.g. a custom projection omitting provenance) is not treated as known absence. Expand **Relationship filters** to independently select relationship kind, validity and confidence. Neighborhood traversal follows the selected relationship filters. Custom projections can supply `evidence_count` to support evidence views.
- Select a node/relationship for attributes and evidence. Double-click a node or choose **Explore neighborhood** to retrieve an undirected neighborhood at depths 1–4. Node filters still apply. **Clear filters & focus** returns to the overview. Set a path start, select another node and find an undirected shortest path within the loaded slice.
- Choose force, hierarchy, concentric, circle or grid layouts. Export the current snapshot/activity as JSON or the graph as PNG. Exports can contain private host knowledge.
- PNG export adds background-colored margins on each side: 5% of the graph image's width horizontally and 5% of its height vertically, rounded up to whole pixels. Graph pixels keep their existing scale; only the exported canvas grows. For a 5,000-pixel-wide graph, each horizontal margin is 250 pixels and the resulting width is 5,500 pixels.
- **Follow graph growth** is on initially: added/removed nodes or relationships rerun the layout and fit the graph without enlarging small graphs past 100%. Full layouts allocate model-space area from node count and label dimensions, keeping small graphs compact and centered by the camera; enlarging the canvas at the same aspect ratio does not spread nodes farther apart. Canvas aspect ratio is a soft shape preference, bounded for extreme windows; topology, labels and local collision clearance can override it. **Fit** explicitly centers and fits the complete visible graph, capped at 100% camera zoom; following also fits automatically as the graph grows. **Rearrange** rebuilds the layout without reloading the page. Panning, wheel zoom, dragging or focusing an activity turns following off; reenable it to resume automatic arrangement. With following off, newly added nodes are placed without moving existing nodes or changing pan/zoom. Window resizing refits the existing arrangement while following is enabled; a graph built while its tab is hidden is laid out when shown.
- At the default **Element size · 100%**, camera zoom changes the distance between nodes while keeping node diameters within 1.5–18 CSS pixels and label fonts within 2–14 CSS pixels. Visible node diameters use 32.5% of the base size while layout retains its original spacing, leaving more room between nodes in dense graphs. Node and relationship labels use base font sizes of 5 and 4.5 pixels at 100% camera zoom. Labels shrink with the graph, smoothly fade below a 7-pixel font size and disappear at 3 pixels, including hovered/selected relationship labels. GPU label texture keys include effective text opacity so cached labels follow the same fading rule as standard rendering. This avoids giant elements on close inspection and unreadable text in the overview. Borders and relationship strokes also have bounded screen sizes. Full node labels remain available as hover tooltips and in the inspector. Relationship labels are off initially, appear on hovered/selected relationships, and can be enabled together using **Relationship labels**. Node size uses a bounded logarithmic scale to keep hubs from dominating the view.
- Label growth slows smoothly near its maximum. It stays linear up to 80% of the current font ceiling, then follows a quadratic curve with a decreasing growth rate. The ceiling is reached when the nominal uncapped size reaches 120% of that ceiling, where growth becomes zero without a sudden change in speed. At the default ceiling of 14 pixels, slowing starts at 11.2 pixels; a nominal 14-pixel font renders at 13.3 pixels. Text never exceeds its ceiling. Fading uses this actual smoothed font size; minimum sizes, 3–7 pixel fade thresholds and layout measurements are unchanged.
- **Element size** in the graph toolbar offers 30%, 40%, 50%, 65%, 80%, 100%, 125%, 150%, 200%, 250%, 300% and 400%. It multiplies base node/text sizes and their maximum screen sizes, while keeping the 1.5-pixel node minimum, 2-pixel font minimum and 3–7 pixel fading interval fixed. Opacity follows the actual smoothed font size; at 30–40% the font ceiling stays within the fade interval, so labels can appear but never become fully opaque. These are CSS pixels, independent of physical display resolution. The preference persists locally, remains available in expanded graph mode and Replay, and preserves positions, camera and history progress. Layout measurements retain their original dimensions.
- **Tables & schema** shows counts, DDL, foreign keys and paginated rows. **SQL inspection** runs a read-only SELECT against the supported v3 store. Use these for evidence, history, metadata, malformed relationships and data outside the graph slice.

Unresolved or ambiguous targets must be explicit stored nodes under the v3 contract; the viewer does not infer aliases or manufacture reference nodes from old table layouts. All types share `(scope_id,id)` identities. Tables/SQL expose the supported store's detail, coverage, metadata and history tables alongside the graph.

Code detail shows qualified names, signatures, source locators and file coverage. Partial signatures and review statuses are displayed as stored, without asserting semantic correctness. The compact whole-graph response omits long detail fields; content fingerprints still reveal updates to those fields, and selection retrieves full bounded details.

The viewer builds its built-in normalized projections in request-local **memory-only temporary tables** and indexes for efficient joins and filters. Inspection connections use SQLite `mode=ro`; caller SQL remains `query_only` and cannot enable writes, attach files or load extensions. A read-only `PRAGMA data_version` watcher avoids retransmitting an unchanged whole graph and detects commits from active WAL writers. Changes during a read appear on a subsequent poll. Close/restart the server to release its watcher. After installing Python changes, restart the viewer server and reload the browser. Persistent history is a separately versioned extension set up automatically in the same file; it does not change the base graph schema version.

## Custom projections within v3

Pass `--mapping "C:/path/to/host/.evomneme/viewer-mapping.json"`:

```json
{
  "nodes": "SELECT json_array(scope_id,id) AS graph_id, title AS label, kind, summary, layer FROM nodes",
  "edges": "SELECT json_array(scope_id,id) AS graph_id, json_array(scope_id,source_id) AS source, json_array(scope_id,target_id) AS target, kind, layer FROM edges"
}
```

Nodes require unique **text** `graph_id` and `label`. Edges require unique **text** `graph_id`, `source`, `target`; endpoints match node IDs. Include scope in composite IDs, e.g. `json_array(scope_id,id)`. Node/edge namespaces are separate. Optional `layer` enables named layer switches (missing/null layers default to `custom`); edge layer names may also represent edge-only layers. Optional `kind`, `scope_id`, `validity`, `confidence`, `source_path`, `summary` enable corresponding views/filters. All projected columns appear in detail. Use stable read-only SELECTs without trailing semicolons or duplicate aliases. Inspect custom provenance using SQL. An explicit mapping replaces the default projection but still requires a valid v3 database. Include every graph source the user wants to see.

## Live activity and identities

**Live** checks every two seconds when a refresh is not already running; it does not queue automatic refreshes behind a slow load. Empty activity polls retain existing highlights without restyling the graph. Dropdown elements/options are retained when unchanged; changed options wait until a focused dropdown loses focus. A refresh failure pauses Live and leaves its error visible until a retry; use **Refresh** after correcting the cause, then reenable Live as desired. Created/modified elements in the unchanged loaded slice turn green. Removed elements disappear and are counted in the timeline. Snapshot changes are **unattributed**: they are never assigned to the last chat that queried the database. Without persistent recording, changes outside the loaded slice or entirely between polls cannot be reconstructed.

Row changes, SQL calls and bound graph-CLI reads/mutations persist automatically in the same managed database. Each changed row has its own change ID, bounded typed before/after values and supported graph references. Access events retain known caller metadata and returned IDs without SQL text, parameters or result contents. `nodes` and `links` therefore feed the activity timeline and highlighting without a separate logging action by the agent. The latest saved events load on opening the page; older history retrieves earlier calls and changes. See [persistent change history](change-history.md) for the versioned tables, compatibility, suspension, storage and recording limits. Changes predating recording cannot be reconstructed.

Use the SQL CLI normally; history requires no extra flags:

```powershell
python scripts/evomneme.py --database "C:/path/to/host/.evomneme/knowledge.sqlite3" --sql "SELECT 1"
```

Python and CLI use the same default managed-store recording. Restart existing executor processes after updating the tool. The optional legacy `--trace-directory` path is only for a secondary JSONL export or reading existing log files; it is not needed to populate the activity panel. A process/session fallback keeps unidentified calls together without inventing a chat name. Per-call metadata supplies the actual identity when available.

Each `execute_sql` call may identify the main chat, work session and agent:

```json
{
  "sql": "SELECT scope_id,id,title FROM nodes WHERE scope_id=:scope LIMIT 12",
  "params": {"scope": "current-scope"},
  "activity_context": {
    "chat_id": "main-codex-chat-id",
    "chat_title": "Investigate memory graph",
    "session_id": "investigation-session-id",
    "session_title": "Inspect dependency coverage",
    "agent_id": "agent-or-subagent-id",
    "agent_name": "Main agent"
  }
}
```

All fields are optional nonempty strings of at most 200 characters. IDs provide stable grouping; `chat_title`, `session_title`, `agent_name` provide readable labels, with IDs still visible to distinguish identical names. Main agents and subagents supply the same `chat_id` and `chat_title` to group work by parent chat. Callers must include only known identities and titles, never invent a UI title or identity. Without per-call values the viewer identifies only a fallback process/session, not a known chat or agent. **SQLite and the executor cannot discover Codex chat ancestry automatically.** Restart existing executor processes after updating the tool; reload the viewer to load updated UI code. Historical events cannot acquire missing caller metadata retroactively.

Tracing preserves SQL result objects. Events record time, identities, table access, duration, result bounds and transaction outcome. They omit SQL, parameters and row contents except node/edge identifiers:

- A single-table `nodes` or `edges` result with unique `scope_id` and `id` columns yields returned node/relationship references in that table's namespace. Joins involving other tables, aggregate queries and results omitting IDs remain table-level activity.
- For custom projections, explicitly return `trace_node_id` or `trace_edge_id` with the **same text IDs** as the graph mapping. SELECT and DML RETURNING support these aliases; they are explicit agent assertions identifying graph elements.
- A reference means an ID was **returned to the caller**, not that every examined row was returned or that the agent understood/used it. Output bounds and aggregation hide some/all exact IDs. Writes without returned identifiers remain attempted table activity; rollback is labeled. Use `RETURNING scope_id,id` or explicit aliases for precise affected IDs. Per-chat committed node creation is never guessed from write attempts.
- Uninstrumented clients cannot report reads. Their committed changes appear through the installed SQLite journal without an inferred author. Instrumented connections attach their own call identity to row changes; no shared last-caller identity or timing guess is used.

For example, add `RETURNING json_array(scope_id,id) AS trace_node_id` to a node INSERT, or `RETURNING json_array(scope_id,id) AS trace_edge_id` to a relationship INSERT. The explicit aliases also work when foreign-key checks/triggers access additional tables and make implicit single-table attribution ambiguous.

Both code and knowledge use these same v3 IDs. A custom mapping's aliases must match its own graph IDs.

Select **Main chat**, **Session**, **Agent** to filter the timeline/highlight. Sessions are collapsed groups keyed by chat and session IDs, so identical session IDs in different chats stay separate. Expand a group for individual calls/changes, or highlight its combined loaded graph references. Counts and group highlights describe loaded history; older-history controls retrieve earlier database pages. Unassigned changes have their own group. Expanded groups and selection survive Live refreshes; long groups show children in bounded batches.

Newly received accesses automatically flash visible nodes and relationships, including existing elements: a 300 ms rise followed by a 5 second quadratic fade that accelerates toward the end. Repeated access restarts the rise from the current brightness. Yellow means read, blue means update, green means create, and red means delete, matching the graph caption. Journal entity references distinguish before-only deletions, after-only creations and updates present in both phases; evidence/detail edits, including their deletion, update the attached entity. Initial and older history pages do not trigger access flashes. Live polling determines when new accesses reach the browser. The transient halo is independent of history selection and accumulated highlighting. Relationships also pulse in width and, when no retained highlight is present, line/arrow color, so accesses remain visible with GPU rendering, which omits relationship halos. Retained/history/path/selection colors stay in place during the width pulse.

Deleted elements previously visible in this graph slice leave red dashed geometry on a separate noninteractive canvas. It follows pan/zoom and fades with the same timing, without adding deleted nodes/relationships back to the live graph, layout, component counts or pathfinding. History/recording can hold cached deleted geometry, with 300 ms transitions when selecting or clearing it. The cache retains at most 10,000 removed elements and resets when graph filters change; previously unseen or evicted geometry cannot be drawn, but stored before/after values remain available. Accumulated colors retain the latest known mutation for an ID; later reads do not erase that mutation. Without database history, same-filter snapshot differences distinguish newly visible, modified and removed elements, which are observations about the loaded slice rather than proof of a database operation. With database history enabled, exact journal events determine the operation colors.

**Record highlight** accumulates new references and unattributed snapshot changes. Accumulated colors turn on with a 300 ms transition and remain on; selecting or clearing history highlighting transitions colors in either direction over 300 ms with ease-in-out timing. **Pause recording** freezes accumulation; **Reset highlight** clears it and current flashes without deleting database history. The timeline and new access flashes continue during a pause. **Use log history** explicitly seeds highlighting from history loaded by this browser. **Only highlighted graph** retains accumulated/selected elements and endpoints of highlighted relationships; transient flashes do not change that filter. Off-page or deleted IDs remain counted but cannot be drawn until available in the selected slice.

Click a timeline activity (or focus it and press Enter/Space) to highlight only that event's known IDs, without changing the accumulated recording. **Return to accumulated highlight** restores the recording. Select a row change to inspect its stored before/after values, including deleted elements. Selection persists across live refreshes; changing identity filters, Reset, or Use log history leaves the single-event/session selection. The status explains when exact IDs are missing, off-page, grouped, or removed. Unassigned snapshot/row observations never populate caller filters. Known caller metadata on correctly attributed row changes can populate those filters. Existing logs without identity metadata remain honestly unidentified.

Recording controls affect browser-local highlighting, not automatic database recording. `--no-history` stops this process from setting up/maintaining database history and recording calls there; it does not remove persistent row triggers already installed or disable an explicitly requested legacy JSONL export. See the history reference for deliberate global suspension. Reloading resets browser recording/selection and rereads saved history. Database history has no automatic disk pruning; legacy JSONL exports retain their per-process 32 MiB / 1,000-file reader limits. Browser history and highlight retain at most 10,000 events with a visible limit notice. This is observation, not a lossless audit log.

## Bounds and interpretation

Complete selected graphs can load up to 100,000 projected nodes and 200,000 relationships. Exceeding either limit returns an explicit error rather than silently showing a prefix: use layers, filters or grouping. When full loading is off, nodes/groups paginate by graph ID: default 500, maximum 2,000; a slice draws up to 2,000 relationships whose endpoints are both loaded. Aggregate-map relationships retain the 2,000-group-link bound with visible truncation. Boundary counts, truncation, pagination and timing remain visible. Unresolved references are explicitly stored nodes; missing endpoints in custom mappings are still counted and inspected through tables/SQL. Components, degree and shortest paths describe the loaded graph, which can be filtered or paginated. Global counts/facets describe all projected layers, not the current switches. Node filters do not implicitly filter relationship kind/validity; use the independent relationship filters.

SQL/table inspection returns at most 200 rows; evidence detail at most 200. Graph snapshot construction has a 30-second SQLite VM deadline; other reads retain five seconds, with a one-second lock wait. Time limits yield an explanatory error instead of SQLite's bare `interrupted`. The browser aborts an unresponsive request after 90 seconds, including response-body transfer. Requests are capped at 64 KiB, ordinary responses at 8 MiB, complete-graph JSON at 128 MiB, and schema inspection at 200 tables. Large JSON is gzip-compressed when the client accepts gzip. Built-in complete-graph rows omit detail columns before serialization/budget checks, while content fingerprints still cover those details; full selection joins materialize node IDs alone. Individual text/BLOB values above 16 KiB become explicit previews. Narrow expensive projections/filters or inspect an isolated copy; full counts can cost substantial work on large databases. A changed filter resets snapshot comparisons. No measured development-efficiency gain is claimed.

Run `python -m unittest discover -s tests -v`. For manual browser checks, `python tests/test_viewer.py --serve-demo` serves synthetic fixtures under excluded `.evomneme-tests/viewer-demo/`.

When Node.js is already available for development, the Python suite also runs the geometry regressions against the bundled Cytoscape with `node tests/test_viewer_layout.js`. Otherwise that optional check is skipped; Node.js is not a viewer runtime dependency.

The **Expand graph** corner icon (named in its hover tooltip) fills the page with the graph, its toolbar and saved-history
controls. A compact logo and the project heading share one row with the toolbar
buttons, with the project centered in the space between the logo and controls.
Controls wrap on narrow windows without a scrollbar. It hides the remaining
page header, side panels, activity log and captions. Messages share a fixed-height
row with the saved-history status: right-aligned after a gap, truncated with an
ellipsis and available in full on hover. The calculation timer appears only after
one second, and disappears on completion or cancellation without shifting the graph.
Selecting a node, relationship or aggregate slides the selection inspector in
from the right without resizing the graph. It shows the same stored attributes,
evidence and actions as the regular inspector; Replay retains historical-only
details. Close it with its close button, Escape, a click outside, or by moving
keyboard focus outside the panel or switching away from the browser window.
Moving focus between controls inside the panel keeps it open. Background refreshes
do not reopen a dismissed panel. The slide respects reduced-motion preferences.
Use the inward-corner **Restore page** icon or Escape with the inspector closed to return. This mode preserves the loaded graph,
filters and replay state, and also works in the public demo. Existing resize
behavior applies: following fits the graph to the available space, while a
manual view with following disabled retains its pan and zoom.

### Large graph layout and zoom cost

For **Force directed** above 800 loaded nodes, enable **Experimental background
layout** to calculate positions without blocking the page. With it disabled,
the main thread uses the quick grid overview; **Rearrange** then rebuilds that
same grid. Disabling background layout terminates an outstanding calculation.
The status reports elapsed time, not a percentage or a predicted completion time.

Large flat connected regions use spatially approximated repulsion and exact
relationship springs, retaining all nodes, relationships and 350 iterations.
Small regions and compound graphs keep the bundled CoSE solver. Locked positions,
label-aware collision separation and component placement remain in effect.
This changes the exact positions of large force layouts; it does not change the
stored graph. Graphs above 10,000 visible nodes still use the grid overview.
Synthetic completion measurements are examples, not a deadline for every topology.

Above 2,000 loaded elements (nodes plus relationships), screen-size styles refresh
once zoom has been idle for 150 ms. During a wheel gesture or animated camera move,
the renderer scales the existing styles; the normal size limits and label fading
are restored after the camera settles. Smaller graphs retain per-frame updates.
This avoids repeatedly rebuilding all geometry and label caches during motion;
the final style refresh and rendering can still pause on a very large graph.
