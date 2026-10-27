# Task retrieval and context handoff

Use in an authorized host, including authorized self-hosting with the same identity and storage isolation requirements. The goal is enough verified context to make a change safely. Ordinary graph exploration uses the [name-based navigation CLI](navigation.md): `nodes root` → `links root` → selected `nodes`/`links` → source evidence. The real root supplies project context and cards show exact link counts without expanding neighbors. A known method or small local task can use direct source inspection. The SQL recipes below remain an advanced or deliberately chosen SQL route and document the underlying v3 graph; they are not necessary for ordinary CLI navigation and must not silently bypass a failed configured integration.

## Establish context once

Reuse the connection receipt and a trustworthy session handoff: authorized database/transport, installed tool revision, verified schema version, source scope and known local changes. If compatibility has not been verified, follow [schema verification](schema.md#initialization-and-compatibility). Do not repeatedly dump DDL in every subagent, or guess aliases from another graph system.

Select scope by source correspondence, not the newest-looking ID. If the receipt/packet does not establish one, use [scopes.sql](../queries/scopes.sql) to list bounded pages of branch, worktree, revision and inspected snapshot. Compare them with the actual checkout and local edits. If no scope matches, say which claims need source verification; do not silently combine historical scopes or start a host rebuild. Once verified, pass the chosen scope and schema contract onward instead of repeating this discovery.

The fields needed for ordinary retrieval are:

| Object | Fields and meaning |
| --- | --- |
| Node | `(scope_id,id)`, `title`, `kind`, `summary`, `confidence`, `validity`, `source_path`, `source_hash`, `line_start`, `line_end` |
| Edge | Same scope and claim fields, plus `source_id`, `target_id`, `kind`, `resolution`; direction has meaning |
| Symbol detail | `(scope_id,node_id)`, `qualified_name`, `signature`, `language` |
| Evidence | `(scope_id,id)`, exactly one of `node_id` / `edge_id`, `description`, `source_path`, `source_hash`, `validity` |

`name`, `scope`, `locator` and `stable_id` are not v3 node columns. A title is not a globally unique identity. Always join on scope as well as ID. Current validity is an observation, not proof of freshness in this checkout. Compare revision, worktree/local edits and relevant sources before relying on a claim. An empty new-scope lookup may require verifying useful older observations; do not automatically promote them.

## Orient by responsibility, then follow and verify

1. Express the unfamiliar task as **entities, actions and invariants**, without assuming their stored names. For example, changing a parcel reference only on confirmation while preserving unfinished input and reliable retries concerns a local commit boundary, draft lifetime and delivery guarantees. Searching every declaration for `reference` would not establish those mechanisms.
2. Read [architecture.sql](../queries/architecture.sql) with the host's established architectural kind (normally `architecture`). It selects **one knowledge type**, without a word or source-path predicate. Begin with 12 cards and 120 summary characters per card, `max_rows:12`, `max_output_bytes:8192`. Cards carry title, responsibility preview, confidence and an explicit truncation flag. Use your own understanding to select responsibilities that explain the actions/invariants, even when their titles share no words with the task. Degree is not relevance. The first page is not a ranked top list: ID order is only for stable paging.
3. Fetch [node.sql](../queries/node.sql) for one or two plausible responsibilities before deciding. A clipped preview is not the full contract. Inspect at most two catalog pages initially; if they do not locate the mechanism, deliberately continue bounded pages or revisit the host's kind vocabulary. Do not substitute a global nodes substring scan. Record incomplete catalog coverage; absence from a partial catalog proves nothing. If the catalog is empty or its reviewed responsibilities do not cover the task, report that architectural knowledge gap and use focused source discovery. Do not invent a responsibility or require rebuilding the graph.
4. Use [incident.sql](../queries/incident.sql) on the chosen responsibility to read direct **incoming and outgoing** relationships. Select implementation links, decisions/constraints and direct component interactions by their explanations. A code node may implement an architecture node via an incoming edge, and a pathless decision may constrain it. Read selected decision details and evidence. Follow only the next implementation/boundary needed to answer an open question, such as a call from a local sender to a server command handler. Use observed host vocabulary rather than assuming every relationship is called `calls`.
5. Only after choosing the mechanism, use physical source locators or [declarations.sql](../queries/declarations.sql) to inspect relevant code in a file. A physical path filter excludes pathless knowledge by design; it must not define the architectural catalog. Cross-module responsibilities are connected to their implementation through edges, not by pretending that every pathless node belongs to every directory. For a known local edit, [anchors.sql](../queries/anchors.sql) can skip the catalog: exact IDs/titles find selected symbols, while exact source paths return file/module entrypoints; listing all declarations requires the explicit file recipe.
6. Fetch evidence for consequential claims and read the actual implementation, tests and material boundaries. Compare locators/hashes with sources. Current graph validity is not a fresh source check; missing edges do not establish independence. Stop when you have a source-backed mechanism map, important constraints and explicit open questions. A small graph can still be incomplete. Preserve uncertainty rather than expanding unrelated containment trees until output looks complete.

This is semantic selection **by the agent from bounded architectural context**, not automatic semantic search. It supplies the missing opportunity to recognize a differently named responsibility. Success depends on the quality and coverage of that context and on the agent's reasoning; test those separately from SQL correctness.

### Executable recipes

Read a recipe once and send its complete text as the `sql` string to the selected Python `Executor.execute_sql`, with the documented bound parameters. For CLI, `--sql-file` accepts that same one-statement file with `--params` JSON; prefer a request file if shell quoting is cumbersome. These are editable agent-authored SQL recipes, not new executor commands. The existing [SQL contract](sql.md#shared-sql-contract) governs all results and budgets.

| Recipe | Bound parameters | Use |
| --- | --- | --- |
| [scopes.sql](../queries/scopes.sql) | `after_id` (null initially), `limit` (integer 1–32) | Source scope candidates; select by verified checkout correspondence, never automatically by age/order. |
| [architecture.sql](../queries/architecture.sql) | `scope`, `kind` (normally `architecture`), `after_id`, `limit` (integer 1–32), `preview_chars` (integer 0–240) | Current knowledge cards of one architectural type; no keyword/path filtering. |
| [node.sql](../queries/node.sql) | `scope`, `id` | Full current selected node, with confidence and source locators. |
| [anchors.sql](../queries/anchors.sql) | `scope`, `query`, `mode` (`exact` or `prefix`), `path_prefix` (null for any), `after_id`, `limit` | Literal ID/title or title prefix; exact source paths match file/module entrypoints. A physical path filter excludes NULL paths. |
| [declarations.sql](../queries/declarations.sql) | `scope`, `source_path`, `kind` (null for all), `after_id`, `limit` | Deliberate current code declarations in one exact source file, optionally of one type. |
| [incident.sql](../queries/incident.sql) | `scope`, `root`, `edge_kind` (null for all), `after_id`, `limit` | Current resolved incident edges with current root/neighbor, original direction, relationship explanation and neighbor context. |
| [evidence.sql](../queries/evidence.sql) | `scope`, `target_type` (`node` or `edge`), `target`, `after_id`, `limit` | Current provenance for one selected current node or edge. |

An initial catalog request binds `{"scope":"verified-scope","kind":"architecture","after_id":null,"limit":12,"preview_chars":120}`. Do not add a `VIN`/`reference` predicate or `client/` path to this stage. Use the IDs returned in the catalog for full details and incident roots; they are not expected to be known beforehand. If the host uses a different architectural kind, consult its established vocabulary in the receipt and select that type deliberately; do not mix thousands of code entities into this initial view. Decisions/findings are selected through relevant relationships after choosing architecture. An unlinked decision may require a separate, bounded review of its knowledge type when a concrete question justifies it; do not imply that incident traversal covers unlinked records.

For a known source anchor, parameters may be `{"scope":"verified-scope","query":"Session.commit","mode":"exact","path_prefix":"src/session/","after_id":null,"limit":8}`. Pass JSON null for unused filters, not the string `"null"`. Matching is case-sensitive and literal, without wildcard interpretation of `%` or `_`. A path prefix is literal text; include a trailing slash for a directory boundary. An empty query yields no anchors. Exact paths no longer enumerate every declaration implicitly: use `declarations.sql` with the path and optional kind for that explicit operation. ID/title matches and exact/prefix modes otherwise retain their prior behavior.

Paged recipes order by ID and request `limit+1` rows internally. Set executor `max_rows` equal to `limit` so the extra row produces `has_more` when another page exists. Resume with the last ID actually delivered (`id`, `edge_id`, or `evidence_id`); keep all other parameters unchanged. Smaller byte budgets may end the page sooner. If no row fits, reduce the catalog preview or use a larger valid budget; retrying the same empty page cannot advance. Titles and selected full details are not clipped by the catalog's preview limit, so output budgets still matter. Concurrent graph edits can change page membership; paging does not provide a snapshot across calls. `node.sql` returns at most one selected node and needs no cursor. For a stable comparison use an isolated unchanged fixture. Incident retrieval omits unresolved/ambiguous edges; investigate their uncertainty separately when relevant. Evidence retrieval checks the target's current validity, but for an edge does not certify resolution or endpoint validity. Returned evidence is a claim to verify, not a freshness guarantee.

Keep calls small (for example `max_rows: 8`, `max_output_bytes: 8192`, `timeout_ms: 1000`) and adapt them to actual summary lengths. A SQL `LIMIT` can hide further matches from the executor: `has_more:false` alone is not a completeness claim. Recipe pagination and executor truncation are different boundaries. Output limits do not bound SQLite query work; exact/prefix matching can still scan within the selected scope. Narrow scope/path/kind and respect timeouts rather than installing a host-only index.

The existing [neighborhood.sql](../queries/neighborhood.sql) remains available for bounded multi-hop reachability when that is the question. It returns minimum node depth, not a path explanation. Its output limit does not bound intermediate traversal; start with small depth and avoid indiscriminate expansion of hubs. Use incident edges when you need to know why a neighbor matters.

## Preserve behavior at a changed boundary

Before replacing a library/framework component or bypassing an established wrapper, identify the unmet requirement. Check whether existing configuration already supplies it. Inspect or probe the directly used boundary when its inherited behavior matters: validation, coercion, encoding, errors, defaults, transaction or retry semantics. Compare old and proposed behavior on relevant accepted and rejected inputs; testing only the desired new case misses guarantees silently removed by a replacement. Keep this investigation proportional to the change; no dependency-tree indexing is needed.

If knowledge is missing, record the verified boundary contract and its provenance on the existing entity and meaningful relationships. Distinguish an observed failure, a hypothesis about its cause and a design decision. A new implementation's comment is not evidence that the previous implementation was inadequate. Reviewers should receive that distinction and the unresolved boundary checks, rather than only the author's explanation.

## Hand off a small, reusable packet

Supply only what a recipient needs for its assignment. A useful packet contains:

- Authorized store/transport, tool/schema revision and known parent activity identities; do not include secrets or invent unknown IDs.
- Scope ID plus the verified source revision/worktree and local changes. The recipient checks compatibility with its own checkout before reusing claims.
- Catalog kind, pages actually reviewed and cursor if incomplete; selected responsibilities and why their mechanisms match the task. Pass the known query parameters/field card, rather than making each recipient rediscover the schema or semantic entrypoint.
- A few selected node/edge IDs, exact locators and concise established contracts, with evidence references and confidence. Include the reason for a dependency, not just a list of files.
- Remaining questions, missing edges, stale observations and material external guarantees requiring verification; separate facts from proposed explanations.
- File ownership, permitted maintenance and the changed-source delta. Reuse discovered columns and query parameters instead of forwarding whole DDL, SQL transcripts or repeated file dumps.

Before handing off affected context, apply the [write checkpoints and file-wide locator reconciliation](code-graph.md#file-wide-locator-reconciliation): a line insertion can displace unrelated entities in the same file. Persist discoveries and reconcile changes first, or explicitly identify dirty/unverified references and pending maintenance when work is incomplete or writes are blocked. Never pass knowingly outdated line numbers as current.

This packet does not replace loading the live skill or authorize a new integration. When the recipient discovers a mismatch, reverify the affected context, including displaced references in changed files. For substantial maintenance, send changed files/entities and the observed semantic changes, not the whole exploration history. Reconcile changed declarations, direct relationships, contracts and evidence together; a small patch can alter a class's behavior without changing its declaration line. Record unfinished analysis on the existing owner/file. Do not spend more on routine graph bookkeeping than the task warrants.

## Check usefulness without assuming it

Use isolated fixtures and record relevant contracts, missing knowledge, all necessary calls/output, instruction and source-reading costs. Good SQL and a completed graph walk do not establish a correct code change or lower total cost. Preserve the first result, errors and uncertainty; label clarifications or reruns separately. Keep private host data out of reusable fixtures and reports.

See [retrieval evaluation](retrieval-evaluation.md) for reproducible checks, lexical ablation, a fresh-agent orientation observation and its limits. Evaluation history is optional reading, not required context for ordinary retrieval.
