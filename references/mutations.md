# Bound graph maintenance

[Command chains](chains.md) apply several mutations in one transaction with `--next`;
later segments see earlier writes and any failure rolls back the entire chain.

Use these commands in an authorized host with a verified connection receipt.
Each command targets one selected record, plus the explicitly limited dependent
closure for delete with `--cascade`; use the selected authorized SQL route for
advanced queries or transactions spanning several records.

Syntax: `[]` marks optional parameters; arguments outside brackets are required.
`(A | B)` requires exactly one choice. Do not type the notation brackets,
parentheses or vertical bar. Omitted update fields retain their existing values.
Every command also accepts `-h` as an alias for `--help`; help exits without writing.

- `CONFIDENCE`: `confirmed`, `inferred`, `uncertain`.
- `VALIDITY`: `current`, `stale`, `superseded`.
- `RESOLUTION`: `resolved`, `unresolved`, `ambiguous`.
- Add defaults: `validity=current`, `layer=knowledge`, `resolution=resolved`
  where supported; omitted nullable fields are SQL NULL.
- Updates change only supplied fields, without add defaults; `updated_at` is
  managed on actual writes.

## add node

```text
evomneme add node --id ID --kind KIND --title TITLE --summary SUMMARY --confidence CONFIDENCE [--validity VALIDITY] [--layer LAYER] [--source_path PATH] [--source_hash HASH] [--line_start N] [--line_end N] [--help]
```

Nullable: `source_path`, `source_hash`, `line_start`, `line_end`.
No `--clear` on add. `--id` is a stable user-supplied ID, unique among nodes
in the bound scope. A missing configured root can be explicitly added using its
configured ID and all required node fields.

## update node

```text
evomneme update node NAME [--kind KIND] [--title TITLE] [--summary SUMMARY] [--confidence CONFIDENCE] [--validity VALIDITY] [--layer LAYER] [--source_path PATH] [--source_hash HASH] [--line_start N] [--line_end N] [--clear FIELD] [--help]
```

`NAME` selects the existing node; its ID cannot change. Omitted fields retain
their values. Repeat `--clear FIELD` for any of `source_path`, `source_hash`,
`line_start`, `line_end`.

## add edge

```text
evomneme add edge SOURCE TARGET --id ID --kind KIND --summary SUMMARY --confidence CONFIDENCE [--validity VALIDITY] [--layer LAYER] [--resolution RESOLUTION] [--source_path PATH] [--source_hash HASH] [--line_start N] [--line_end N] [--help]
```

SOURCE/TARGET are node selectors stored as `source_id`/`target_id`; add has no
`--source_id`/`--target_id` flags. `--id` is a stable user-supplied ID, unique
among edges in the bound scope. Nullable: `source_path`, `source_hash`,
`line_start`, `line_end`. No `--clear` on add.

## update edge

```text
evomneme update edge ID [--source_id SOURCE] [--target_id TARGET] [--kind KIND] [--summary SUMMARY] [--confidence CONFIDENCE] [--validity VALIDITY] [--layer LAYER] [--resolution RESOLUTION] [--source_path PATH] [--source_hash HASH] [--line_start N] [--line_end N] [--clear FIELD] [--help]
```

`ID` is the exact existing edge ID, not a mutable field. Omitted fields retain
their values. SOURCE/TARGET are node selectors. Repeat `--clear FIELD` for any of
`source_path`, `source_hash`, `line_start`, `line_end`.

## add evidence

```text
evomneme add evidence --id ID --description DESCRIPTION (--node_id NODE_ID | --edge_id EDGE_ID) [--validity VALIDITY] [--source_path PATH] [--source_hash HASH] [--help]
```

Exactly one attachment flag is required; the other parent is SQL NULL.
`--id` is a stable user-supplied ID, unique among evidence in the bound scope.
Nullable: `node_id`, `edge_id`, `source_path`, `source_hash`, subject to exactly
one parent. No `--clear` on add. Evidence has no line, confidence, layer or
resolution fields in schema v3.

## update evidence

```text
evomneme update evidence ID [--description DESCRIPTION] [--node_id NODE_ID] [--edge_id EDGE_ID] [--validity VALIDITY] [--source_path PATH] [--source_hash HASH] [--clear FIELD] [--help]
```

`ID` is the exact existing evidence ID, not a mutable field. Omitted fields
retain their values. Neither parent flag is required on update: omitting both
retains the attachment. Setting `--node_id` clears `edge_id` atomically and vice
versa; supplying both fails. Repeat `--clear FIELD` for any of `source_path`,
`source_hash`, `node_id`, `edge_id`. The final row must have exactly one parent;
clearing the only parent without a replacement fails. Evidence has no line,
confidence, layer or resolution fields in schema v3.

## delete node

```text
evomneme delete node NAME [--cascade] [--help]
```

Physically delete the selected node, including historical rows. `NAME` uses the
node selector rules below. Default: RESTRICT if dependent rows exist; the error
lists counts and the explicit `--cascade` option. Cascade deletes only this
scope's incident edges (all parallel edges, each self-loop once), evidence on
the node or those edges, and this node's `symbol_details`/`file_details`, then the
node. It never deletes neighboring nodes or `contains` descendants. The configured
root can never be deleted, including stale roots or with `--cascade`.

## delete edge

```text
evomneme delete edge ID [--cascade] [--help]
```

Physically delete the exact same-scope edge ID, including historical rows.
Default: RESTRICT if attached evidence exists; the error lists counts and
`--cascade`. Cascade deletes only that evidence, then the edge; endpoint nodes
are retained.

## delete evidence

```text
evomneme delete evidence ID [--help]
```

Physically delete only the exact same-scope evidence ID, including historical
rows. No `--cascade` flag. All deletes retain released row/audit history and
owner links, accessible through the existing viewer/activity history; they do
not mark rows stale. Unfamiliar incoming foreign-key dependencies are rejected,
even if their declared cascade would otherwise remove rows automatically.
Success reports actual deleted counts for `evidence`, `edges`, `symbol_details`,
`file_details` and `nodes` in the validated closure, including zero counts.
Delete verification rejects unusually long IDs if released history truncates
their identity; the entire command rolls back. Such IDs may require the selected
authorized SQL route.

## Shared rules

- Flags use schema names with underscores. Quote text for the selected shell;
  use `--field=value` for values beginning with a dash and `--` before positional
  names beginning with a dash. Append `--help` to any selected command for its
  detailed reference.
- `scope_id` comes only from the verified receipt and is immutable. Record `id`
  is required on add, immutable thereafter, and selected positionally on update
  or delete; neither has `--id`. `updated_at` is managed UTC; there is no flag to supply
  or clear it. No database/project/scope override flags exist.
- Node selectors (`NAME`, SOURCE/TARGET) accept exact titles/IDs, `root`, or
  percent-encoded `@scope/id`. Matching includes stale/superseded nodes;
  ambiguity, including title/ID collisions, fails. Use a qualified alias to
  disambiguate. Edge/evidence update/delete IDs and evidence parent IDs are exact IDs,
  including stale/superseded rows; titles, `root` and qualified aliases are not
  interpreted as selectors for them.
- All references must exist in the bound scope. Both final edge endpoints,
  including retained endpoints, are validated even for `unresolved`/`ambiguous`
  resolution. An evidence edge parent must also have both endpoints in scope.
- Required text and supplied kinds/layers must be nonempty. Kinds/layers use the
  host vocabulary. Locators/hashes are recorded literally; no source files are
  read, hashes computed, or truth/confidence/freshness inferred.
- Line values are positive 1-based integers. The final merged row, including
  retained bounds, must have `line_start` whenever `line_end` is set and satisfy
  `line_end >= line_start`. Clear both bounds together when removing a range.
- Nullable clearing uses repeatable `--clear FIELD`, one field per occurrence:
  `--clear line_start --clear line_end`. Empty strings and literal `null` are
  text, not SQL NULL. Unknown/immutable fields, repeated value options, repeated
  clears, set-plus-clear conflicts, empty updates and unchanged patches fail.
- A current configured root cannot become stale/superseded. Preexisting root
  gaps allow maintenance, with a warning if the final root is still missing or
  non-current and ordinary navigation remains unavailable. Explicitly adding
  the missing root or restoring it with `update node root --validity current`
  removes that warning once the final root is current.
- Binding validation, reference resolution, final-row validation, graph write,
  released row history and completed activity metadata share one
  `BEGIN IMMEDIATE` transaction. History setup occurs only after binding
  validation in that transaction; missing released history is installed there.
  Explicitly suspended history remains suspended and blocks the command until
  deliberately resumed. No implicit database/root creation, schema migration
  or private extension is performed. Physical deletion requires an explicit
  delete command with the documented closure; existing SQL executor behavior
  remains unchanged.
- Errors roll back the entire command, print to stderr and return nonzero.
  Add/update success prints the actual row and changed schema fields; delete
  success prints identity and verified per-table counts. All use navigation's
  plain multiline renderer; controls are escaped and blank lines separate result
  elements only. UTF-8 encoding and the 65536-byte complete-output budget are
  checked before commit; failures roll back.

Changes-only examples:

```text
evomneme update node Parser --summary "Rejects invalid input before decoding"
evomneme update node Parser --clear source_hash --clear line_start --clear line_end
evomneme update evidence parser-check --edge_id root-parser
```
