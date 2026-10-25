# Full code graph: coverage and maintenance

Use this procedure for initial construction, expansion of an existing architecture-only store, continuation of incomplete coverage, and structural reconciliation. It applies within an authorized host; it does not activate EvoMneme in its own repository. The agent owns analysis and SQL within the [controlled schema](schema.md). No external analyzer or separate indexing service is required.

## Establish the source boundary

Inventory the host's sources independently of the database. Include all project-owned packages, modules, declarations, tests, scripts, and code-bearing configuration, including private, nested, and currently unused code. Account for uncommitted and new files as well as tracked sources. Do not assume a Git-tracked file list alone is complete or traverse dependency/build directories indiscriminately.

Record the host/version/worktree and inspected content identities, included roots, and explicit exclusions with reasons. Secrets, knowledge-store files, third-party dependency trees, and disposable build outputs are outside the normal source inventory. For generated code, record its generator/source and boundary references; record any excluded generated output explicitly. Do not exclude project-owned code just because it is large, unfamiliar, ignored by Git, or irrelevant to the current feature. Honor a user's narrower scope and describe resulting coverage within that scope. Inaccessible or unsupported project sources are coverage gaps, not successful exclusions.

## Represent declarations and relationships

For every in-scope file, record its role and declarations as `nodes`: modules/namespaces, classes/interfaces/types, functions/methods/constructors, fields/properties/constants, and equivalent language structures. Include nested declarations and distinguish overloads, accessors, and same-named symbols in different owners. Use identities qualified by source and owner, plus a language-appropriate disambiguator; line numbers alone are not identities. Store qualified names/signatures/language in `symbol_details`; common responsibilities and source locations stay on the node. Distinguish declared members from inherited members reachable through inheritance.

Store every relationship in the shared `edges` table, rather than burying names in summaries or introducing separate code adjacency tables:

- Ownership/containment, imports/exports/re-exports, inheritance, and interface implementation.
- Calls and symbol references, reads/writes and data dependencies where represented in the source.
- Configuration, registrations, events, callbacks, dependency injection, and other indirect/runtime connections.

Review these categories throughout the source inventory, not just in selected subsystems. Preserve direction, relationship kind, and evidence locations; multiple occurrences may share an edge if their evidence remains available. Represent external dependencies as boundary entities without indexing their implementation. Separate resolved edges from inferred candidate targets and unresolved references. For a dynamic target that cannot be established, retain the originating symbol/location, what is known, and the missing evidence as queryable unresolved work. Do not invent a resolved call edge or silently omit the site. An unresolved edge is not evidence that no dependency exists.

Architecture, contracts, decisions, and findings link to the structural graph. Preserve existing useful records when expanding a summary-only store. Do not copy implementation bodies or turn every expression into a prose record; compact locators and relationships provide navigation back to source.

## Build and demonstrate coverage

Keep source inventory as file `nodes` and coverage state in `file_details`, connected to declarations through `declared_in` edges. Track each file's inspected content identity, declaration coverage, relationship categories reviewed, unresolved sites, and remaining work. Record category review/gaps in `remaining_work` and unresolved sites as graph nodes/edges; do not create private coverage tables. Distinguish pending, partial, verified, stale, and blocked work, with reasons. A file with no declarations still needs a recorded inspection outcome. Keep explicit exclusions visible alongside coverage, rather than counting them as inspected code. Additional structured coverage fields require a published schema/viewer change.

Build in bounded, resumable batches. Prioritize the current development area without dropping the rest of the inventory; save the next pending work and resume it in subsequent active sessions without another user request. Do not block every small task on a full rebuild or repeatedly rescan unchanged implementation bodies. A dedicated maintenance subagent may help under the skill's delegation and ownership rules. If time, access, or available tooling prevents completion, preserve the gap and report partial coverage, not a finished graph.

Before claiming structural completeness for a source snapshot:

1. Reconcile the independently obtained file inventory against coverage state: every included file is accounted for; no pending, blocked, or stale files are hidden.
2. Compare declarations observed in each file with stored identities, owners, kinds, and locators. Check for omissions, duplicate identities, and stale/deleted declarations. Use existing environment facilities and source inspection; do not derive the expected declaration list solely from the graph itself.
3. Verify containment and source evidence, and review the relationship categories for every file. Record unresolved semantic/runtime relationships separately; complete declaration coverage does not establish a complete resolved call/data-flow graph.
4. Exercise retrieval by qualified symbol, owner/member listing, and incoming/outgoing relationships. Follow source evidence for sampled results. These checks assess navigability and correctness, not exhaustive coverage by themselves.
5. Recheck the source snapshot before recording the result. Changes during analysis leave affected coverage stale until reconciled.

Report the inspected scope/version, files and declarations accounted for, exclusions, pending/stale/blocked work, relationship review coverage, and unresolved targets. Use coverage ratios only when the denominator was established from sources. If the expected symbol total is not established, say so. SQL success, foreign-key integrity, hashes, and total records/edges/evidence are not proof of completeness. Never describe the entire graph as fully resolved while known relationship gaps remain.

## Keep the graph current

At session start, compare the current source inventory and content identities with the last verified state, including local edits and changes made by other agents. Reuse prior observations only after confirming their applicability to the current scope; a new commit or branch does not validate old knowledge automatically.

For additions and edits, reconcile the file's full declaration set and relationships, not only the lines touched by the task. For renames/moves, reconcile symbol identities, containment, and references; for deletions, remove or invalidate current declarations, incident edges, and evidence while retaining useful version-scoped history. Recheck incoming dependents, exports, inheritance, and runtime registration sites affected by a changed symbol or contract. Unchanged caller text does not guarantee an unchanged target. Mark unverified dependents and their coverage stale.

Commit coherent graph, evidence, and coverage updates in an explicit transaction, after rechecking source identity. Do not mark a batch verified when its declarations were written but its relationship review is still pending. Concurrent agents must coordinate ownership of overlapping source areas; database locks alone do not resolve conflicting interpretations.

Before task completion, reconcile its changes or report the exact remaining gap, persist the broader coverage backlog, and continue it during later active work. No maintenance runs after sessions end unless separately authorized.
