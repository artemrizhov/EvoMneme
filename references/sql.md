# SQL execution contract

Use the bound [graph commands](navigation.md) for ordinary navigation and [maintenance commands](mutations.md) for graph writes. For advanced SQL, [storage usage](storage.md) covers Python import/create/close, SQL CLI requests and schema setup. Select and exclude one explicit host database; respect configured integrations and report failures before changing routes.

Managed v3 databases automatically retain row changes and SQL-call activity in the same SQLite file. The [Cytoscape explorer](viewer.md) reads this history without trace-directory setup and groups activities by session. Supply known per-call `activity_context` IDs and titles. `--no-history` opts a process out of history setup/recording; optional legacy JSONL tracing remains available. Generic or not-yet-initialized SQLite files keep the native SQL contract without automatic history installation.

## Shared SQL contract

`execute_sql` arguments, also accepted by CLI `--input`, are:

```json
{
  "sql": "SELECT id,title,summary FROM nodes WHERE scope_id=:scope AND validity='current' LIMIT 8",
  "params": {"scope": "verified-scope-id"},
  "max_rows": 8,
  "max_output_bytes": 12000,
  "timeout_ms": 5000
}
```

Only `sql` is required. The same operation is available as `Executor.execute_sql` in the Python source and CLI JSON `--input`; request semantics are identical. `sql` is either one native SQLite statement with optional top-level `params`, or an array of `{sql,params}` command objects, each with its own binding. Do not concatenate commands into a string: no custom SQL splitter runs. See [the atomic batch example](storage.md) for explicit `BEGIN`/`COMMIT` objects.

Only the fields below are accepted; unknown execution/command keys are rejected. CLI `--input` supplies this object, Python calls `executor.execute_sql(**request)`.

| Field | Accepted value / default |
| --- | --- |
| `sql` | Required nonempty statement string, or array of 1–100 objects containing `sql` and optional `params`. |
| `params` | Optional positional array for `?`, or named object for `:name` (keys omit `:`). For a batch, put it in each command and omit it at top level. |
| `activity_context` | Optional object containing `chat_id`, `chat_title`, `session_id`, `session_title`, `agent_id`, `agent_name`; each supplied value is a nonempty string up to 200 characters. Reuse stable IDs and the parent chat identity for subagents; pass only known information. Automatic managed-store history preserves this metadata without changing SQL results. |
| `max_rows` | Integer 0–1000; default 50, shared across all command results. |
| `max_output_bytes` | Integer 1024–1048576; default 16384 for the full execution-result object. |
| `timeout_ms` | Integer 1–60000; default 5000 for execution and lock waits together. |

Parameter values are null, string, boolean, signed 64-bit integer, finite float, or a `{"$blob_base64":"..."}` object. Use that tag for bytes even in Python; nested arrays/ordinary objects are not scalar bindings. Nonstandard JSON NaN/Infinity and lone surrogates are refused. SQL plus bindings are limited to 1MiB encoded input; CLI files also have a 1MiB bound. SQLite's individual value/row length limit is 8MiB; output may omit a row sooner because of its JSON budget.

SELECTs return a bounded prefix and `has_more` after at most one lookahead rather than scanning the rest to count omitted rows. DML RETURNING completes writes even if returned rows are bounded. Use small predicates/columns/limits and graph depth; an output limit alone does not guarantee cheap SQL. The shared runtime specification drives Python and CLI, rather than separate execution implementations.

**SQLite owns transaction behavior.** A batch is sequential, not automatically atomic: put related changes between explicit `BEGIN`/`COMMIT` commands in one array. Native savepoints, `VACUUM`, and journal-mode operations are available subject to SQLite's own rules. An open transaction is rolled back on request failure or at request end, so it cannot span calls. Earlier autocommitted statements or completed commits remain durable even if a later command fails; inspect execution/rollback results before retrying. A SELECT prefix does not imply an incomplete DML write.

The shared result contains `ok`, `results`, `completed_statements`, `transaction_rolled_back`, `autocommit_effects_possible`, and an optional `error`. Each command result has `columns`, value-array `rows`, `has_more`, and `affected_rows`. Row limits apply across the request; there is no exact omitted-row count or blanket `committed` flag. Preceding results/affected-row counts are execution observations and may describe changes later rolled back. `transaction_rolled_back` reports cleanup of an open transaction at request end/error; an explicit SQL `ROLLBACK` is instead a completed native command. `autocommit_effects_possible` conservatively warns that a retry may repeat durable work, rather than proving an exact change count. If prior outputs cannot fit beside diagnostics, whole resultsets may be omitted with `results_truncated:true`; `completed_statements` still counts completed commands.

For `SELECT 42 AS value`, the shared object is:

```json
{"ok":true,"results":[{"columns":["value"],"rows":[[42]],"has_more":false,"affected_rows":0}],"completed_statements":1,"transaction_rolled_back":false,"autocommit_effects_possible":false}
```

Rows align positionally with `columns`. `affected_rows` is SQLite's change delta including triggers/cascades, not a SELECT count. `completed_statements` may exceed retained result count when output handling fails after native completion. An ordinary engine error such as `SELECT * FROM missing` returns the same envelope with `ok:false`, `results:[]`, `completed_statements:0`, and `error` containing `kind:"sqlite"`, `failed_statement_index:0`, `sqlite_errorcode:1`, and `sqlite_errorname:"SQLITE_ERROR"`; both durability flags are false when nothing executed before it. Error kinds are `request`, `sqlite`, `timeout`, `transaction`, and `rollback`.

BLOB values use `{"$blob_base64":"..."}` in parameters/results; nonfinite SQLite floats use `{"$float":"Infinity"}` (or `-Infinity`/`NaN`) in results. Input JSON must remain standards-compliant.

An `error` has `kind`, bounded `message`, `message_truncated`, zero-based `failed_statement_index` (or null), and SQLite error code/name when available, without intentionally echoing SQL/parameters. Available preceding results remain within the output budget. An unfinished transaction returns `ok:false` with a transaction error after rollback; it cannot silently persist between calls. Errors do not undo prior commits/autocommit effects. A rollback failure requires inspection before reopening. One persistent database remains fixed: nonempty attached paths, `:memory:` attachments, URIs, extensions, and SQL file-access functions are refused. Explicit temporary attachment is allowed only in the literal form `ATTACH '' AS name`. Bound `ATTACH ? AS name` with an empty-string parameter and computed filenames are refused because SQLite's authorizer cannot establish that they name the permitted empty workspace; the tool does not rewrite SQL. SQLite-owned `VACUUM` scratch workspace remains allowed. This boundary validates neither facts, host identity, nor permission to execute incoming SQL.
