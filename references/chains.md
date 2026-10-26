# Command chains

Separate commands with `--next`; write `evomneme` only once:

```text
evomneme nodes root --next links root --next references src/parser.py
evomneme add node --id parser --kind function --title Parser --summary "Parses input" --confidence confirmed --next add edge root Parser --id root-parser --kind contains --summary "Owns parsing" --confidence confirmed --next update node Parser --summary "Rejects invalid input"
```

Choose one category for the entire chain:

- Reads: `nodes`, `links`, `references` share one read-only SQLite snapshot.
- Mutations: `add`, `update`, `delete` share one `BEGIN IMMEDIATE` transaction.
  Later segments see earlier writes. Any failure rolls back every graph write,
  history installation, row-history entry and activity entry from the chain.

Reads and mutations cannot mix. Setup (`connect`, `install`), help and empty
segments are rejected in chains. Run a selected command's `--help` separately.
All segments are parsed and categories checked before receipt discovery or
database access; type, enum, option or required-argument errors in a later segment
cannot execute an earlier command. State-dependent checks run sequentially inside
the shared transaction. There is no substitution or inferred relationship creation.

## Separator and literal arguments

- Standalone `--next` is a separator only before the first standalone `--`.
  Quoting `"--next"` does not make it literal: shells remove those quotes.
- `--` ends both option and chain-separator parsing for the entire remainder.
  That remainder belongs to the final segment, including any literal `--next`.
  Thus `evomneme nodes -- --next` remains a single read of a node named `--next`.
- Use `--summary=--next` for the literal flag value `--next`.
- A leading-dash positional name can follow `--` only in the final segment.
  Node selectors can instead use a percent-encoded qualified `@scope/id` alias
  in any segment. File paths are exact stored literals: they have no such alias;
  leading-dash paths must be in the final `references` segment after `--`.

```text
evomneme update node Parser --summary=--next --next update node Parser --confidence uncertain
evomneme nodes root --next nodes -- --next
evomneme nodes root --next references -- '-special.py'
```

New returned navigation commands omit unnecessary `--`; a leading-dash node
name stays readable in its card but uses its qualified alias in the returned
command. To combine returned commands, retain `evomneme` (and any shell call
operator) only on the first command, then copy subsequent command words after
`--next`. Previously returned commands containing `--` still work alone or as the
final segment. Ordinary-path references retries omit `--`; leading-dash-path
retries retain it and must be standalone or last.

## Results, limits and failures

- Each result is labeled with its segment number and command. A mutation result
  is its actual stored row or verified deletion counts, not a following read.
  Results describe each step in order; later writes can change an earlier row.
- The aggregate limit is 65536 UTF-8 bytes, including result wrappers. No segment
  reaches stdout until the entire chain succeeds. In a read chain, `--all` on
  any segment removes that aggregate size guard for every segment. Mutation
  chains have no `--all`. Oversized read errors provide a safe whole-chain retry;
  control-bearing arguments require rerunning the original invocation manually.
- One five-second deadline covers the complete chain; `--all` does not extend it.
  Read operations share one snapshot even if another connection commits between
  segments. Binding validation happens once; references can inspect stale/missing
  root maintenance data, while each `nodes`/`links` segment still requires a
  current configured root in that snapshot.
- Every mutation retains the [maintenance safeguards](mutations.md): exact scope,
  changes-only updates, nullable clearing, restricted delete cascades, root
  protection, suspended-history refusal and full delete-identity verification.
  Each mutation segment has its own activity ID in the existing audit history.
- Errors identify the segment and return nonzero with no result output. Rendering,
  encoding, aggregate-budget and deadline checks happen before mutation commit.
  Actual delivery to stdout occurs after commit: a broken pipe or other output
  delivery failure cannot undo an already committed transaction.

Full command parameters remain in [navigation](navigation.md),
[file references](references.md) and [maintenance](mutations.md).
