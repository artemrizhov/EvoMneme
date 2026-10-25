# Optional MCP SQL transport

The stdio adapter exposes one `execute_sql` tool backed by the same executor as the CLI. Its database is bound once at startup; callers cannot choose a path in tool arguments. It has no network server, SDK dependency, code scanner, knowledge API, automatic schema, or instruction loader. Use it only when the authorized host's existing MCP client supports stdio; otherwise the SQL CLI or an existing authorized SQLite interface is sufficient.

## Project-local setup

First select and exclude the host's local database as described in [storage setup](storage.md). Use an existing Python 3.11+ executable and trusted absolute tool path. An illustrative JSON client entry is below; place it only in the **host's supported project-local** MCP configuration after checking that client's documented format. This is not a universal filename/configuration guarantee or a request to change global client settings.

```json
{
  "mcpServers": {
    "evomneme-host": {
      "command": "<existing-absolute-python-executable>",
      "args": [
        "<absolute-tool>/scripts/evomneme_mcp.py",
        "--database", "<absolute-canonical-host-db>"
      ]
    }
  }
}
```

The file must exist unless `--create` is explicitly added to permit an empty new database. No schema is applied. Linked worktrees must use the same canonical host path; separate hosts/clones must use different files and entries. Do not configure this tool repository as a host, or install an MCP SDK/client/runtime for this optional route. A configured integration failure still needs reporting and authorization for repair or another route.

The server supports MCP **2025-11-25** and **2025-06-18**; unsupported version requests negotiate 2025-11-25, rather than implying newer-version support. Its lifecycle, stdio framing, and tools interface follow the [lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle), [transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), and [tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) specifications. Client initialization must finish before tool calls. Requests are synchronous; cancellation is unsupported and not advertised. Keep stdout exclusively for protocol messages; do not wrap startup in a shell banner or a command that emits unrelated output.

## Execute SQL

`execute_sql` arguments, also accepted by CLI `--input`, are:

```json
{
  "sql": "SELECT id,title,summary FROM records WHERE scope_id=:scope AND validity='current' LIMIT 8",
  "params": {"scope": "verified-scope-id"},
  "max_rows": 8,
  "max_output_bytes": 12000,
  "timeout_ms": 5000
}
```

Only `sql` is required. The same operation is available as `Executor.execute_sql` in the Python source and CLI JSON `--input`; request semantics are identical. `sql` is either one native SQLite statement with optional top-level `params`, or an array of `{sql,params}` command objects, each with its own binding. Do not concatenate commands into a string: no custom SQL splitter runs. See [the atomic batch example](storage.md) for explicit `BEGIN`/`COMMIT` objects.

Defaults are 50 rows, 16384 output bytes, and a 5000ms execution/busy budget. The shared runtime argument specification supplies bounds, MCP input metadata, and CLI options; there is no separate MCP execution implementation. SELECTs return a bounded prefix and `has_more` after at most one lookahead rather than scanning the rest to count omitted rows. DML RETURNING completes writes even if returned rows are bounded. Use small predicates/columns/limits and graph depth; an output limit alone does not guarantee cheap SQL.

**SQLite owns transaction behavior.** A batch is sequential, not automatically atomic: put related changes between explicit `BEGIN`/`COMMIT` commands in one array. Native savepoints, `VACUUM`, and journal-mode operations are available subject to SQLite's own rules. An open transaction is rolled back on request failure or at request end, so it cannot span calls. Earlier autocommitted statements or completed commits remain durable even if a later command fails; inspect execution/rollback results before retrying. A SELECT prefix does not imply an incomplete DML write.

The shared result contains `ok`, `results`, `completed_statements`, `transaction_rolled_back`, `autocommit_effects_possible`, and an optional `error`. Each command result has `columns`, value-array `rows`, `has_more`, and `affected_rows`. Row limits apply across the request; there is no exact omitted-row count or blanket `committed` flag. Preceding results/affected-row counts are execution observations and may describe changes later rolled back. `transaction_rolled_back` reports cleanup of an open transaction at request end/error; an explicit SQL `ROLLBACK` is instead a completed native command. `autocommit_effects_possible` conservatively warns that a retry may repeat durable work, rather than proving an exact change count. If prior outputs cannot fit beside diagnostics, whole resultsets may be omitted with `results_truncated:true`; `completed_statements` still counts completed commands.

BLOB values use `{"$blob_base64":"..."}` in parameters/results; nonfinite SQLite floats use `{"$float":"Infinity"}` (or `-Infinity`/`NaN`) in results. Input JSON must remain standards-compliant. MCP exposes the shared object in `structuredContent` and a compatibility JSON text copy; envelope/copy bytes exceed the executor object's budget.

An `error` has `kind`, bounded `message`, `message_truncated`, zero-based `failed_statement_index` (or null), and SQLite error code/name when available, without intentionally echoing SQL/parameters. Available preceding results remain within the output budget. An unfinished transaction returns `ok:false` with a transaction error after rollback; it cannot silently persist between calls. Errors do not undo prior commits/autocommit effects. A rollback failure requires inspection before reopening. One persistent database remains fixed: nonempty attached paths, `:memory:` attachments, URIs, extensions, and SQL file-access functions are refused. SQLite's empty-filename temporary workspace, including `ATTACH ''`, is allowed so native maintenance such as `VACUUM` can work. This boundary validates neither facts, host identity, nor permission to execute incoming SQL.

## Verify the connection

Use the actual configured client to initialize, list the tool, inspect schema with a bounded query, and exercise a controlled read/write/rollback in a synthetic fixture. Check that the selected database is the intended host's and another host is isolated. Record transport evidence and limitations locally. Starting the process or passing a wire harness does not prove a real client's configuration works.

Separately follow [instruction verification](integration.md): test that a fresh ordinary host session loads the full live skill, and that a later session loads an authorized instruction update. MCP startup and tool discovery cannot establish either condition. Report unavailable checks as incomplete; no real host is integrated by this repository's isolated tests.
