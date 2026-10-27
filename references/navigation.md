# Graph navigation from the shell

Combine related reads with [command chains](chains.md); ordinary returned commands
omit unnecessary `--`, and leading-dash node names use qualified command arguments.

Use the read-only navigator in an authorized, connected host project. It is separate from the generic SQL executor: ordinary exploration needs names and shell commands, not SQL, JSON requests or per-call database/scope arguments. Connecting EvoMneme itself as a host requires the same explicit user authorization, verified identity, separate project store and Git exclusions as any other project.

## Start with the actual project root

```text
evomneme nodes root
evomneme links root
evomneme nodes 'Chosen responsibility' 'Related decision'
evomneme links 'Chosen responsibility'
evomneme links 'Chosen responsibility' 'Chosen implementation'
```

Copy the names/commands returned by the program; the example names above are placeholders, not mandatory vocabulary. `nodes root` opens a **real stored node** assigned during integration. Its description should explain the project's purpose, boundaries and major responsibilities. It is not a virtual catalog, and neither navigation nor connection setup creates graph data. If the root is absent, non-current or unassigned, the program reports the gap instead of inventing a replacement.

For an unfamiliar task spanning subsystems, read this overview, select responsibilities that explain the task's actions/invariants, inspect their relations, then read selected descriptions, constraints and source evidence. A title need not contain the task's keyword. A known local edit can go straight to its source or named node. Do not turn traversal into a ritual for every change.

## Cards and relationships

`nodes NAME [NAME ...]` returns cards containing `kind`, `title`, `summary`, confidence/current validity, available source locators and evidence, a ready-to-use argument, and **the exact number of relationships that `links NAME` would return in the same snapshot** (`link_count`). It does not list neighbors. Parallel relationships count separately; a self-loop counts once. This is a relationship count, not the number of distinct neighbors.

`links NAME` lists compact relationships, their original directions and copyable neighbor names. `links NAME1 NAME2` returns every relationship between the pair in both directions, including parallel relationships, with the relationships' descriptions, uncertainty, source locators and available evidence. Agents do not need an edge ID to inspect the pair.

Output is multiline plain text with one field per line, without JSON braces, commas or quotation marks around ordinary values. The schema's column names are retained: both nodes and relationships use `kind` and `summary`. On a relationship card, the top-level `summary` and `confidence` belong to the relationship; the neighbor's `argument`, `title`, `summary` and `confidence` are indented under `neighbor`. `argument`, `direction`, `neighbor`, `link_count`, shell commands and envelope/completion fields are navigation metadata, not additional table columns. Pair cards retain `source` and `target` as usable arguments in the original relationship direction.

For example, a relationship card has this structure (illustrative stored values):

```text
direction: outgoing
kind: depends_on
summary: Saving requires the editable value.
confidence: inferred
validity: current
resolution: resolved
neighbor:
  argument: Editable draft
  title: Editable draft
  summary: Retains raw text until confirmation.
  confidence: confirmed
nodes_command: & 'evomneme' 'nodes' 'Editable draft'
```

`locator` groups retain stored `source_path`, `source_hash`, `line_start` and `line_end` fields when available. `evidence` contains indented `-` entries with `description`, `validity` and available locator columns. Empty groups consist only of their field label. Blank lines appear **only between result cards**, and only when the result has multiple cards; header, warnings, nested groups and completion have no blank separators. Multiline scalar values continue with two extra spaces of indentation, including their empty lines, so stored text cannot impersonate another card or the completion marker. Terminal controls and nonprintable characters are shown as Unicode escapes. Returned commands retain necessary shell quoting; names containing line/control characters use a safe ID or percent-encoded qualified argument.

The active graph consists of current nodes and current edges whose endpoints are both current in the same selected scope. Resolution/confidence remain visible; unresolved or ambiguous relationships are not silently promoted to confirmed ones. Stale records do not become active merely because the file is accessible. A node's `current` status is the graph's stored assertion, not a promise that its source has just been reverified.

Available evidence retains its own validity labels, including stale attachments when present. Seeing an attachment on a current card does not promote that attachment to current evidence; inspect its status and verify the source.

Each command resolves names, reads cards/evidence/counts and renders results from one read snapshot. Separate commands can observe intervening maintenance: the count shown on a card describes that card's snapshot, not a lock on the next command. Navigation opens the database read-only, without automatic history installation or graph maintenance.

## Names you can understand and copy

An unambiguous existing title or existing node ID is the normal argument. The program chooses a usable name and supplies shell-quoted commands; it does not create a new persistent slug registry. Titles are not assumed unique. If a title/ID matches different nodes, the command reports ambiguity and supplies qualified alternatives rather than guessing an ID-first or title-first winner.

`root` is a reserved alias for the assigned real root. A stored node actually named `root` can still be addressed explicitly. Technical scope/ID qualification is available for collisions and advanced use; it is not printed as the primary address on every ordinary relationship. A qualified foreign scope never switches the connection automatically.

Shell examples identify their quoting convention. Use the returned argument as one argument, especially for names containing spaces, quotes or leading dashes. Do not paste an unquoted title into a constructed shell command.

## Complete output and unusually large neighborhoods

Ordinary output is complete, with a field-per-line scope/status/shell/count header and a `complete` group repeating the scope and count and stating `source_completeness: not established`. There is no mandatory paging and no hidden SELECT prefix. A high-degree neighborhood or oversized card can exceed the normal stdout budget. In that case the program refuses the oversized response before emitting a misleading partial card/list, explains the counts/reason and provides a ready-to-copy retry using `--all`. The guard measures every UTF-8 output byte, including indentation, separators, header, warnings and completion.

```text
evomneme links --all root > graph.txt
evomneme links --all root | rg 'pattern'
```

`--all` removes the ordinary output-size guard, not errors or execution deadlines. It lets the shell save/filter the complete response. A timeout or read failure is an explicit nonzero failure, never a successful partial result. The program cannot prevent a calling agent tool from truncating its own captured output: check the program's counts/completion marker, and save/read a file when the caller cannot retain the response. Do not treat a pipe as automatic permission to emit unlimited context; agent capture often uses a pipe too.

## One connection receipt, explicit worktree bindings

The excluded host-local connection receipt contains the canonical database/project identity and active scope/root binding. The machine-readable receipt at `.evomneme/connection.json` is the connection record itself, not a second independent source of identity. Setup preserves unrelated receipt fields and refuses incompatible/conflicting bindings. An integrating agent must reconcile an older free-form receipt rather than silently retaining contradictory connection records.

The navigator discovers the receipt from nested working directories. It must not accidentally borrow a parent project's connection across a nested project boundary or accept a receipt copied from an unrelated clone. Every linked worktree gets an explicit local binding to the same canonical host database, with the source scope appropriate for that checkout. Matching remote URLs do not establish shared identity.

A binding across different project/canonical roots must establish actual linked Git worktrees with the same resolved common Git directory. An independent clone or an unverifiable cross-root identity is rejected; this is separate from an ordinary freshness warning. A single-root non-Git project remains supported with its verification limitations stated.

An invalid database/schema, nonexistent scope, wrong project/worktree binding or mismatched recorded identity is an error. Local edits or a different source checkpoint can make knowledge stale during normal development: these produce a visible warning/status and keep reading available. Reconcile before trusting/passing affected claims, following [maintenance checkpoints](code-graph.md#file-wide-locator-reconciliation). Do not choose the newest scope automatically or label all current claims freshly verified. Where persistent store identity or source checks are unavailable, that verification limitation must remain visible.

## Bootstrap and integration

Use an existing Python runtime and the trusted tool checkout once to bootstrap command availability and connect a host. Normal `nodes`/`links` calls then need neither interpreter nor script/store paths. This setup is part of authorized integration; it does not authorize installing runtimes or modifying unrelated projects.

The launcher installer supports two explicit choices: install the tool's own launcher into an existing accessible command directory, or generate a project-local activation that the user/environment deliberately invokes. It does not silently edit global PATH, profiles or registry. Launchers bind the selected existing Python and live tool path; moving either requires explicit repair. A launcher being present does not prove a fresh shell can find it: verify the actual shell and nested project invocation. If no command directory or chosen activation is available, command setup remains incomplete.

Illustrative bootstrap commands (replace paths and verified identifiers; the initial interpreter invocation happens only during setup):

```text
python /trusted/EvoMneme/scripts/evomneme_cli.py install --bin-dir /existing/command/directory
evomneme connect /host/.evomneme/knowledge.sqlite3 --project /host --scope verified-scope --root existing-root-id
```

Alternatively, run `install --activate /host/.evomneme/bin` from the host root and invoke the printed activation command deliberately. This affects only that shell's environment. Use setup's `--canonical-root` when explicitly connecting a linked worktree to its shared host; do not use it to join unrelated clones. Unknown receipt fields are retained. A non-JSON manual receipt or conflicting/unsupported version is refused and must be reconciled explicitly by the integrating agent, preserving useful prior conventions and evidence. Neither setup nor the navigator silently overwrites such records.

Windows uses a PowerShell `.ps1` launcher with private UTF-8 argument transport to the existing Python process, avoiding CMD expansion and loss of literal quotes. This transport is internal; ordinary calls still use meaningful node names. The launcher does not change execution policy. If the current policy blocks local scripts, report command setup incomplete and agree a permitted setup route; do not bypass or downgrade the policy. POSIX uses its executable wrapper. Verify actual pipelines, returned commands, Unicode and exit codes on the supported shell rather than inferring support from static launcher text.

Connection setup selects an existing v3 store, an explicit source scope and an existing real root. It changes only the receipt, never the selected database. Creating or selecting a meaningful root and evidenced direct architecture relationships is authorized integration/maintenance work using the existing graph model, not a side effect of a read command. Keep the root's description and links reconciled; a root with missing links does not prove architectural completeness. Never populate root-to-everything edges solely to make a traversal look complete.

See `evomneme --help`, `evomneme nodes --help`, `evomneme links --help` and setup-command help for actual arguments. Use [integration verification](integration.md) for instruction loading, exclusions, identity and future worktrees. SQL transports remain available for graph maintenance and advanced queries; neither SQL authoring nor schema discovery is required for each ordinary navigation call. Honor deliberately selected transports and stop/report a failed configured integration instead of silently changing routes.

Development checks and the limits of the isolated fresh-agent observation are recorded separately in [navigation validation](navigation-evaluation.md); normal exploration does not require reading that evaluation history.
