# Persistent database change history · format 1

The viewer can explicitly install a row journal in an authorized SQLite database. This is a published optional extension, separate from base graph schema v3 and JSONL SQL-call tracing. Opening the viewer without the flag leaves the database read-only; it can still read an already installed journal.

```powershell
python scripts/evomneme_viewer.py --database "C:/path/to/host/.evomneme/knowledge.sqlite3" --record-changes
```

Restart the server and reload the browser after updating the viewer. The flag opens a short read/write connection to install or refresh the journal. Graph, SQL and history requests use read-only connections. No base data migration, `user_version` change, writer-side Python callbacks, external package or MCP configuration change is needed.

## Storage and transactions

- `evomneme_change_log`: one row per INSERT, actual UPDATE or DELETE of a tracked ordinary-table row, with monotonic change ID, UTC time, source table, operation, primary key (rowid fallback), typed before/after JSON.
- `evomneme_change_elements`: links from change IDs to graph node/edge IDs, with `before`/`after` phase and entity/detail/evidence role. References survive deletion because they deliberately do not foreign-key the current graph.
- `evomneme_change_meta`: extension owner/version, installation time, tracked-table schema signatures and owned trigger names. These reserved tables do not recursively journal themselves.

SQLite AFTER triggers run inside the writer's transaction. Rollback/savepoint rollback removes their history; multirow statements produce separate entries. A no-op UPDATE produces none. Ordinary external SQLite clients are covered, including writes while the viewer is closed; reads and caller/chat identity cannot be inferred by triggers. SQL-call traces remain the source of caller metadata and read activity. Matching events by time does not establish authorship or transaction identity.

Values preserve SQLite storage type; blobs are hexadecimal, nulls explicit. Text/blob fields have bounded previews (roughly 32 KiB of preview content per row, at most 16 KiB per field, with additional JSON/type metadata); lengths and truncation are marked. This is an investigation record, not a complete backup of long values. All source tables may contain private content, and the journal retains deleted content. Export and protect the database accordingly. History has no automatic disk pruning; it increases database size and write work. Back up and prune deliberately if needed. Deleting log rows also cleans their element links even when foreign-key enforcement is off.

Known graph links cover v3 `nodes`, `edges`, `symbol_details`, `file_details`, and `evidence`. They use the viewer's composite graph IDs. Custom tables still retain row history but arbitrary SQL mappings do not automatically supply graph links. Deleting evidence/detail rows does not label the attached node itself as deleted. The viewer rejects non-v3 databases before `--record-changes` can install any history tables or triggers.

## Interface and paging

The latest 100 changes are restored when opening the page; Live retrieves later IDs. **Older database changes** first exposes more loaded events, then fetches earlier database pages. Requests return at most 200 changes and use a bounded response budget; browser history retains at most 10,000 events with a visible limit notice. The database retains earlier rows even when they are outside browser history. Tables/SQL inspection remains available for deliberate investigation.

Click a saved activity to highlight related current elements and see field values before/after. Deleted or renamed IDs can be absent from the current graph; their stored row values remain visible. Filters/layers/grouping can also hide referenced elements. Caller filters exclude database changes because their author is unknown. **Record highlight**, pause and **Reset highlight** only control browser accumulation; they do not stop or erase the SQLite journal.

## Schema updates, suspension and limits

Installation is transactional and idempotent. It checks the owner and format before touching reserved names and refuses incompatible collisions. With `--record-changes`, the viewer refreshes owned triggers when it observes a schema-version change. New tables are not recorded until their triggers are installed; writes in that interval cannot be reconstructed. Missing/stale or unsupported-table tracking is shown in journal status. Virtual/shadow tables and tables wider than 200 ordinary columns are excluded. Generated/hidden columns are not independently archived. DDL itself is not a row event.

SQLite `INSERT OR REPLACE` can delete conflicting rows without DELETE triggers unless the writer enables `recursive_triggers`. The journal does not change writer pragmas or promise those implicit deletions; use explicit DELETE/UPDATE or UPSERT when the complete row transition matters. Trigger failures follow normal SQLite transaction semantics and can reject the source write. This extension is an observation aid, not a tamper-proof or lossless audit service.

Stop any viewer managing this database before a deliberate migration or suspension. The standalone installer supports:

```powershell
python scripts/evomneme_journal.py suspend --database "C:/path/to/host/.evomneme/knowledge.sqlite3"
python scripts/evomneme_journal.py install --database "C:/path/to/host/.evomneme/knowledge.sqlite3"
```

Suspension removes owned source triggers and preserves all history. Installation resumes recording; it cannot fill the suspended interval. Existing-history viewing works while suspended. Base-schema migration tools may reject extended databases; follow their explicit compatibility/preflight requirements and back up first. Prefer completing the base graph migration before enabling this extension. No real host database is modified by development tests.
