# Local memory explorer

The optional explorer renders an explicitly selected host SQLite database with **Cytoscape.js**. By default it opens the file read-only. Explicit `--record-changes` installs and maintains the published [row-change journal](change-history.md); graph/table/SQL inspection still uses read-only connections. It never activates EvoMneme or migrates the base graph schema. Develop this repository using synthetic fixtures only. Keep host databases, traces, mappings and exports in the host's excluded local working area.

## Start

Using an existing Python, from the tool checkout:

```powershell
python scripts/evomneme_viewer.py --database "C:/path/to/host/.evomneme/knowledge.sqlite3" --trace-directory "C:/path/to/host/.evomneme/activity"
```

Open the complete printed URL, including `#token=...`. Stop with Ctrl+C. The server binds only to `127.0.0.1` on an allocated port (`--port` can select one). Tokens protect data APIs; Host/origin checks reject cross-origin requests. Scripts/styles are served locally. No npm installation, CDN, internet or external service is required at runtime. The requested optional Cytoscape.js 3.30.4 asset, MIT license and SHA-256 manifest are in `scripts/viewer/vendor/`. This user-directed viewer dependency adds no dependencies to SQL execution and does not amend the charter.

## Visual investigation

### Controlled schema v3

New host stores use the [shared version-3 schema](schema.md): all entities in `nodes`, all relationships in `edges`, and supported type attributes in `symbol_details` / `file_details`. The viewer projects these tables directly across every kind/layer. Both node and edge graph IDs are `json_array(scope_id,id)` in separate namespaces. Symbol selection shows qualified name, signature and language; file coverage is available on file nodes and through current `declared_in` edges. Provenance comes from `evidence.node_id` / `evidence.edge_id`. Fingerprints include attached symbol/file attributes so their edits refresh the graph too.

New kind/layer values need no viewer code changes. Unsupported schema versions or missing contract columns produce explicit compatibility errors; update the published schema, migration and viewer together before using a new model in a host. Legacy schemas below remain supported for inspection, and an explicit custom mapping remains an inspection aid, not permission for a private schema fork. Opening a database never migrates it.

For v3 activity SQL, return `scope_id,id` from a single `nodes` or `edges` table, or explicit `json_array(scope_id,id) AS trace_node_id` / `AS trace_edge_id` aliases when joining details. Legacy tracing examples below retain their original namespaces.

### Exploration controls and legacy compatibility

- The default graph combines stored code entities (`code_symbols`), knowledge (`records`), their relationships (`code_edges`, `relations`), and links between these domains. **Graph layers** independently switches **Code entities**, **Knowledge**, **Cross-layer relationships**, and **Unresolved / ambiguous references**. All available layers start enabled. Disabling a node layer also hides incident relationships and removes that layer from neighborhood traversal; disabling cross-layer relationships leaves both sets of nodes visible.
- **Load complete selected graph** is on initially. It loads the entire selected graph instead of the former first-page-only view. Turn it off for bounded node pages. For graphs above 1,000 visible nodes, a linear grid overview keeps the browser responsive; use zoom, layers, filters or **Whole database · by layer/type** for structural inspection. All selected relationships remain in the graph, with edge rendering temporarily suppressed during viewport gestures. Large graphs are added in batches with progress feedback.
- Whole-database structural counts show scale: nodes, relationships, isolated nodes, missing endpoints, table rows and logical SQLite page size. They are **not a quality score**, proof of completeness, or physical WAL/file size.
- **Graph detail** switches to a whole-database map grouped by layer, type, scope, source, validity or confidence. Group sizes and relationship counts are computed from the full filtered SQL projections, not a browser sample. Group detail includes member counts and, when available, counts of current/stale/uncertain/unsupported members. Select a group and **Explore group members**, or double-click it, to drill into individual nodes, including unspecified-source groups. Switch to individual nodes for exact session highlights.
- Color nodes and relationships by type, validity, confidence, evidence count, scope/version, source file, component or degree. Inspect disconnected regions, stale/uncertain claims, source attribution and evidence. Evidence count includes historical/stale evidence: inspect its attributes before judging support. Stored confidence/validity are assertions, not independently verified truth.
- Search node titles, IDs, summaries and paths. Combine scope, type, validity, confidence and source filters. Facets list at most 200 categories; SQL can inspect all. Scopes retain distinct composite IDs.
- **Structural focus** selects nodes with an explicitly known zero evidence count, or nodes isolated in the whole database. An unspecified evidence count (e.g. code provenance not modeled in the starter evidence table) is not treated as known absence. Expand **Relationship filters** to independently select relationship kind, validity and confidence. Neighborhood traversal follows the selected relationship filters. Custom projections can supply `evidence_count` to support evidence views.
- Select a node/relationship for attributes and evidence. Double-click a node or choose **Explore neighborhood** to retrieve an undirected neighborhood at depths 1–4. Node filters still apply. **Clear filters & focus** returns to the overview. Set a path start, select another node and find an undirected shortest path within the loaded slice.
- Choose force, hierarchy, concentric, circle or grid layouts. Export the current snapshot/activity as JSON or the graph as PNG. Exports can contain private host knowledge.
- PNG export adds background-colored margins on each side: 5% of the graph image's width horizontally and 5% of its height vertically, rounded up to whole pixels. Graph pixels keep their existing scale; only the exported canvas grows. For a 5,000-pixel-wide graph, each horizontal margin is 250 pixels and the resulting width is 5,500 pixels.
- **Follow graph growth** is on initially: added/removed nodes or relationships rerun the layout and fit the graph without enlarging small graphs past 100%. Layout spacing accounts for node labels, and a rigid rotation chooses the better fit for the current viewport. **Rearrange** rebuilds the layout without reloading the page. Panning, wheel zoom, dragging or focusing an activity turns following off; reenable it to resume automatic arrangement. With following off, newly added nodes are placed without moving existing nodes or changing pan/zoom. Window resizing adapts the overview while following is enabled; a graph built while its tab is hidden is laid out when shown.
- Node labels disappear at overview scales where they would be unreadably small and reappear when zooming in. Full node labels remain available as hover tooltips and in the inspector. Relationship labels are off initially, appear on hovered/selected relationships, and can be enabled together using **Relationship labels**. Node size uses a bounded logarithmic scale to keep hubs from dominating the view.
- **Tables & schema** shows counts, DDL, foreign keys and paginated rows. **SQL inspection** runs a read-only SELECT against any schema. Use these for evidence, history, metadata, malformed relationships and data outside the graph slice.

The starter `records`/`relations` and code `code_symbols`/`code_edges` schemas are recognized automatically, including databases with only code tables. Knowledge node IDs remain `json_array(scope_id,id)`; code node IDs are `json_array('code',scope_id,id)`, and code edge IDs are `json_array('code-edge',scope_id,id)`. Scope and domain identities stay distinct. Code edges can reference exact symbol/record IDs or explicit `record:` / `knowledge-record:` aliases. A target is resolved only if its identity is unique. Missing or ambiguous endpoints become clearly marked reference nodes, not invented declarations, so their stored edges remain inspectable. Their counts describe projected placeholders rather than stored symbols. Other schemas or endpoint encodings may require a custom mapping; incompatible known tables produce a visible warning. Tables/SQL still expose every table, including coverage and inventory tables that are not graph-node tables.

Code detail shows the original owner, qualified name, signature and source locator, plus the stored `code_files` coverage/review row when compatible. Partial signatures and review statuses are displayed as stored, without asserting semantic correctness. Starter evidence is attached only to knowledge records/relationships, never to a code symbol merely sharing a local ID. The compact whole-graph response omits long detail fields; content fingerprints still reveal updates to those fields, and selection retrieves full bounded details.

The viewer builds its built-in normalized projections in request-local **memory-only temporary tables** and indexes for efficient joins and filters. Inspection connections use SQLite `mode=ro`; caller SQL remains `query_only` and cannot enable writes, attach files or load extensions. A read-only `PRAGMA data_version` watcher avoids retransmitting an unchanged whole graph and detects commits from active WAL writers. Changes during a read appear on a subsequent poll. Close/restart the server to release its watcher. After installing Python changes, restart the viewer server and reload the browser. Persistent history is a separate explicit schema extension, enabled with `--record-changes` as described below.

## Other schemas

Pass `--mapping "C:/path/to/host/.evomneme/viewer-mapping.json"`:

```json
{
  "nodes": "SELECT CAST(key AS TEXT) AS graph_id, name AS label, category AS kind, description AS summary, 'application' AS layer FROM entities",
  "edges": "SELECT CAST(key AS TEXT) AS graph_id, CAST(from_key AS TEXT) AS source, CAST(to_key AS TEXT) AS target, relation_type AS kind, 'application' AS layer FROM links"
}
```

Nodes require unique **text** `graph_id` and `label`. Edges require unique **text** `graph_id`, `source`, `target`; endpoints match node IDs. Include scope in composite IDs, e.g. `json_array(scope_id,id)`. Node/edge namespaces are separate. Optional `layer` enables named layer switches (missing/null layers default to `custom`); edge layer names may also represent edge-only layers. Optional `kind`, `scope_id`, `validity`, `confidence`, `source_path`, `summary` enable corresponding views/filters. All projected columns appear in detail. Use stable read-only SELECTs without trailing semicolons or duplicate aliases. Inspect custom provenance using SQL. An explicit mapping replaces built-in discovery, so it must include every graph source the user wants to see.

## Live activity and identities

**Live** refreshes every two seconds. Dropdown elements/options are retained when unchanged; changed options wait until a focused dropdown loses focus. Created/modified elements in the unchanged loaded slice turn green. Removed elements disappear and are counted in the timeline. Snapshot changes are **unattributed**: they are never assigned to the last chat that queried the database. Without persistent recording, changes outside the loaded slice or entirely between polls cannot be reconstructed.

To retain row changes across page/server restarts, explicitly add `--record-changes` to the viewer command. This creates `evomneme_change_log`, `evomneme_change_elements`, `evomneme_change_meta` and ordinary SQLite triggers in the selected database. Each changed row has its own change ID, bounded typed before/after values and supported graph references. The latest changes load on opening the page; **Older database changes** retrieves earlier pages. Select an activity to highlight its current graph elements and inspect the saved row transition, including deleted elements. Reset highlight only clears browser highlighting. See [persistent change history](change-history.md) for setup, suspension, schema compatibility, storage and recording limits. Changes predating installation are not recoverable from this journal.

Opt in to read/write tracing on each SQL/MCP process:

```powershell
python scripts/evomneme_mcp.py --database "C:/path/to/host/.evomneme/knowledge.sqlite3" --trace-directory "C:/path/to/host/.evomneme/activity" --session-id "fallback-session"
```

Use the same directory for the viewer. CLI supports the same flags. Python callers use `configure_trace(executor, absolute_directory, fallback_session)` from `evomneme_trace`. Each process writes a separate JSONL file to avoid concurrent append interleaving; events identify the bound database and other-database events are ignored.

Each `execute_sql` call may identify the main chat, work session and agent:

```json
{
  "sql": "SELECT scope_id,id,title FROM records WHERE scope_id=:scope LIMIT 12",
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

All fields are optional nonempty strings of at most 200 characters. IDs provide stable grouping; `chat_title`, `session_title`, `agent_name` provide readable labels, with IDs still visible to distinguish identical names. Main agents and subagents supply the same `chat_id` and `chat_title` to group work by parent chat. The MCP tool description asks callers to include known identities and titles; callers must omit unknown values, never invent a UI title or identity. MCP initialization supplies a client name/version, which is recorded when present. It does not supply chat ancestry or titles. Without per-call values, chat/session use the startup fallback ID and agent uses the process log ID. The viewer labels this as missing chat metadata / a process identity instead of implying a known chat. **SQLite/MCP cannot discover Codex chat ancestry automatically.** Developing this viewer does not change any real host's MCP configuration. Restart existing MCP processes to load the updated tool schema and reconnect their clients; reload the viewer to load updated UI code. Historical events cannot acquire missing caller metadata retroactively.

Tracing preserves SQL result objects. Events record time, identities, table access, duration, result bounds and transaction outcome. They omit SQL, parameters and row contents except node/edge identifiers:

- A single-table `records`, `relations`, `code_symbols` or `code_edges` result with unique `scope_id` and `id` columns yields returned node/relationship references in that table's namespace. Joins involving other tables, aggregate queries and results omitting IDs remain table-level activity.
- For custom schemas, explicitly return `trace_node_id` or `trace_edge_id` with the **same text IDs** as the graph mapping. SELECT and DML RETURNING support these aliases; they are explicit agent assertions identifying graph elements.
- A reference means an ID was **returned to the caller**, not that every examined row was returned or that the agent understood/used it. Output bounds and aggregation hide some/all exact IDs. Writes without returned identifiers remain attempted table activity; rollback is labeled. Use `RETURNING scope_id,id` or explicit aliases for precise affected IDs. Per-chat committed node creation is never guessed from write attempts.
- Uninstrumented clients cannot report reads. Their committed changes appear through snapshots or the separately enabled SQLite journal. JSONL call tracing itself installs no triggers or tables.

For example, add `RETURNING json_array(scope_id,id) AS trace_node_id` to a starter record INSERT, or `RETURNING json_array(scope_id,id) AS trace_edge_id` to a relationship INSERT. The explicit aliases also work when foreign-key checks/triggers access additional tables and make implicit single-table attribution ambiguous.

For explicit built-in code aliases use `json_array('code',scope_id,id) AS trace_node_id` or `json_array('code-edge',scope_id,id) AS trace_edge_id`. A custom mapping's aliases must match its own graph IDs.

Select **Main chat**, **Session**, **Agent** to filter the timeline/highlight. **Record highlight** accumulates new references and unattributed snapshot changes. **Pause recording** freezes accumulation; **Reset highlight** clears it without deleting logs. The timeline continues during a pause. **Use log history** explicitly seeds highlighting from logs loaded by this browser. **Only highlighted graph** retains highlighted elements and endpoints of highlighted relationships. Yellow means returned IDs; green means snapshot changes. Off-page or deleted IDs remain counted but cannot be drawn until available in the selected slice.

Click a timeline activity (or focus it and press Enter/Space) to highlight only that event's known IDs, without changing the accumulated recording. **Return to accumulated highlight** restores the recording. Selection persists across live refreshes; changing identity filters, Reset, or Use log history leaves the single-event selection. The status explains when exact IDs are missing, off-page, grouped, or removed. Snapshot observations are shown as **Database observation · author not reported** and never populate chat/session/agent filters. They describe committed graph differences, not an identified agent action. If only observations are available, the viewer explicitly says no traced calls with caller metadata were loaded. Seeing this does not establish which client made those changes or whether host tracing was configured correctly.

Recording controls affect browser-local highlighting, not executor logging. To stop collecting logs on disk, restart the executor without tracing flags. Reloading resets browser recording/selection and rereads logs. Each process stops logging at 32 MiB and reports failures/limits on stderr without undoing SQL. Archive logs deliberately; the viewer refuses more than 1,000 files. Browser history and highlight retain at most 10,000 events with a visible limit notice. This is observation, not a lossless audit log.

## Bounds and interpretation

Complete selected graphs can load up to 100,000 projected nodes and 200,000 relationships. Exceeding either limit returns an explicit error rather than silently showing a prefix: use layers, filters or grouping. When full loading is off, nodes/groups paginate by graph ID: default 500, maximum 2,000; a slice draws up to 2,000 relationships whose endpoints are both loaded. Aggregate-map relationships retain the 2,000-group-link bound with visible truncation. Boundary counts, truncation, pagination and timing remain visible. Built-in unresolved references are explicit nodes; missing endpoints in custom mappings are still counted and inspected through tables/SQL. Components, degree and shortest paths describe the loaded graph, which can be filtered or paginated. Global counts/facets describe all projected layers, not the current switches. Node filters do not implicitly filter relationship kind/validity; use the independent relationship filters.

SQL/table inspection returns at most 200 rows; evidence detail at most 200. Queries have a five-second SQLite VM deadline and one-second lock wait. Requests are capped at 64 KiB, ordinary responses at 8 MiB, complete-graph JSON at 64 MiB, and schema inspection at 200 tables. Large JSON is gzip-compressed when the client accepts gzip. Individual text/BLOB values above 16 KiB become explicit previews. Narrow expensive projections/filters or inspect an isolated copy; full counts can cost substantial work on large databases. A changed filter resets snapshot comparisons. No production host integration or measured development-efficiency gain is claimed.

Run `python -m unittest discover -s tests -v`. For manual browser checks, `python tests/test_viewer.py --serve-demo` serves synthetic fixtures under excluded `.evomneme-tests/viewer-demo/`.

When Node.js is already available for development, the Python suite also runs the geometry regressions against the bundled Cytoscape with `node tests/test_viewer_layout.js`. Otherwise that optional check is skipped; Node.js is not a viewer runtime dependency.
