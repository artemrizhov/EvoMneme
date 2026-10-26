# Task retrieval and context handoff

Use in an authorized host, never as a live knowledge workflow for EvoMneme itself. The goal is enough verified context to make a change safely. SQL is optional when a known source location or ordinary search answers the question more directly. These recipes use the released v3 graph and the existing SQL transport; they add no schema, retrieval service or automatic ranking model.

## Establish context once

Reuse the connection receipt and a trustworthy session handoff: authorized database/transport, installed tool revision, verified schema version, source scope and known local changes. If compatibility has not been verified, follow [schema verification](schema.md#initialization-and-compatibility). Do not repeatedly dump DDL in every subagent, or guess aliases from another graph system.

The fields needed for ordinary retrieval are:

| Object | Fields and meaning |
| --- | --- |
| Node | `(scope_id,id)`, `title`, `kind`, `summary`, `confidence`, `validity`, `source_path`, `source_hash`, `line_start`, `line_end` |
| Edge | Same scope and claim fields, plus `source_id`, `target_id`, `kind`, `resolution`; direction has meaning |
| Symbol detail | `(scope_id,node_id)`, `qualified_name`, `signature`, `language` |
| Evidence | `(scope_id,id)`, exactly one of `node_id` / `edge_id`, `description`, `source_path`, `source_hash`, `validity` |

`name`, `scope`, `locator` and `stable_id` are not v3 node columns. A title is not a globally unique identity. Always join on scope as well as ID. Current validity is an observation, not proof of freshness in this checkout. Compare revision, worktree/local edits and relevant sources before relying on a claim. An empty new-scope lookup may require verifying useful older observations; do not automatically promote them.

## Select, follow, verify

1. Start with the task's actual identifier, public operation, source path or architectural responsibility. Choose a small number of candidate anchors, with an owner/path boundary when known. Prefer literal exact matches, then a narrow title prefix. A short substring can match unrelated words in both SQL and ordinary file search. Do not rank by degree: a widely used helper is not necessarily the task's entry point.
2. Inspect the candidate's responsibility and confidence. Choose a few IDs, then inspect direct incoming and outgoing relationships: callers/consumers, immediate ownership, constraints, implementation links, dependencies and relevant tests. Use the host's observed edge vocabulary and direction. Expand only a relationship that answers a remaining question, often one further hop from a representative implementation or architectural concept. Do not traverse every containment descendant or require an edge visit for a known file edit.
3. Fetch provenance or supported detail attributes for the claims that matter. Read the actual affected implementation, its relevant tests and material boundaries. Summaries and edges orient inspection; they do not certify a change. A missing relationship does not establish independence. If anchors or meaningful edges are absent, state the gap and use focused source search/reading; reconcile only what the task establishes.
4. Stop expanding when the remaining work has concrete source locations, the important dependencies/invariants have evidence, and open questions are explicit. If output is truncated or mostly irrelevant, narrow the query or page deliberately before adding more queries. Do not load an entire subsystem to make a small result look complete.

### Executable recipes

Read a recipe once and send its complete text as the `sql` string to the configured `execute_sql`, with the documented bound parameters. For CLI, `--sql-file` accepts that same one-statement file with `--params` JSON; prefer a request file if shell quoting is cumbersome. MCP cannot open a query path on the caller's behalf. These are editable agent-authored SQL recipes, not new executor commands. The existing [SQL contract](mcp.md#shared-sql-contract) governs all results and budgets.

| Recipe | Bound parameters | Use |
| --- | --- | --- |
| [anchors.sql](../queries/anchors.sql) | `scope`, `query`, `mode` (`exact` or `prefix`), `path_prefix` (null for any), `after_id` (null initially), `limit` (positive integer) | Exact literal ID/title/source path, or literal title prefix; current nodes in one scope, optionally within a literal source-path prefix. |
| [incident.sql](../queries/incident.sql) | `scope`, `root`, `edge_kind` (null for all), `after_id`, `limit` | Current resolved incident edges with current root/neighbor, original direction, relationship explanation and neighbor context. |
| [evidence.sql](../queries/evidence.sql) | `scope`, `target_type` (`node` or `edge`), `target`, `after_id`, `limit` | Current provenance for one selected current node or edge. |

For example, anchor parameters may be `{"scope":"verified-scope","query":"Session.commit","mode":"exact","path_prefix":"src/session/","after_id":null,"limit":8}`. Pass JSON null for an unused filter, not the string `"null"`. Use the returned ID as an incident `root`, then select the claim whose evidence is needed. Exact mode and prefix mode are separate choices, so an exact hit cannot silently broaden into unrelated prefixes. Matching is case-sensitive and literal, without wildcard interpretation of `%` or `_`. A path prefix is literal text; include a trailing slash for a directory boundary. An empty query yields no anchors. Natural-language wording different from the stored title can miss useful concepts; use known responsibility names or focused source discovery rather than assuming absence.

All recipes order by ID and request `limit+1` rows internally. Set executor `max_rows` equal to `limit` so the extra row produces `has_more` when another page exists. Resume with the last ID actually delivered (`id`, `edge_id`, or `evidence_id`); keep all other parameters unchanged. Smaller byte budgets may end the page sooner. If no row fits, narrow the projection or use a larger valid budget; retrying the same empty page cannot advance. Concurrent graph edits can change page membership, so paging does not provide a snapshot across calls. For a stable comparison use an isolated unchanged fixture. Incident retrieval omits unresolved/ambiguous edges; investigate their uncertainty separately when relevant. Evidence retrieval checks the target's current validity, but for an edge does not certify resolution or endpoint validity. Returned evidence is a claim to verify, not a freshness guarantee.

Keep calls small (for example `max_rows: 8`, `max_output_bytes: 8192`, `timeout_ms: 1000`) and adapt them to actual summary lengths. A SQL `LIMIT` can hide further matches from the executor: `has_more:false` alone is not a completeness claim. Recipe pagination and executor truncation are different boundaries. Output limits do not bound SQLite query work; exact/prefix matching can still scan within the selected scope. Narrow scope/path/kind and respect timeouts rather than installing a host-only index.

The existing [neighborhood.sql](../queries/neighborhood.sql) remains available for bounded multi-hop reachability when that is the question. It returns minimum node depth, not a path explanation. Its output limit does not bound intermediate traversal; start with small depth and avoid indiscriminate expansion of hubs. Use incident edges when you need to know why a neighbor matters.

## Preserve behavior at a changed boundary

Before replacing a library/framework component or bypassing an established wrapper, identify the unmet requirement. Check whether existing configuration already supplies it. Inspect or probe the directly used boundary when its inherited behavior matters: validation, coercion, encoding, errors, defaults, transaction or retry semantics. Compare old and proposed behavior on relevant accepted and rejected inputs; testing only the desired new case misses guarantees silently removed by a replacement. Keep this investigation proportional to the change; no dependency-tree indexing is needed.

If knowledge is missing, record the verified boundary contract and its provenance on the existing entity and meaningful relationships. Distinguish an observed failure, a hypothesis about its cause and a design decision. A new implementation's comment is not evidence that the previous implementation was inadequate. Reviewers should receive that distinction and the unresolved boundary checks, rather than only the author's explanation.

## Hand off a small, reusable packet

Supply only what a recipient needs for its assignment. A useful packet contains:

- Authorized store/transport, tool/schema revision and known parent activity identities; do not include secrets or invent unknown IDs.
- Scope ID plus the verified source revision/worktree and local changes. The recipient checks compatibility with its own checkout before reusing claims.
- A few selected node/edge IDs, exact locators and concise established contracts, with evidence references and confidence. Include the reason for a dependency, not just a list of files.
- Remaining questions, missing edges, stale observations and material external guarantees requiring verification; separate facts from proposed explanations.
- File ownership, permitted maintenance and the changed-source delta. Reuse discovered columns and query parameters instead of forwarding whole DDL, SQL transcripts or repeated file dumps.

This packet does not replace loading the live skill or authorize a new integration. When the recipient discovers a mismatch, reverify only the affected context. For substantial maintenance, send changed files/entities and the observed semantic changes, not the whole exploration history. Reconcile changed declarations, direct relationships, contracts and evidence together; a small patch can alter a class's behavior without changing its declaration line. Record unfinished analysis on the existing owner/file. Do not spend more on routine graph bookkeeping than the task warrants.

## Evaluate changes honestly

Use isolated, self-contained fixtures with expected relevant entities and contracts defined in advance. Compare the same task terms, scope, source snapshot and output budgets. Count irrelevant hits, dependency/invariant coverage, complete serialized SQL-result bytes, calls and schema errors, including every expansion/evidence response. If one route reads more claims, report that extra cost rather than comparing only its first response. A fixture with missing edges must remain explicitly incomplete.

Deterministic recipe tests establish SQL behavior and synthetic context composition. They do not show that a fresh agent chooses good anchors, follows the procedure, preserves application correctness, or saves tokens/time. Those require matched fresh-session evaluations with the same task, models, delegation and stopping rules. Keep private host code, paths, databases and logs out of public fixtures and reports.

Reproduce the isolated checks with `python -m unittest discover -s tests -p test_retrieval.py` and the comparison with `python tests/test_retrieval.py --compare`. The comparison intentionally puts twelve substring distractors before an exact relevant title in deterministic ID order. Both routes receive the same task term and scope, project the same anchor columns and use `max_rows=8` / `max_output_bytes=12000`. The baseline uses a broad substring lookup; the new route selects the exact title, inspects incident edges and requests selected evidence. Required IDs are defined by the fixture, without giving the new route an oracle seed ID. This measures a failure mode, not a representative workload or comparison against a well-chosen exact file search.

| Synthetic term | Irrelevant seed hits, substring → exact | Required entities found, substring → expanded | Result bytes, substring → all new calls | Calls |
| --- | --- | --- | --- | --- |
| billing | 8 → 0 | 0/2 → 2/2 | 1370 → 1674 | 1 → 3 |
| session | 8 → 0 | 0/2 → 2/2 | 1378 → 1674 | 1 → 3 |
| policy, missing edge | 8 → 0 | 0/2 → 1/2 | 1386 → 1001 | 1 → 2 |

Bytes count compact UTF-8 shared result objects for every call, including empty/evidence responses. Requests, instructions and MCP wrapper duplication are excluded; this is not the model-facing context or a token estimate. The first two scenarios improve coverage while increasing bytes and calls. The missing-edge case remains incomplete. Recipe tests also cover natural-language anchor misses, cross-scope ID collisions, validity, literal wildcards, confidence, direction, self-loops and pagination under output truncation. No real host data is used.

The comparator also includes a reasonable exact lexical lookup (`title=:query`) with the same scope, columns and budgets. Its returned rows and bytes equal anchor-only retrieval in every scenario. This separates predicate selection from the extra information supplied by relationships:

| Synthetic term | Exact lexical = anchor-only | Anchor + hop | Anchor + hop + selected evidence |
| --- | --- | --- | --- |
| billing / session | 424 bytes, 1 call, 1/2 required | 1283 bytes, 2 calls, 2/2 | 1674 bytes, 3 calls, 2/2 |
| policy, missing edge | 422 bytes, 1 call, 1/2 | 1001 bytes, 2 calls, 1/2 | 1001 bytes, 2 calls, 1/2 |

Good lexical predicates account for the removal of distractors. The hop exposes a stored decision whose title does not match the task term, at additional cost; evidence adds provenance rather than another required entity. These fixtures do not compare the total effort to reach equally sufficient context through good source search versus graph navigation. The recipes help after a useful anchor is formulated or supplied; they do not solve semantic discovery of differently worded architecture concepts.
