# Controlled graph schema, version 3

[schema.sql](../schema.sql) is the canonical starting model for every new authorized host store. It is a shared EvoMneme architecture contract, not a per-host example. The SQL executor stays generic and does not install or police the schema; agents must follow this contract. Creating an empty database does not initialize it.

## One graph

| Table | Role |
| --- | --- |
| `nodes` | Every graph entity: files, symbols, modules, architecture, decisions, findings, external boundaries, unresolved references. Identity is `(scope_id,id)`; `kind` describes its type and `layer` its display grouping. |
| `edges` | Every graph relationship, including containment, calls, imports and links between code and decisions. Both endpoints reference `nodes` in the same scope. `kind`, direction and `resolution` retain their meaning. |
| `symbol_details` | Optional one-to-one symbol attributes: qualified name, signature, language. Its key `(scope_id,node_id)` references a node. Ownership is an edge, not a second adjacency model. |
| `file_details` | Optional one-to-one file inspection state: declaration and relationship coverage, inspected hash, exclusions and remaining work. The file itself is a node with its locator in `source_path`. |
| `evidence` | Provenance attributes attached to exactly one node or edge through `node_id` / `edge_id`. These attachments do not define a separate graph. If an observation needs independent navigation, create an ordinary node and explicit edges for it. |
| `scopes`, `metadata`, `history` | Source/version boundaries, store metadata and maintenance notes. `history` is not a lossless row-change audit. |

Common summaries, confidence, validity and source locators belong on nodes/edges, so retrieval need not join type-specific tables. Keep detailed attributes in the supported extension tables. Do not create a second node/edge registry for a new language, entity type or project. Extensions must not hide structural relationships in strings, JSON or foreign keys outside `edges`.

Use stable qualified node IDs within a scope; types do not establish separate identity namespaces. A function and a decision cannot share an ID in the same scope. IDs survive ordinary updates; source line numbers are locators, not identity. Viewer IDs are `json_array(scope_id,id)` for both nodes and edges, in separate viewer namespaces. `layer` is stored data: normally `code`, `knowledge`, `unresolved`, with `cross` for cross-layer edges. A new `kind` or `layer` value is ordinary data and must render without a schema edit.

Use `contains` edges from an owner/file to its members, and `declared_in` edges from symbols to their source-file nodes. These serve different navigation purposes. File detail is attached to the file node; symbol coverage is retrieved through `declared_in`. Represent excluded inventory files as file nodes with explicit exclusion reasons. Represent unresolved sites as ordinary `unresolved_reference` or `ambiguous_reference` nodes in layer `unresolved`, with an originating edge carrying the corresponding `resolution`. Do not invent a resolved target or leave dangling foreign keys. External declarations known only at a boundary can use `external_symbol`.

`confidence` is `confirmed`, `inferred` or `uncertain`; `validity` is `current`, `stale` or `superseded`. Resolution is independent of confidence. File coverage is `pending`, `partial`, `verified`, `stale`, `blocked` or `excluded`; stored coverage is an assertion to verify against sources. Evidence staleness and affected dependents must be reconciled transactionally by the agent.

## Initialization and compatibility

1. Verify the authorized host, excluded local storage and installed EvoMneme revision. Inspect the existing file before any DDL.
2. For a new empty database, apply the exact released `schema.sql` using an authorized native SQLite script facility, or author a command array with one complete statement per command and explicit transaction boundaries. Do not split SQL with a home-made parser. The generic `execute_sql` and CLI `--sql-file` accept one native statement per string, not this whole script.
3. Verify `PRAGMA user_version` and `metadata.schema_version` are both 3, compare tables/columns/constraints/indexes with the release, and run `PRAGMA integrity_check` and `PRAGMA foreign_key_check`. Check the matching viewer on a synthetic fixture before declaring the integration compatible.
4. Create a scope before its nodes, nodes before edges, and attach supported details/evidence using bound values. Record the schema version and tool revision in the host connection receipt.

Never overwrite an existing database with the bootstrap script. The viewer supports only v3 and rejects older/unversioned databases before any inspection or journal installation. A custom projection does not bypass this check. Apply a compatible published migration before opening an existing older store.

[002_to_003.sql](../migrations/002_to_003.sql) migrates the **unextended official v2 starter**: node/edge IDs, scopes, records, relationships, evidence, metadata and history are retained. New layers default to `knowledge`; this does not reclassify old data or assert new source verification. Inspect the source DDL against the old published schema, stop writers, back up, and test on an isolated copy first. The script rejects wrong versions, extra tables/views/triggers and different column layouts; these guards are not a complete semantic DDL comparison. A native script caller must stop and roll back on any error. Verify constraints, counts, representative traversal and viewer details after success.

Stores containing additional code tables, custom columns or audit extensions need a separately published migration that understands that exact source contract. Do not drop these tables or their history to make this migration pass, and do not invent a private conversion. Until a compatible migration is available, retain the existing store and report migration as pending; it cannot be opened in this viewer. Unsupported/future schemas produce an explicit incompatibility message. Custom mappings change projections within a supported v3 store, not the supported database versions.

## Retrieval contract

Agents query `nodes` and `edges` directly for every type and layer. [queries/neighborhood.sql](../queries/neighborhood.sql) is a single native SQLite statement for bounded cross-type navigation, usable through MCP, Python or CLI. Bind `scope`, `root`, `max_depth` (0 through 32), `direction` (`incoming`, `outgoing`, `both`), `edge_kind` (null for all), `traverse_kind` (null for all intermediate types), `result_kind` (null for all returned types), and `limit` (positive). It follows only current nodes/edges in one scope and returns minimum hop depth. The root is included at depth zero when it passes the result filter; traversal type restrictions apply to subsequent nodes.

Keep traversal and result filters distinct. To reach decisions via symbols and components, leave `traverse_kind` null and set `result_kind='decision'`. Setting the traversal kind to `decision` would prevent passing through symbols. Depth bounds and `UNION` bound repeated visits in cyclic graphs; result limits alone do not bound query work. Start small and respect executor time/output budgets. Adapt predicates and requested columns for a task without changing the schema; fetch signatures, coverage or evidence only for selected results. The viewer's neighborhood control remains bounded to depths 1–4 and uses its documented filter semantics.

## Schema changes are public architecture work

The agent freely inserts, updates, invalidates and queries host data within authorization. Adding type/layer values, scopes, graph nodes, edges or rows in existing detail tables does not change the schema. Adding/removing/renaming tables, columns, indexes, views, triggers or constraints, changing ID encoding, or changing field semantics **does**. Do not do that as local knowledge maintenance, including a supposedly harmless host-only performance index.

A schema change requires one reusable EvoMneme change: explain the need, update the canonical schema and version/extension version, publish data-preserving migration(s) with explicit source-version coverage, update viewer projection/detail/filter/activity support, update instructions/examples, and test new initialization, migration/rollback, cross-type traversal and viewer compatibility on synthetic fixtures. An extension's installation and upgrade must follow its own published versioned contract. Publish the solution in the public repository (fork/PR where appropriate) and use the compatible published tool revision before applying it to a host. If a required migration or viewer capability is missing, continue supported data work and report the architecture gap.

Never publish host databases, backups or private evidence. Do not change the protected founding charter without explicit human authorization. Its allowance to choose a model is exercised through this shared architecture and its public evolution, rather than independent per-host schemas.
