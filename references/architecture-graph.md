# Architecture graph: construction and maintenance

Record how the host system is organized and why: responsibilities, component boundaries, important flows, external contracts and consequential decisions. This is an architectural view within the same [controlled graph](schema.md), connected to code and evidence, not another database or a mechanically collapsed call graph. Use only within an authorized host; do not activate EvoMneme in this repository, its forks or worktrees.

Apply the [shared representation conventions](code-graph.md#shared-representation-across-population-and-maintenance) during both [initial population](initial-population.md) and ordinary development. A full build reviews architecture across the agreed project boundary; ordinary work updates the architectural facts it actually investigates or affects.

## Select meaningful architectural concepts

Represent a concept when it captures a distinct responsibility, contract or boundary useful for understanding changes. Examples include a subsystem, running service, data store, external integration or an important workflow spanning components. A directory, package, class, configuration key or deployment resource is not automatically an architectural component. Do not impose a template's layers on a project that does not have them.

Use common `nodes` fields for these concepts, with `layer='knowledge'` and compatible existing kinds; use `kind='architecture'` when no suitable host convention exists. Use stable identities based on the concept's role/boundary, not its discovery batch or a source line. Reuse a code file/module node when it already expresses the same responsibility; a separate architecture node needs a distinct abstraction, such as a service implemented across modules. Actual code entities retain their code representation and selection limits.

Summarize responsibility, boundary, important inputs/outputs or contracts, constraints and consequential uncertainty. Include operational, product or UI/UX responsibilities when supported and relevant. Keep decisions and substantive findings as their existing knowledge kinds, with reasons and consequential alternatives. Do not infer historical motivation solely from current implementation, invent rejected alternatives or create routine review/TODO nodes.

## Build from evidence

1. Read relevant non-secret project documentation and decision records to identify intended responsibilities, terminology and claims. Treat diagrams and descriptions as evidence to check, not automatic truth about the running system.
2. Inspect entrypoints, composition/registration code, public interfaces, configuration and deployment descriptions to establish actual boundaries and connections. Follow implementation paths for important user/system flows. Read tests as evidence of the contracts they check, without claiming they prove deployed behavior.
3. Trace meaningful interactions between boundaries: what initiates the interaction, what data/control crosses it, the target and mechanism, and important failure or consistency constraints where established. Resolve sufficient implementation to support the claim; folder names, imports and similarly named entities alone do not establish architecture.
4. Reconcile documented intent with observed implementation. Describe whether a claim is intended, implemented or observed at runtime, with the corresponding evidence and confidence. Preserve material disagreement as an evidenced finding or uncertainty on the relevant concept. A proposed design must not appear as a current implemented relationship; `validity='current'` alone does not mean implemented.

Attach evidence through the existing `evidence` table to the node or edge it supports. Use source/version locators and inspected content identity for code, configuration and documents. For an authorized decision or runtime observation, retain a concise dated description and available provenance. Do not copy documents, credentials, deployment secrets or conversations into the store. Summaries may combine sources, but must not claim a broader boundary or behavior than those sources establish.

## Connect architecture, code and decisions

All relationships belong in `edges`, with endpoints in the same scope. Reuse compatible host relationship names and directions; document any newly needed vocabulary in the private receipt. Without an existing convention, use `depends_on` from a consumer to a directly required component, `implements` from representative code to the architectural responsibility it realizes, and `constrains` from a decision to the concept it governs. Describe the actual mechanism/contract and attach supporting evidence; these names are data conventions, not schema changes.

Use `layer='knowledge'` for relationships among knowledge nodes and `layer='cross'` between knowledge and code. Link representative implementation boundaries that explain a concept, not every descendant symbol. Architectural abstraction does not justify redundant containment or all-pairs dependencies: record direct component interactions you have understood, without generating edges from transitive code reachability. Repeated observations of the same meaning reuse one edge; genuinely different contracts may have distinct evidenced relationships.

Describe a multi-step flow through its direct participants and interactions; create a workflow node only when the workflow has a useful independent contract or responsibility. An uncertain participant stays in the originating summary or existing remaining-work attributes until established. Do not invent targets or expand external implementations to fill out a diagram.

## Completion and maintenance

Before reporting an architectural review complete, reconcile the reviewed sources with the responsibilities and boundaries they establish. Check important entrypoint-to-outcome flows, storage/external interactions and relevant decisions within the agreed scope. Follow architectural claims to evidence and representative implementation, and back from that implementation to its architectural context. Check that intent, implementation, runtime observations and unresolved contradictions remain distinguishable.

Track architectural review progress and remaining questions in the existing private receipt or owning concept summary. `file_details` describes code inspection; verified declarations do not certify architecture. If evidence is inaccessible or a flow is only partly understood, report that limitation without constructing a speculative complete diagram. Record counts are not completion criteria.

During ordinary development, revisit affected architectural responsibilities, contracts, flows and decision links when sources change. Reuse the same identities and conventions as initial population. Recheck sources before atomically updating claims, relationships and evidence; invalidate unsupported dependents, retain scoped history and supersede decisions only when evidence establishes the change. A local refactor may leave architecture unchanged, while configuration or contract changes may require architectural updates even without new code declarations.

## Representation examples

| Observation | Representation |
| --- | --- |
| A service spans routing, business logic and persistence modules | One architectural responsibility if that boundary is established, linked to representative implementation and direct dependencies; no node per folder by default. |
| A design document proposes a queue, but current code writes synchronously | Preserve the proposal/decision and the evidenced implementation distinction; do not add a current implemented queue dependency. |
| Configuration and adapter code establish an external payment integration | Record the external contract/boundary and direct interaction, with non-secret evidence; do not index the provider's implementation. |
| An architecture decision explains why retries must be idempotent | Keep its reasons and actual alternatives; link it to the affected responsibility and relevant code contract. |
| A configuration change redirects persistence to a different service | Reconcile architectural edges and evidence as well as relevant code knowledge; unchanged declarations do not mean unchanged architecture. |
