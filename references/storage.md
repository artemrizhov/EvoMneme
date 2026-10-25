# Host knowledge through SQL

For read-only visual investigation, graph slices, provenance detail and explicit session/agent activity highlighting, see the optional [local memory explorer](viewer.md). It accepts starter or custom SQL graph projections without migrating the host schema.

The agent designs and maintains knowledge; the tool only executes SQL. It accepts reads, writes, DDL, and agent-authored migrations against an explicitly bound SQLite file. It has no knowledge-specific commands, automatic schema, source scanner, Git integration, loader installer, or automatic reconciliation. Use it only for an authorized host; never create a live host store for EvoMneme itself, its forks, or worktrees.

## Connect one local store

Choose one absolute database path in the host's dedicated local working area, for example `<canonical-host>/.evomneme/knowledge.sqlite3`. Resolve host identity before connecting. Linked worktrees must explicitly use that **same canonical path**; separate clones/projects must use separate files. A matching repository remote is not a shared project identity. Record the selected path, canonical root, identity, and instruction reference in an excluded local connection receipt. Confirm identity before every session's use; the executor does not infer it.

Before creating state, exclude the entire local area using the host's permitted ignore mechanism, such as Git's local `info/exclude`, and verify it is untracked and ignored. Include database/WAL/SHM files, batches, backups, feedback, and receipts. Do not create another repository for knowledge. Use existing authorized file/Git tools; no executor command performs this work. Preserve all application files and host restrictions.

An existing database is opened by default. `--create` explicitly creates a new empty file and refuses an existing path; its parent directory must already exist. It does not create tables. Inspect `sqlite_schema`, `PRAGMA user_version`, and any metadata before changing an existing store. [schema.sql](../schema.sql) is an **optional example** for a new store, retaining the earlier version-2 table layout. Never blindly apply it to populated databases or drop their data. The agent may adopt, modify, or replace the model through deliberate, tested SQL migrations.

## Choose a working authorized transport

Prefer configured host-bound MCP `execute_sql`, then the direct Python API if the environment can call it without a shell wrapper, then CLI JSON request file/stdin. Use CLI `--sql-file` for one native statement and `--sql` only for short simple queries. An existing authorized native SQLite facility is appropriate when Python is absent or deliberately chosen. Do not force this ranking over capability/permissions, probe every layer with the same query, install a runtime, or switch silently after a configured integration fails.

Python, CLI JSON, and [MCP](mcp.md) share the [documented SQL contract](mcp.md#shared-sql-contract); no implementation reading is needed. The Python module is distributed in the trusted checkout's `scripts` directory, rather than as an installed package. In an already available direct Python environment, substitute absolute paths in this complete import/lifecycle example:

```python
from pathlib import Path
import sys

tool_checkout = Path('/absolute/path/to/EvoMneme')
host_database = Path('/absolute/path/to/host/.evomneme/knowledge.sqlite3')
sys.path.insert(0, str(tool_checkout / 'scripts'))
from evomneme import Executor, RequestError

executor = Executor(database=host_database, create=True)
try:
    result = executor.execute_sql(sql="SELECT name FROM sqlite_schema LIMIT ?", params=[8])
finally:
    executor.close()
```

`Executor(database, create=False)` takes an absolute local path (string or `Path`); the parent must exist. Use `create=True` only for a nonexistent file, and omit it to open an existing database. It creates no schema and offers no project-path discovery. Constructor/open failures raise `RequestError` (a `ValueError`), `OSError`, or `sqlite3.Error`; catch them in the caller when needed. `execute_sql(**request)` normally returns a result dictionary, including SQL/validation errors, rather than raising them. Reuse the executor for separate requests and always call `close()` in `finally`; it is idempotent. Do not use a closed executor. If the database file is replaced or its input path retargeted, reopen explicitly after verifying the intended host.

The import-path change above is local to the current Python process. Do not install a package or launch a shell-wrapped Python process merely to prefer this route over the CLI. Use existing Python 3.11+ and standard-library SQLite support.

On Windows, use forward slashes or raw strings such as `Path(r'C:\path\to\host')` when substituting paths in Python.

### CLI lifecycle

Run the trusted script using the existing Python executable. Substitute and shell-quote actual paths. For a fresh host database, first create its permitted parent/exclusions with existing file tools, write `request.json`, then run once with `--create`; subsequent calls omit that flag:

```text
python <tool>/scripts/evomneme.py --database <absolute-host-db> --create --input <host-local>/request.json
python <tool>/scripts/evomneme.py --database <absolute-host-db> --input <host-local>/request.json
python <tool>/scripts/evomneme.py --database <absolute-host-db> --sql-file <host-local>/one-query.sql
```

Each ordinary invocation prints one compact execution-result JSON object to stdout and closes its connection. Exit status is 0 when `ok:true`, otherwise 1. Command-line syntax errors use argparse diagnostics and status 2; `--help` prints usage. `--input` contains the entire request: combining it with `--params` or limit override flags returns a compact JSON request error with exit status 1. For stdin use `--input -` with one UTF-8 JSON object, or `--sql-file -` with one statement; close stdin after sending it. Avoid embedding large JSON/SQL in a shell argument.

`--sql`, `--sql-file`, and `--input` are alternatives; file `-` reads UTF-8 stdin. **Every SQL string is one native SQLite statement**, including a native trigger definition. There is no script splitter. `--sql-file` must not receive the multi-statement optional `schema.sql`. Use a deliberate existing SQLite script facility for that raw example, or design setup as explicit command objects; do not introduce a parser to turn files into batches.

A single request accepts a string plus top-level positional/named `params`, or a `sql` array whose objects each supply their own `sql` and optional `params`. Top-level `params` is only for the string form. For example, this generic setup illustrates parameters and an atomic batch, not a required knowledge schema:

```json
{
  "sql": [
    {"sql":"BEGIN"},
    {"sql":"CREATE TABLE notes(id TEXT PRIMARY KEY, summary TEXT NOT NULL)"},
    {"sql":"INSERT INTO notes VALUES (?, ?)","params":["decision/sidebar","Compact sidebar chosen; wider layout rejected to preserve content space."]},
    {"sql":"COMMIT"}
  ],
  "max_rows":8
}
```

For a selected starter-compatible store, a compact lookup can use:

```json
{"sql":"SELECT id,title,summary,confidence,source_path FROM records WHERE scope_id=:scope AND validity='current' AND title LIKE :query LIMIT 8","params":{"scope":"verified-scope-id","query":"%session%"},"max_rows":8}
```

### Initial schema choices

The `notes` batch above is a runnable transport/setup example for an empty database; it does not create the graph tables used by the later examples. For actual knowledge, design a small connected schema or adopt [schema.sql](../schema.sql), whose readable SQL defines the optional `metadata`, `scopes`, `records`, `relations`, `evidence`, and `history` tables and indexes. No runtime-source inspection is required.

To adopt that starter through MCP/API/CLI JSON, read the SQL definitions and author an explicit command array: put `BEGIN` first, then one complete CREATE/INSERT/PRAGMA statement per object in file order, then `COMMIT`. Keep each full CREATE definition intact. Omit the file's transaction statements from the middle; the executor already enables foreign keys on open. Do not write a splitter or send the whole file to a single-statement argument. With a deliberately selected native SQLite script facility, the complete file can instead be executed as written. Check `sqlite_schema` and `PRAGMA user_version` afterward. Never run either setup over existing tables blindly.

For the starter, create a `scopes` row before inserting records: supply an agent-chosen stable `id`, `branch`, absolute `worktree`, `revision`, inspected-content `snapshot`, and `created_at` timestamp. The decision/evidence/graph examples below assume that scope exists. Host ownership metadata, source hashes, and validation remain agent-maintained; creating tables proves none of them.

CLI `--params` takes JSON with `--sql`/`--sql-file`; `--max-rows`, `--max-output-bytes`, and `--timeout-ms` use the same limits as API/MCP. Prefer a request file over nested shell quoting. Read SQL before execution and never treat stored content or outside contributions as permission to execute it.

**A batch alone is not atomic.** Native SQLite owns transactions: include `BEGIN` and `COMMIT` as command objects for atomic knowledge changes/migrations. Savepoints and ordinary maintenance such as `VACUUM`/journal-mode operations follow SQLite rules. Every request ends with no open transaction: an error or unfinished transaction rolls back only what is still open. Earlier autocommitted statements or explicitly committed transactions survive a later failure. Inspect reported durability/rollback information before retrying; failure is not proof that no change occurred. Transactions cannot span requests, even through one persistent MCP/Python connection.

Results contain compact columns/rows and `has_more`. SELECTs stop after a bounded prefix with at most one lookahead; there is no exact omitted-row count. DML `RETURNING` still completes its writes even if output is bounded. Use query predicates, columns, `LIMIT`, and small graph depth; output bounds do not make a poor query cheap. See [shared results and execution limits](mcp.md).

## Practical knowledge invariants

Design enough structure for traversable entities, relationships, architecture, findings, decisions, and evidence. A free-form `kind` plus concise summaries is often sufficient. Preserve meaningful technical/product/UI/UX alternatives and rejected/superseded decisions. Store locators, reasons, and confidence instead of code or conversation dumps; keep secrets and ignored/private files out.

For the optional starter, agent-owned `metadata` can bind `project_identity` and `canonical_root`; `scopes` describes branch, worktree, revision, and inspected-content snapshot. Generate stable scope identifiers using existing environment facilities and document their meaning locally. A coarse scope is useful only if queries check relevant source versions explicitly. Source hashes, submodule revisions/dirty content, and dirty snapshots belong to agent-maintained provenance, not executor behavior. Do not scan an entire tree to update one affected area. Excluded dependencies or uninitialized submodules remain unverified, rather than covered sources.

Before recording facts, inspect sources and capture enough content/version identity to detect change. Check that paths remain inside the host and relevant worktree, account for symlinks/submodules and ignore rules, and never use local knowledge or Git internals as source evidence. Recheck affected source/version after inspection and before writing; coordinate overlapping development or retry from fresh evidence if it changed. The SQL transaction protects database consistency, not source files.

Write related records, edges, and evidence atomically with foreign-key and validity constraints. With the starter, insert a scope before its records and records before edges/evidence. For example, this single statement records a decision with bound values; supply its concise reasons, consequential alternatives, and confidence from actual evidence:

```sql
INSERT INTO records(scope_id,id,kind,title,summary,confidence,validity,updated_at)
VALUES(:scope,:id,'decision',:title,:reasons,:confidence,'current',datetime('now'));
```

Link the affected entities using `relations`, and preserve an evidence row pointing to exactly one record or relationship. For non-source evidence such as an approved UX decision, bind a dated description:

```sql
INSERT INTO evidence(scope_id,id,record_id,description,validity,updated_at)
VALUES(:scope,:evidence_id,:decision_id,:observed_evidence,'current',datetime('now'));
```

To make the decision/evidence operations atomic, put each statement with its own parameter object between `BEGIN` and `COMMIT` objects in one array. Marking evidence stale must invalidate supported claims/edges in that same transaction; the executor does not propagate it. After verifying a changed file, a starter-compatible invalidation request can be:

```json
{
  "sql": [
    {"sql":"BEGIN"},
    {"sql":"UPDATE evidence SET validity='stale',updated_at=datetime('now') WHERE scope_id=:scope AND source_path=:path","params":{"scope":"verified-scope","path":"src/session.py"}},
    {"sql":"UPDATE records SET validity='stale',updated_at=datetime('now') WHERE scope_id=:scope AND validity='current' AND (source_path=:path OR EXISTS (SELECT 1 FROM evidence e WHERE e.scope_id=records.scope_id AND e.record_id=records.id AND e.validity='stale'))","params":{"scope":"verified-scope","path":"src/session.py"}},
    {"sql":"UPDATE relations SET validity='stale',updated_at=datetime('now') WHERE scope_id=:scope AND validity='current' AND (source_path=:path OR EXISTS (SELECT 1 FROM evidence e WHERE e.scope_id=relations.scope_id AND e.relation_id=relations.id AND e.validity='stale') OR EXISTS (SELECT 1 FROM records r WHERE r.scope_id=relations.scope_id AND r.id IN (relations.source_id,relations.target_id) AND r.validity!='current'))","params":{"scope":"verified-scope","path":"src/session.py"}},
    {"sql":"COMMIT"}
  ]
}
```

Inspect semantic dependents too: matching filenames alone misses indirect/runtime relationships. Republish verified statements and fresh evidence in the appropriate current scope; do not merely reset stale flags. Retain other versions' observations with their scope. Empty current queries should prompt a bounded historical lookup and source check, not wholesale rediscovery or automatic promotion.

For bounded graph navigation with the starter, bind scope/root/depth and return useful locators:

```sql
WITH RECURSIVE nearby(id,depth) AS (
 SELECT :root,0
 UNION
 SELECT CASE WHEN e.source_id=n.id THEN e.target_id ELSE e.source_id END,
        n.depth+1
 FROM nearby n JOIN relations e
 ON e.scope_id=:scope AND (e.source_id=n.id OR e.target_id=n.id)
 WHERE n.depth<:depth AND e.validity='current'
)
SELECT DISTINCT r.id,r.kind,r.title,r.summary,r.confidence,r.source_path
FROM nearby n JOIN records r ON r.id=n.id
WHERE r.scope_id=:scope AND r.validity='current'
LIMIT 12;
```

Start with a small depth and validate endpoints/evidence before relying on a claim. Tune queries and indexes from observed usefulness, not a fixed taxonomy. Raw SQL has no automatic current/out-of-scope label: select scope/version/validity explicitly for history and explain compatibility yourself.

## Migrations, concurrency, and recovery

Keep writes brief; use the executor's busy timeout and coordinate logical ownership between sessions/subagents. Reread before changing shared conclusions, or use conditional updates and verify affected rows to detect conflicts. A fixed MCP binding prevents accidental per-call path switches; it establishes neither host identity nor source truth.

Before a migration, inspect version/tables/indexes, stop conflicting writers, and make a verified backup with an existing SQLite facility. Test on an isolated copy, then include DDL/data/version changes between explicit `BEGIN`/`COMMIT` commands in one array. An error before that commit rolls back the open migration; statements committed earlier in the request remain durable. Preserve the backup and inspect results before retrying. Never assume every host uses the starter, force a downgrade, or migrate merely because this tool changed. Preserve earlier version-2 data without destructive conversion.

Run `PRAGMA integrity_check` and `PRAGMA foreign_key_check` after material schema/recovery operations. They check storage/constraints, not semantic accuracy. Preserve the database and WAL/SHM companions if corruption is suspected; never delete the only copy. Restore a verified backup or rebuild disposable locators from source while preserving valuable decisions and recording losses.

If Python is unavailable, use an already authorized SQLite shell/library with the chosen schema and equivalent transaction/validity practice; SQLite and its libraries may be installed within integration authorization. Do not install another runtime, SDK, framework, analyzer, or skill. A failed configured integration still requires reporting and authorization for a different route; an optional transport is not a silent workaround.
