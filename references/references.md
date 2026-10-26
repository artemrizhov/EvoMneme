# Saved source-file references

Combine with navigation through [command chains](chains.md) to share one snapshot.
Leading-dash literal paths require `--` in the final segment; `--all` on any read
segment opts out of the whole chain's size guard while keeping its deadline.

```text
evomneme references PATH [PATH ...] [--all]
```

Run in an authorized connected host before reconciling changed files. Arguments are exact stored `source_path` strings: no filesystem access, path resolution, slash/case normalization or alias expansion. Multiple paths form a deduplicated union in the receipt's selected scope. Use `--` before paths beginning with a dash.

The result includes all stored validity states, grouped as direct nodes, edges and evidence whose **own** `source_path` matches; additional edges incident to directly matched `kind: file` nodes; and additional evidence owners/edge endpoints for context. Every row appears once; overlapping roles are explicit reasons. Dependency edges do not establish that their own locator belongs to the selected file. Owner context retains its own locator and validity, does not fan out recursively, and identifies missing owners/endpoints explicitly. Evidence has no line columns; an owner's lines are not evidence lines. Node file/symbol details are included when present.

Counts distinguish direct references from additional dependencies/context. The report preserves source freshness warnings and remains usable when the configured root node is stale or missing, with an explicit warning. Wrong scope, schema or binding still fails. All queries and owner context use one read-only snapshot, without activity/history writes or history installation.

Coverage is limited to structured literal matches. Arbitrary text citations, file-text mentions, aliases and paths stored with different spelling are not searched. Zero matches do not prove absence of source code or other references. Verify source and reconcile the affected saved claims explicitly.

Output uses the navigator's safe plain-text fields, with blank lines only between result elements. The 64 KiB guard measures the complete UTF-8 output before stdout; oversized reports fail with an installed-command retry using `--all`. That option removes the size guard while retaining the five-second deadline, snapshot and errors. There are no silent row limits or successful partial reports.

For control-bearing path arguments, the size error instructs you to repeat the original invocation with `--all` and preserves the original arguments rather than printing a potentially unsafe shell literal. The report itself displays those characters safely as escaped/indented fields.

```text
evomneme references src/model.py src/service.py
evomneme references --all -- '-special.py' > references.txt
```

See [connection and navigation](navigation.md) for the existing project receipt and shell launcher setup. Do not connect the EvoMneme repository itself as a host; isolated synthetic development fixtures are permitted.
