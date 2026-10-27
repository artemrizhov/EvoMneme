# Initial population of an authorized host database

Use this procedure for an explicit request to build the host's complete knowledge graph, or to resume/rebuild that agreed scope. Connecting EvoMneme, opening an empty store or performing an ordinary task does not start a full build. Self-hosting requires the same explicit authorization and storage isolation as any other host.

The result combines selected code entities with architectural responsibilities, boundaries, flows and useful decisions. Follow the shared [representation and code selection rules](code-graph.md) and [architecture rules](architecture-graph.md). Initial population is a broader reading pass under the ordinary maintenance rules, not a separate data format or indexing pipeline.

## 1. Verify readiness and existing knowledge

Confirm the authorized host, applicable instructions, live tool revision, configured SQL transport, canonical excluded database path, branch/worktree/revision and local changes. Follow [connection verification](integration.md), [storage practice](storage.md) and [schema compatibility](schema.md#initialization-and-compatibility). Keep connection verification separate from graph coverage; report incomplete setup accurately. A failed configured integration stops affected work unless its repair or another route is already authorized.

Inspect an existing store before changing it. Initialize only a new empty store using the released schema and an authorized facility; preserve existing records and use only compatible published migrations. An empty current-scope query does not prove the database is empty. Check relevant history and source applicability before reusing it; never promote old claims automatically or erase the store to begin a build.

Read the private connection receipt and representative compatible records. Establish or reuse the shared identity, path, vocabulary and language conventions, and record the choices in that receipt. Confirm the source/version scope before preparing any records.

## 2. Establish the reading boundary and order

Include own application/library sources, scripts and examples, plus tests at the depth defined by the code selection rules. Include uncommitted/new sources within that boundary. Identify relevant architecture documentation, manifests, entrypoints, configuration and deployment descriptions as evidence sources; they do not each require a code node. Read only non-secret material within the authorized boundary.

Record included roots, exclusions with reasons, scope/snapshot and traversal order in the private receipt. Default to sorted project-relative paths within the included roots and source order within each file; record any deliberate dependency-first detour so it does not skip a file. For generated code, inspect the meaningful generator/source boundary. Do not traverse vendor/dependency implementations or disposable outputs. Inaccessible in-scope sources are blocked work, not successful exclusions.

Listings and searches establish navigation and the source inventory only. Do not populate declarations or relationships from grep, static-analysis output or file lists, or precreate pending nodes for all unread files.

## 3. Read and understand bounded portions

Read source files sequentially in portions small enough to understand and verify before saving. For each portion, identify eligible declarations, immediate owners and meaningful direct interactions under the shared rules. Follow relevant sources when needed to resolve a relationship; retain a return point in the traversal. An unknown target stays in an existing summary or file's `remaining_work`, not a guessed edge or placeholder node.

Develop the architectural view alongside this reading using the [architecture procedure](architecture-graph.md): establish responsibilities and boundaries, trace important flows, link representative implementation and retain supported decisions and reasons. Documents may describe intent while code/configuration establish a different implementation; preserve that distinction. Do not claim a complete architecture merely because declarations have been recorded.

## 4. Persist understood knowledge coherently

Recheck the affected sources and version identity after reading and before writing. If they changed, reread and reconcile the affected observations instead of marking the old snapshot verified. Coordinate overlapping writers; database locks do not lock source files or settle conflicting interpretations.

Use bound values and explicit `BEGIN`/`COMMIT` for related nodes, details, edges, evidence and inspection updates in one request. Create the scope before nodes, then their edges and attachments. Reuse existing compatible identities and relationships, with the normal `code`, `knowledge` and `cross` layers. Apply the same evidence and confidence requirements to initial and later records. Save per-file declaration/relationship status, inspected hash and remaining work in `file_details`; partial reading remains partial.

After an SQL error, inspect reported durability and actual records before retrying. A batch alone is not atomic, and an error does not prove earlier commits were undone. Do not advance the saved reading point past unconfirmed writes.

## 5. Save progress and resume safely

At each committed batch boundary, update the private receipt with the next file/region, completed reading boundary, any detours, architecture questions still to review and blockers. Keep per-file details and node-specific uncertainty in the existing attributes, not service nodes or a second graph. Save the cursor after the database commit; if interrupted between them, inspect committed records and reconcile the repeated portion using the same IDs.

On an explicit continuation, reload the live instructions, conventions and cursor. Recheck the source inventory and the identity of already inspected sources against the saved state, including additions, renames, deletions and dirty edits. Revisit changed areas and affected code/architectural claims; mark unverifiable dependents stale. If the version scope changed, verify applicability before recording observations in that scope. Resume unchanged work without creating duplicate records. An ordinary small task does not resume unrelated full-build work.

## 6. Verify completion against sources

Apply the [code completion checks](code-graph.md#inspection-state-and-full-build-completion) and [architecture checks](architecture-graph.md#completion-and-maintenance) to the agreed scope and snapshot. Reconcile the source inventory with actual reading and exclusions; account for eligible declarations and reviewed meaningful interactions. Verify source lookup, immediate ownership, incoming/outgoing edges and architecture-to-implementation/evidence navigation.

Recheck source identity before declaring the inspected state verified. Explicitly report blocked files, partial regions, unresolved interactions and architectural uncertainty. Reading completion and unresolved dynamic behavior are different claims: report both accurately. Counts, successful SQL, hashes or a few spot checks alone do not establish completeness, and no record quota is a target.

## 7. Hand over to ordinary maintenance

Report the inspected scope/version, code and architectural coverage, exclusions, material uncertainty and remaining reading point if unfinished. Keep the private receipt's conventions available for future sessions. Separate verified work from pending work and unverified integration checks.

Subsequent development updates the same entities, architectural claims, relationships and evidence under the shared rules. Reconcile relevant changes and invalidate unsupported dependents without beginning another full pass. No second store, bootstrap-only node kinds, new schema or background process is needed.
