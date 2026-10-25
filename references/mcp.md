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

Only `sql` is required. Defaults are 50 rows, 16384 output bytes, and a 5000ms execution/busy budget. Allowed ranges are 0–1000 rows, 1024–1048576 output bytes, and 1–60000ms. Input is limited to 1MiB and scripts to 100 statements; SQLite values/rows have an 8MiB limit. Bind positional arrays or named objects for a single statement; multi-statement scripts cannot receive parameters. The executor owns an atomic transaction across a script, including DDL and writes. Transaction-control statements are refused. Connection foreign keys remain enabled; the tool does not impose a schema or interpret `user_version`.

Success returns `ok:true`, `committed:true`, `results`, and `output_truncated`. Each result has `columns`, `rows` as value arrays, `rows_returned`, `rows_omitted`, and `affected_rows`. Row limits count the whole request; each retained result is a prefix with an exact omitted-row count. Affected rows use SQLite's change delta, including triggers/cascades, not a SELECT count. Whole rows are omitted rather than silently shortening cells. BLOB values use `{"$blob_base64":"..."}` in parameters/results; nonfinite floats use `{"$float":"Infinity"}` (or `-Infinity`/`NaN`) in results. Budget includes execution-result metadata; metadata overflow rolls back. MCP returns this object in `structuredContent` plus a compatibility JSON text copy; envelope/copy bytes exceed the executor budget.

Bound output does not excuse an expensive query: use predicates/columns/limits and small graph depth. Row production is consumed so a successful write with `RETURNING` still completes even when output is truncated; check commit status before retrying a write.

Errors return `ok:false`, `committed:false`, and `error` with `kind`, bounded `message`, `message_truncated`, and zero-based `failed_statement_index` (or null), plus `sqlite_errorcode`/`sqlite_errorname` for SQLite failures. Diagnostics obey the requested byte budget by shortening only the message and setting its truncation flag. Errors/timeouts roll back the batch without intentionally echoing SQL/parameters. A rollback failure closes the connection and requires inspection before reopening. File attachment, SQL extension loading, file-access functions, and changes to fixed connection settings are blocked, including journal-mode setters; reading `PRAGMA journal_mode` is permitted. `VACUUM` cannot run within the executor's atomic transaction; use a separately authorized SQLite maintenance facility when necessary. These are execution guardrails, not validation of agent-authored facts or permission to run arbitrary incoming SQL.

## Verify the connection

Use the actual configured client to initialize, list the tool, inspect schema with a bounded query, and exercise a controlled read/write/rollback in a synthetic fixture. Check that the selected database is the intended host's and another host is isolated. Record transport evidence and limitations locally. Starting the process or passing a wire harness does not prove a real client's configuration works.

Separately follow [instruction verification](integration.md): test that a fresh ordinary host session loads the full live skill, and that a later session loads an authorized instruction update. MCP startup and tool discovery cannot establish either condition. Report unavailable checks as incomplete; no real host is integrated by this repository's isolated tests.
