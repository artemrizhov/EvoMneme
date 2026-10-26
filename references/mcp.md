# Optional MCP SQL transport

Managed v3 databases automatically retain row changes and SQL-call activity in the same SQLite file. The [Cytoscape explorer](viewer.md) reads this history without trace-directory setup and groups loaded activities by session. Supply known per-call `activity_context` (chat/session/agent IDs and readable titles); MCP initialization contributes client metadata but cannot discover chat ancestry. `--no-history` opts a process out of history setup/recording; optional legacy JSONL tracing remains available. Graph inspection is read-only after history setup; the viewer binds to loopback and the stdio adapter remains network-free.

The stdio adapter exposes one `execute_sql` tool backed by the same executor as the CLI. Its database is bound once at startup; callers cannot choose a path in tool arguments. It has no network server, SDK dependency, code scanner, knowledge API, automatic base-graph schema creation, or instruction loader. History is a published versioned extension installed only in recognized managed stores; generic or not-yet-initialized SQLite files keep the native SQL contract. Use it only when the authorized host's existing MCP client supports stdio; otherwise the SQL CLI or an existing authorized SQLite interface is sufficient.

## Project-local setup

The availability/setup notice below applies to SQL maintenance and advanced SQL access. Ordinary [read-only navigation](navigation.md) through the selected `evomneme nodes` / `evomneme links` CLI does not require SQL authoring, SQL MCP or a missing-SQL-tool notice.

If `execute_sql` is unavailable in an authorized host session and the host's `AGENTS.md` has no applicable refusal, explicitly report that fact and offer to connect this adapter. Check actual client tool availability before assigning a cause; distinguish a missing configuration from an observed startup/discovery failure or an unverified cause. Give the notice before an authorized alternative SQL route is used. Record an explicit project-level refusal in the host's `AGENTS.md` and honor it across sessions as described in [SQL tool priority](../SKILL.md#sql-tool-priority); suppress routine absence notices and connection offers until the user revises that decision. Respect an existing transport decision, avoid repeated unchanged notices in the same session, and configure or repair only within the user's authorization. MCP remains optional; a working Python/CLI route does not make its tool available to the client.

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

For a direct stdio client, the equivalent launch is `python <tool>/scripts/evomneme_mcp.py --database <absolute-host-db>` (add `--create` once for a new file). Send one UTF-8 JSON object per newline; read one response per request, while notifications receive none. After the initialization response, this minimal sequence discovers and calls the tool:

```jsonl
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"host-agent","version":"1"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"execute_sql","arguments":{"sql":"SELECT ? AS value","params":[42],"max_rows":1}}}
```

Keep stdin open while using the server; close it to send EOF and close the database connection. Startup/transport failure writes diagnostics to stderr and exits 1. Normal EOF exits 0. The server does not implement a separate shutdown request.

The server supports MCP **2025-11-25** and **2025-06-18**; unsupported version requests negotiate 2025-11-25, rather than implying newer-version support. Its lifecycle, stdio framing, and tools interface follow the [lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle), [transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), and [tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) specifications. Client initialization must finish before tool calls. Requests are synchronous; cancellation is unsupported and not advertised. Keep stdout exclusively for protocol messages; do not wrap startup in a shell banner or a command that emits unrelated output.

Invalid UTF-8, unencodable lone surrogates, and JSON nested beyond the decoder's supported depth are rejected before dispatch with bounded JSON-RPC parse error `-32700` and `id:null`. The server can process the next valid frame; valid Unicode surrogate pairs remain supported.

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

Only the fields below are accepted; unknown execution/command keys are rejected. CLI `--input` supplies this object, Python calls `executor.execute_sql(**request)`, and MCP supplies it as `tools/call.params.arguments`.

| Field | Accepted value / default |
| --- | --- |
| `sql` | Required nonempty statement string, or array of 1–100 objects containing `sql` and optional `params`. |
| `params` | Optional positional array for `?`, or named object for `:name` (keys omit `:`). For a batch, put it in each command and omit it at top level. |
| `activity_context` | Optional object containing `chat_id`, `chat_title`, `session_id`, `session_title`, `agent_id`, `agent_name`; each supplied value is a nonempty string up to 200 characters. Reuse stable IDs and the parent chat identity for subagents; pass only known information. Automatic managed-store history preserves this metadata without changing SQL results. MCP initialization supplies client name/version separately when reported. |
| `max_rows` | Integer 0–1000; default 50, shared across all command results. |
| `max_output_bytes` | Integer 1024–1048576; default 16384 for the full execution-result object. |
| `timeout_ms` | Integer 1–60000; default 5000 for execution and lock waits together. |

Parameter values are null, string, boolean, signed 64-bit integer, finite float, or a `{"$blob_base64":"..."}` object. Use that tag for bytes even in Python; nested arrays/ordinary objects are not scalar bindings. Nonstandard JSON NaN/Infinity and lone surrogates are refused. SQL plus bindings are limited to 1MiB encoded input; CLI files/MCP frames also have a 1MiB bound. SQLite's individual value/row length limit is 8MiB; output may omit a row sooner because of its JSON budget.

SELECTs return a bounded prefix and `has_more` after at most one lookahead rather than scanning the rest to count omitted rows. DML RETURNING completes writes even if returned rows are bounded. Use small predicates/columns/limits and graph depth; an output limit alone does not guarantee cheap SQL. The shared runtime specification drives all three transports, rather than separate execution implementations.

**SQLite owns transaction behavior.** A batch is sequential, not automatically atomic: put related changes between explicit `BEGIN`/`COMMIT` commands in one array. Native savepoints, `VACUUM`, and journal-mode operations are available subject to SQLite's own rules. An open transaction is rolled back on request failure or at request end, so it cannot span calls. Earlier autocommitted statements or completed commits remain durable even if a later command fails; inspect execution/rollback results before retrying. A SELECT prefix does not imply an incomplete DML write.

The shared result contains `ok`, `results`, `completed_statements`, `transaction_rolled_back`, `autocommit_effects_possible`, and an optional `error`. Each command result has `columns`, value-array `rows`, `has_more`, and `affected_rows`. Row limits apply across the request; there is no exact omitted-row count or blanket `committed` flag. Preceding results/affected-row counts are execution observations and may describe changes later rolled back. `transaction_rolled_back` reports cleanup of an open transaction at request end/error; an explicit SQL `ROLLBACK` is instead a completed native command. `autocommit_effects_possible` conservatively warns that a retry may repeat durable work, rather than proving an exact change count. If prior outputs cannot fit beside diagnostics, whole resultsets may be omitted with `results_truncated:true`; `completed_statements` still counts completed commands.

For `SELECT 42 AS value`, the shared object is:

```json
{"ok":true,"results":[{"columns":["value"],"rows":[[42]],"has_more":false,"affected_rows":0}],"completed_statements":1,"transaction_rolled_back":false,"autocommit_effects_possible":false}
```

Rows align positionally with `columns`. `affected_rows` is SQLite's change delta including triggers/cascades, not a SELECT count. `completed_statements` may exceed retained result count when output handling fails after native completion. An ordinary engine error such as `SELECT * FROM missing` returns the same envelope with `ok:false`, `results:[]`, `completed_statements:0`, and `error` containing `kind:"sqlite"`, `failed_statement_index:0`, `sqlite_errorcode:1`, and `sqlite_errorname:"SQLITE_ERROR"`; both durability flags are false when nothing executed before it. Error kinds are `request`, `sqlite`, `timeout`, `transaction`, and `rollback`.

BLOB values use `{"$blob_base64":"..."}` in parameters/results; nonfinite SQLite floats use `{"$float":"Infinity"}` (or `-Infinity`/`NaN`) in results. Input JSON must remain standards-compliant. MCP exposes the shared object in `structuredContent` and a compatibility JSON text copy; envelope/copy bytes exceed the executor object's budget.

An `error` has `kind`, bounded `message`, `message_truncated`, zero-based `failed_statement_index` (or null), and SQLite error code/name when available, without intentionally echoing SQL/parameters. Available preceding results remain within the output budget. An unfinished transaction returns `ok:false` with a transaction error after rollback; it cannot silently persist between calls. Errors do not undo prior commits/autocommit effects. A rollback failure requires inspection before reopening. One persistent database remains fixed: nonempty attached paths, `:memory:` attachments, URIs, extensions, and SQL file-access functions are refused. Explicit temporary attachment is allowed only in the literal form `ATTACH '' AS name`. Bound `ATTACH ? AS name` with an empty-string parameter and computed filenames are refused because SQLite's authorizer cannot establish that they name the permitted empty workspace; the tool does not rewrite SQL. SQLite-owned `VACUUM` scratch workspace remains allowed. This boundary validates neither facts, host identity, nor permission to execute incoming SQL.

MCP wraps an execution object in `result.structuredContent`, repeats it as JSON text in `result.content`, and sets `result.isError` to the inverse of its `ok`. Invalid JSON-RPC requests/handshake/tool envelopes instead return a top-level JSON-RPC `error`; they are not SQL execution results. Distinguish that protocol failure from a valid tool response reporting a SQL error.

## Verify the connection

Use the actual configured client to initialize, list the tool, inspect schema with a bounded query, and exercise a controlled read/write/rollback in a synthetic fixture. Check that the selected database is the intended host's and another host is isolated. Record transport evidence and limitations locally. Starting the process or passing a wire harness does not prove a real client's configuration works.

Separately follow [instruction verification](integration.md): test that a fresh ordinary host session loads the full live skill, and that a later session loads an authorized instruction update. MCP startup and tool discovery cannot establish either condition. Report unavailable checks as incomplete; no real host is integrated by this repository's isolated tests.
