# Meaningful code graph: selection and maintenance

The graph is a navigable account of code the agent has understood, not an index of every token or declaration. Apply these rules within an authorized host using the [controlled schema](schema.md). Do not activate EvoMneme in its own repository. No scanner, separate indexing pipeline or new schema is required.

## Shared representation across population and maintenance

Initial population and ordinary maintenance use the same selection, identity, description and evidence rules. The [initial population procedure](initial-population.md) changes the reading scope and order, not the shape of the resulting records. Use [architecture construction and maintenance](architecture-graph.md) for responsibilities, system boundaries, flows and decisions beyond individual code entities; it uses the same store and conventions.

- Before adding records, consult the private connection receipt and inspect relevant existing records in the verified scope. Reuse compatible entity IDs, source-path conventions, type/relationship names and meanings. For code entities, stable identities include the source and immediate owner; architectural concepts use their responsibility/boundary. Line numbers are only locators. Match the actual entity before reusing an ID, and reconcile it instead of creating a second population-specific copy. Historical records require source verification before reuse in a current scope.
- Use concise summaries of responsibility, important behavior/contracts, limitations and consequential uncertainty. Keep source locators, evidence, signatures and inspection state in their supported fields, rather than copying source bodies or introducing a second representation in prose.
- Follow explicit host rules for the language of descriptions and terminology, then compatible existing records. For a new empty store without such rules, use the user's language. Preserve actual program identifiers and API names. Reuse established type/relationship values rather than translating them with each session. If existing conventions conflict, record the selected convention for new and touched records; do not silently rewrite the rest of the store.
- Keep a short record of the chosen ID/path conventions, vocabulary and description language in the existing private connection receipt. Consult it during both initial population and maintenance. It records host choices, not a copied rulebook or permission to override the released schema and selection rules.

Existing records that violate these rules are not templates to reproduce. Preserve useful knowledge and report incompatible conventions or oversized legacy areas; bulk cleanup is separate work. A record's representation must not depend on whether it was discovered during a full build or a later task.

## Choose the reading scope

**Ordinary development:** add and reconcile knowledge from sources actually read while solving the task. Follow relevant dependencies when needed to understand them. Do not inventory or populate the entire repository merely because the skill is active, and do not resume unrelated full-build work during a small task.

**Explicit full build or rebuild:** establish the own-source boundary and read it sequentially in bounded, resumable batches. File/directory listings may establish the traversal order, including local new files; search may locate relevant code. Neither those lists nor grep/static-analysis results are observations to turn into records. Read and understand the sources yourself before preparing SQL. A rebuild request does not by itself require deleting the existing database; reconcile useful data within the agreed scope.

Include own application/library code and own scripts/examples under the same selection rules. Tests and foreign dependencies use the shallow boundaries below. Do not traverse dependency trees, vendored implementations, secrets or disposable build outputs. Describe excluded roots/reasons once in the existing project/module summary or private connection receipt; do not create a node per excluded file or generated artifact. For generated code, retain the meaningful generator/source boundary rather than indexing the output mechanically. Documentation/configuration can support facts without becoming code nodes for every file, key or code fence.

## Select entities

The allowed code entities are **files, modules, classes, methods, functions, fields, constants and global variables**. These are data conventions, not new SQL constraints. Use stable identities qualified by source and immediate owner; line numbers are locators, not identity. Keep source paths consistent within a scope. Store qualified names/signatures/language in `symbol_details` and common meaning/locators on `nodes`.

- Keep module-level functions and class methods, including private ones. Keep instance/class fields, class constants and module globals/constants. Do not copy inherited members onto subclasses.
- Exclude function-local variables and nested functions/classes/constants that only serve internal implementation. An entity returned, exposed or passed to another consumer may be represented when reading establishes that boundary crossing; it is an exception to the local-declaration rule, not a reason to store the rest of the body. Passing or returning a local variable's value does not by itself expose the local variable as a program entity; a returned callable/type can have its own identity.
- Model a property as one field; describe access behavior there. Consolidate overload signatures and getter/setter variants into their logical entity rather than separate nodes. Do not invent extra kinds for each syntax form.
- A file and a module need separate nodes only when each represents a distinct responsibility/boundary. A one-file module normally uses the file node as the owner.
- Represent foreign code only by the directly used entity, such as a called function or base class, with a short role and available locator. Use its actual entity kind and note the external boundary in its summary. Do not expand its implementation, inherited members or dependencies, or create unused imported symbols.
- Represent tests by test-case functions/methods and minimal file/class ownership. Summarize what the case checks and link it to own code only when analysis establishes a meaningful direct interaction. Do not store fixtures, helpers, local declarations, assertion internals or separate parameterized instances.

A code node must identify an actual eligible entity. Its summary captures responsibility, important behavior/contracts, limitations and consequential uncertainty, without copying the source body. Read source again when detailed implementation is needed. Architecture, decisions and substantive findings may be separate knowledge nodes; routine coverage checks and analysis TODOs are not such findings.

## Establish relationships

Write an edge only after your own source analysis establishes what the connection means and where it is supported. Code search and analyzer output can help navigate, but are not sufficient evidence, even when accompanied by hashes or line numbers. SQL batching is appropriate for already understood observations.

- Use `contains` from the immediate owner to a member: file → class → method/field, or file → top-level function. Do not add file → every descendant or a parallel `declared_in` edge. Source paths on nodes provide file lookup without redundant adjacency.
- Keep direct calls, inheritance and other meaningful interactions you have understood, including callbacks/registrations when their target and mechanism are established. Do not create all-pairs connections, transitive dependencies, name-match references, incidental reads/writes or edges merely because a field has a type annotation.
- Import syntax alone does not establish use. A module import/re-export can be a meaningful boundary interaction when you have read and understood that role; do not emit one edge per imported name mechanically.
- Repeated occurrences between the same entities with the same relationship meaning share an edge. Retain only evidence needed to verify it, not an attachment for every occurrence. Keep distinct edges only when their meanings genuinely differ.
- Unknown or candidate targets stay in the originating node's summary or the file's `remaining_work`, with what is known and what would resolve it. Do not create unresolved/ambiguous reference nodes, gap/review nodes or speculative call edges. Reasoned conclusions must be labelled with appropriate confidence and evidence; confidence is not permission to insert a guess.

All retained adjacency belongs in `edges`. This requirement applies to meaningful relationships selected above, not to every fact mentioned in a summary. Do not encode a second adjacency model in JSON or private extension tables.

## Inspection state and full-build completion

Keep per-file inspection state in `file_details`: inspected hash, declaration/relationship status and concise remaining work. Put symbol-specific uncertainty in its summary. Never create coverage-review, gap, exclusion or unresolved-reference nodes to count work. The viewer finds a symbol's file inspection state through its source locator in the same scope; no additional graph edge is required.

For an explicit full build, maintain a compact traversal cursor and included/excluded roots in the private connection receipt or an existing owning module/project summary. Add file nodes as files are read; do not prepopulate thousands of pending nodes. Save the next file/region at batch boundaries and resume when continuing that full-build task. Distinguish pending, partial, verified, stale and blocked work; unfinished reading is not complete coverage.

Before claiming completion for an explicit scope/snapshot:

1. Reconcile the own-source file list with files actually read and documented exclusions. Include uncommitted/new sources within the agreed boundary; do not conceal inaccessible sources as successful exclusions.
2. Compare the eligible declarations you observed with stored identities, immediate owners and locators. Account for omitted local implementation, shallow tests and external boundaries rather than treating them as gaps.
3. Review meaningful direct interactions in the read code. Keep unresolved questions as attributes; declaration coverage does not establish that all dynamic targets are known.
4. Exercise source lookup, immediate owner/member navigation and incoming/outgoing relationships. Recheck the source snapshot before recording verified status; changes during analysis leave affected inspection state stale.

Report the inspected scope/version, remaining reading point and consequential uncertainty. Coverage ratios require a source-grounded denominator. Record totals, successful SQL, hashes and spot checks alone are not completeness evidence. Do not impose arbitrary record quotas or claim development-efficiency gains without measurement.

## Reconcile changes

During ordinary work, recheck the applicability of knowledge you use. Reconcile changed eligible entities, immediate ownership, meaningful edges and evidence; follow affected callers/contracts as needed. For moves or deletions, update identities/locators and remove or invalidate obsolete current relationships. Retain useful version-scoped history. Mark affected dependents stale when they cannot yet be verified; do not create a service node for each pending check.

Commit coherent graph/evidence/inspection updates in an explicit transaction after rechecking source identity. Concurrent agents must coordinate overlapping source areas; database locks do not reconcile conflicting interpretations. These selection rules do not automatically clean an existing oversized store: plan destructive cleanup separately within host authorization.

## Selection examples

| Observation from source reading | Representation |
| --- | --- |
| Private method `Cache._load` with local `buffer` and helper `decode_chunk` used only inside it | Keep the method under `Cache`; omit the local variable/helper. Summarize an important decoding constraint if relevant. |
| `make_handler` returns nested `handle`, which callers invoke | Keep the factory and escaping function with immediate ownership and locators; explain the returned-callback contract. Do not invent calls from unidentified consumers. |
| Property `Cache.size` has getter/setter; `fetch` has several overload signatures | One field for the property and one method/function for `fetch`; describe access behavior/signatures without accessor/overload nodes. |
| `Client` subclasses external `vendor.Base` and calls external `vendor.send` | Keep the directly used external class/function and evidenced inheritance/call edges. Do not read/index the vendor tree. |
| `field: OtherType` or an unused import of `OtherType` | No type/use edge solely from that syntax. |
| Parameterized `test_retry`, a fixture, and nested assertion helpers | One test-case node under its file/class; concise checked behavior; omit fixture/helpers/parameter instances. |
| A callback target cannot be determined | A note on the caller or its file inspection state, not a new reference/gap node or guessed edge. |
| A small bug fix reads two methods | Reconcile the relevant entities/interactions; do not start or resume repository-wide population. |
| Explicit request to rebuild the project's full graph | Read own sources sequentially under these rules; persist the next reading point, not scanner-generated declarations. |
