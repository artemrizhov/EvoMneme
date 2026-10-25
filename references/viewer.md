# Local memory explorer

The optional explorer renders an explicitly selected host SQLite database with **Cytoscape.js**. It opens the file read-only and never applies a schema, migrates data, or activates EvoMneme. Develop this repository using synthetic fixtures only. Keep host databases, traces, mappings and exports in the host's excluded local working area.

## Start

Using an existing Python, from the tool checkout:

```powershell
python scripts/evomneme_viewer.py --database "C:/path/to/host/.evomneme/knowledge.sqlite3" --trace-directory "C:/path/to/host/.evomneme/activity"
```

Open the complete printed URL, including `#token=...`. Stop with Ctrl+C. The server binds only to `127.0.0.1` on an allocated port (`--port` can select one). Tokens protect data APIs; Host/origin checks reject cross-origin requests. Scripts/styles are served locally. No npm installation, CDN, internet or external service is required at runtime. The requested optional Cytoscape.js 3.30.4 asset, MIT license and SHA-256 manifest are in `scripts/viewer/vendor/`. This user-directed viewer dependency adds no dependencies to SQL execution and does not amend the charter.

## Visual investigation

- Whole-database structural counts show scale: nodes, relationships, isolated nodes, missing endpoints, table rows and logical SQLite page size. They are **not a quality score**, proof of completeness, or physical WAL/file size.
- **Graph detail** switches to a whole-database map grouped by type, scope, source, validity or confidence. Group sizes and relationship counts are computed from the full filtered SQL projections, not a browser sample. Group detail includes member counts and, when available, counts of current/stale/uncertain/unsupported members. Select a group and **Explore group members**, or double-click it, to drill into individual nodes, including unspecified-source groups. Switch to individual nodes for exact session highlights.
- Color nodes and relationships by type, validity, confidence, evidence count, scope/version, source file, component or degree. Inspect disconnected regions, stale/uncertain claims, source attribution and evidence. Evidence count includes historical/stale evidence: inspect its attributes before judging support. Stored confidence/validity are assertions, not independently verified truth.
- Search node titles, IDs, summaries and paths. Combine scope, type, validity, confidence and source filters. Facets list at most 200 categories; SQL can inspect all. Scopes retain distinct composite IDs.
- **Structural focus** selects nodes without evidence or nodes isolated in the whole database. Expand **Relationship filters** to independently select relationship kind, validity and confidence. Neighborhood traversal follows the selected relationship filters. Custom projections can supply `evidence_count` to support evidence views.
- Select a node/relationship for attributes and evidence. Double-click a node or choose **Explore neighborhood** to retrieve an undirected neighborhood at depths 1–4. Node filters still apply. **Clear filters & focus** returns to the overview. Set a path start, select another node and find an undirected shortest path within the loaded slice.
- Choose force, hierarchy, concentric, circle or grid layouts. Export the current snapshot/activity as JSON or the graph as PNG. Exports can contain private host knowledge.
- **Tables & schema** shows counts, DDL, foreign keys and paginated rows. **SQL inspection** runs a read-only SELECT against any schema. Use these for evidence, history, metadata, malformed relationships and data outside the graph slice.

The starter `records`/`relations` schema is recognized automatically, with starter `evidence` detail. Other or partially compatible schemas may require a mapping. Without a graph mapping, tables and SQL remain available.

## Other schemas

Pass `--mapping "C:/path/to/host/.evomneme/viewer-mapping.json"`:

```json
{
  "nodes": "SELECT CAST(key AS TEXT) AS graph_id, name AS label, category AS kind, description AS summary FROM entities",
  "edges": "SELECT CAST(key AS TEXT) AS graph_id, CAST(from_key AS TEXT) AS source, CAST(to_key AS TEXT) AS target, relation_type AS kind FROM links"
}
```

Nodes require unique **text** `graph_id` and `label`. Edges require unique **text** `graph_id`, `source`, `target`; endpoints match node IDs. Include scope in composite IDs, e.g. `json_array(scope_id,id)`. Node/edge namespaces are separate. Optional `kind`, `scope_id`, `validity`, `confidence`, `source_path`, `summary` enable corresponding views/filters. All projected columns appear in detail. Use stable read-only SELECTs without trailing semicolons or duplicate aliases. Inspect custom provenance using SQL.

## Live activity and identities

**Live** refreshes every two seconds. Created/modified elements in the unchanged loaded slice turn green. Removed elements disappear and are counted in the timeline. Snapshot changes are **unattributed**: they are never assigned to the last chat that queried the database. Changes outside the loaded slice or entirely between polls cannot be reconstructed.

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
    "session_id": "investigation-session-id",
    "agent_id": "agent-or-subagent-id"
  }
}
```

All fields are optional nonempty strings of at most 200 characters. Main agents and subagents supply the same `chat_id` to group work by parent chat. Without per-call values, chat/session use the startup fallback ID, and agent uses the process's unique log ID. **SQLite/MCP cannot discover Codex chat ancestry automatically.** Developing this viewer does not change any real host's MCP configuration.

Tracing preserves SQL result objects. Events record time, identities, table access, duration, result bounds and transaction outcome. They omit SQL, parameters and row contents except node/edge identifiers:

- A single-table starter result with unique `scope_id` and `id` columns yields returned node/relationship references. Joins involving other tables, aggregate queries and results omitting IDs remain table-level activity.
- For custom schemas, explicitly return `trace_node_id` or `trace_edge_id` with the **same text IDs** as the graph mapping. SELECT and DML RETURNING support these aliases; they are explicit agent assertions identifying graph elements.
- A reference means an ID was **returned to the caller**, not that every examined row was returned or that the agent understood/used it. Output bounds and aggregation hide some/all exact IDs. Writes without returned identifiers remain attempted table activity; rollback is labeled. Use `RETURNING scope_id,id` or explicit aliases for precise affected IDs. Per-chat committed node creation is never guessed from write attempts.
- Uninstrumented clients cannot report reads. Their committed changes may appear through snapshots. No triggers or tracing tables are installed in the host database.

For example, add `RETURNING json_array(scope_id,id) AS trace_node_id` to a starter record INSERT, or `RETURNING json_array(scope_id,id) AS trace_edge_id` to a relationship INSERT. The explicit aliases also work when foreign-key checks/triggers access additional tables and make implicit single-table attribution ambiguous.

Select **Main chat**, **Session**, **Agent** to filter the timeline/highlight. **Record highlight** accumulates new references and unattributed snapshot changes. **Pause recording** freezes accumulation; **Reset highlight** clears it without deleting logs. The timeline continues during a pause. **Use log history** explicitly seeds highlighting from logs loaded by this browser. **Only highlighted graph** retains highlighted elements and endpoints of highlighted relationships. Yellow means returned IDs; green means snapshot changes. Off-page or deleted IDs remain counted but cannot be drawn until available in the selected slice.

Recording controls affect browser-local highlighting, not executor logging. To stop collecting logs on disk, restart the executor without tracing flags. Reloading resets browser recording/selection and rereads logs. Each process stops logging at 32 MiB and reports failures/limits on stderr without undoing SQL. Archive logs deliberately; the viewer refuses more than 1,000 files. Browser history and highlight retain at most 10,000 events with a visible limit notice. This is observation, not a lossless audit log.

## Bounds and interpretation

Nodes/groups paginate by graph ID: default 500, maximum 2,000. A slice draws up to 2,000 relationships whose endpoints are both loaded. Boundary counts, relationship truncation, pagination and timing are visible. Relationships with missing endpoints are globally counted and can be inspected in tables/SQL. Components, degree and shortest paths describe the loaded slice. Whole-database counts/facets do not describe filtered results. Node filters do not implicitly filter relationship kind/validity; use the independent relationship filters. Group maps aggregate the full filtered projections; group count and pagination remain visible if there are too many categories to draw at once.

SQL/table inspection returns at most 200 rows; evidence detail at most 200. Queries have a five-second SQLite VM deadline and one-second lock wait. Requests are capped at 64 KiB, responses at 8 MiB, schema inspection at 200 tables. Individual text/BLOB values above 16 KiB become explicit previews. Narrow expensive projections/filters or inspect an isolated copy; full counts can cost substantial work on large databases. A changed filter resets snapshot comparisons. No production host integration or measured development-efficiency gain is claimed.

Run `python -m unittest discover -s tests -v`. For manual browser checks, `python tests/test_viewer.py --serve-demo` serves synthetic fixtures under excluded `.evomneme-tests/viewer-demo/`.
