# Structural and source diagnostics

Use the connected read-only CLI after coherent population or reconciliation:

```text
evomneme check
evomneme check --sources src/parser.py src/session.py
evomneme stats
```

`check` reports database-wide integrity/foreign-key findings and current-scope
current graph structure: weak components, isolated nodes, distinct-neighbor leaves,
nodes with only containment relationships, duplicate endpoint/kind relationships, evidence
coverage and edges without current endpoints. These are review prompts. A leaf can
be legitimate; a connected graph can omit errors, callbacks or runtime wiring.
Read source before adding or removing relationships; no automatic links are created.

Repeatable `--sources PATH [PATH ...]` checks exact stored paths across node, edge
and evidence locators of all validities in the bound scope. It compares SHA256
hashes (plain or `sha256:`), checks node/edge line bounds and reports missing or
oversized sources. It reads at most 16 MiB per source and rejects absolute paths,
traversal and escaping symlinks. It does not find aliases or textual line citations,
prove a declaration's identity, or certify semantic freshness. Use `references PATH`
for targeted reconciliation and inspect textual citations separately.

`stats` reports scope row counts by kind/layer/validity, database-wide graph/history/
activity/other row groups, file bytes/pages/free pages and storage allocation. Where
`dbstat` is available, allocation includes indices; otherwise the output labels a
payload estimate that excludes storage overhead. Do not compare unlike estimates
or infer retrieval usefulness from storage or graph size.

Both commands use a shared five-second read deadline and a complete 64 KiB output
guard; `--all` removes the output guard, not the deadline. Diagnostics inspect data
without repairing it. Preserve errors and incomplete checks in the handoff.
