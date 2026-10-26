# Persistent database change and activity history · format 2

Managed EvoMneme v3 databases retain row changes and SQL-call activities automatically in the same SQLite file. The viewer and Python/CLI executor install/maintain a published versioned extension when a compatible store is recognized. No recording flag, trace directory or session setup is required. Generic or not-yet-initialized SQLite databases keep the native SQL contract without automatic history installation. The base graph schema remains v3.

```powershell
python scripts/evomneme_viewer.py --database "C:/path/to/host/.evomneme/knowledge.sqlite3"
```

Restart the viewer and existing executor processes and reload the browser after updating the tool. Setup opens a short read/write connection; graph, SQL and history inspection remains read-only. The extension upgrades format 1 transactionally while preserving existing history and the base `user_version`. Old records do not acquire an author retroactively. No external package is needed.

`--no-history` (or `history=False` for an executor/viewer) disables that process's automatic history setup/maintenance and database SQL-call recording. The viewer retains access to saved history. This does not erase existing records or remove persistent row triggers installed earlier. The old `--record-changes` flag remains compatible but is unnecessary. Explicit legacy JSONL tracing/export is independent and remains available for existing workflows, including when database history is disabled; its compatibility flags are the `--trace-directory` / `--session-id` pair.

## Storage and transactions

- `evomneme_change_log`: one row per INSERT, actual UPDATE or DELETE of a tracked ordinary-table row, with monotonic change ID, UTC time, source table, operation, primary key (rowid fallback), typed before/after JSON, and optional `activity_id` / `actor_json` attribution.
- `evomneme_change_elements`: links from change IDs to graph node/edge IDs, with `before`/`after` phase and entity/detail/evidence role. References survive deletion because they deliberately do not foreign-key the current graph.
- `evomneme_change_meta`: extension owner/version, installation time, tracked-table schema signatures and owned trigger names. These reserved tables do not recursively journal themselves.
- `evomneme_change_calls`: durable SQL-call events with a numeric history cursor, stable `activity_id` and bounded event JSON. Events preserve known caller/client metadata, returned graph references, timing, read/write table access and transaction outcome; they omit SQL text, parameters and result contents beyond graph identifiers.

SQLite AFTER triggers run inside the writer's transaction. Rollback/savepoint rollback removes row-change history; multirow statements produce separate entries. A no-op UPDATE produces none. Calls, including failed/rolled-back attempts, remain separately observable with their actual outcome. Partial native autocommits can leave committed changes even if a later command fails; the recorded outcome preserves that distinction.

Instrumented executor connections attach their own activity ID and known identity metadata to their row changes. Connection-local attribution avoids assigning concurrent external writes to the last caller. Ordinary external SQLite clients still work without Python UDFs, including writes while the viewer is closed; their reads and identity cannot be inferred. No attribution is guessed from timestamps or neighboring IDs. Linking a change to a call does not make attempted/rolled-back effects durable. A process crash or call-log write failure can leave a committed attributed change without a completed call record; no missing call outcome is invented.

Callers should supply known `activity_context` chat/session/agent IDs and titles. A fallback session stays stable for an executor process, while unknown chats/agents remain unknown. Actual names, Codex chat ancestry and earlier missing metadata cannot be reconstructed automatically. Restarting a process creates a new fallback session unless the caller supplies a stable session ID.

Values preserve SQLite storage type; blobs are hexadecimal, nulls explicit. Text/blob fields have bounded previews (roughly 32 KiB of preview content per row, at most 16 KiB per field, with additional JSON/type metadata); lengths and truncation are marked. This is an investigation record, not a complete backup of long values. All source tables may contain private content, and the journal retains deleted content. Export and protect the database accordingly. History has no automatic disk pruning; it increases database size and write work. Back up and prune deliberately if needed. Deleting log rows also cleans their element links even when foreign-key enforcement is off.

Known graph links cover v3 `nodes`, `edges`, `symbol_details`, `file_details`, and `evidence`. They use the viewer's composite graph IDs. Custom tables still retain row history but arbitrary SQL mappings do not automatically supply graph links. Deleting evidence/detail rows does not label the attached node itself as deleted. The viewer rejects non-v3 databases before history setup can modify them.

## Interface and paging

Recent calls and changes are restored when opening the page; Live retrieves later IDs. The timeline groups loaded events by chat and session, collapsed initially. Each group shows counts of loaded calls/changes, can reveal individual events in batches of 50, and can highlight the union of its loaded references. These are loaded-history counts and highlights, not totals for the entire stored session. Unknown/unassigned changes remain separate. Groups retain expansion and selection during Live updates.

**Load older calls & changes** retrieves earlier pages from both streams. Requests return at most 200 events per stream and use bounded response budgets; browser history retains at most 10,000 events with a visible limit notice. The database retains earlier rows even when they are outside browser history. Stable activity IDs deduplicate a call available through both DB history and its optional legacy export. Tables/SQL inspection remains available for deliberate investigation.

Click a saved activity to highlight related current elements and inspect an individual change's field values before/after. Deleted or renamed IDs can be absent from the current graph; their stored row values remain visible. Filters/layers/grouping can also hide referenced elements. Caller filters include correctly attributed changes and exclude unknown authors. **Record highlight**, pause and **Reset highlight** only control browser accumulation; they do not stop or erase database recording.

## Schema updates, suspension and limits

Installation is transactional and idempotent. It checks the owner and format before touching reserved names and refuses incompatible collisions. Automatic management refreshes owned triggers when it observes a schema-version change. New autocommit tables gain triggers before the next statement. If a table is created inside an open native transaction, its triggers are installed after COMMIT; population in that same transaction predates recording. Existing tracked tables keep their transaction-local history. Writes before a table's triggers exist cannot be reconstructed. Missing/stale or unsupported-table tracking is shown in journal status. Virtual/shadow tables and tables wider than 200 ordinary columns are excluded. Generated/hidden columns are not independently archived. DDL itself is not a row event.

SQLite `INSERT OR REPLACE` can delete conflicting rows without DELETE triggers unless the writer enables `recursive_triggers`. The journal does not change writer pragmas or promise those implicit deletions; use explicit DELETE/UPDATE or UPSERT when the complete row transition matters. Trigger failures follow normal SQLite transaction semantics and can reject the source write. This extension is an observation aid, not a tamper-proof or lossless audit service.

Stop all viewers/executors managing this database, or run them with `--no-history`, before deliberate migration or suspension; an active manager otherwise resumes automatic tracking. The standalone installer supports:

```powershell
python scripts/evomneme_journal.py suspend --database "C:/path/to/host/.evomneme/knowledge.sqlite3"
python scripts/evomneme_journal.py install --database "C:/path/to/host/.evomneme/knowledge.sqlite3"
```

Suspension removes owned source triggers and preserves all history. Installation resumes recording; it cannot fill the suspended interval. Existing-history viewing works while suspended. Base-schema migration tools may reject extended databases; follow their explicit compatibility/preflight requirements and back up first. Prefer completing the base graph migration before enabling this extension. No real host database is modified by development tests.
