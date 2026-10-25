-- EvoMneme schema v3: the shared storage/viewer contract for new host stores.
-- Apply deliberately to an EMPTY authorized host database, never this repository.
-- Raw SQLite script: use a native script facility, not execute_sql/--sql-file.
-- Schema changes belong in public EvoMneme releases with viewer/tests/migrations.
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE scopes (
    id TEXT PRIMARY KEY, branch TEXT NOT NULL, worktree TEXT NOT NULL,
    revision TEXT NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE nodes (
    scope_id TEXT NOT NULL REFERENCES scopes(id), id TEXT NOT NULL,
    kind TEXT NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL,
    confidence TEXT NOT NULL CHECK(confidence IN ('confirmed','inferred','uncertain')),
    validity TEXT NOT NULL CHECK(validity IN ('current','stale','superseded')),
    source_path TEXT, source_hash TEXT, line_start INTEGER, line_end INTEGER,
    updated_at TEXT NOT NULL, layer TEXT NOT NULL DEFAULT 'knowledge',
    PRIMARY KEY(scope_id,id)
);
CREATE TABLE edges (
    scope_id TEXT NOT NULL, id TEXT NOT NULL, source_id TEXT NOT NULL,
    target_id TEXT NOT NULL, kind TEXT NOT NULL, summary TEXT NOT NULL,
    confidence TEXT NOT NULL CHECK(confidence IN ('confirmed','inferred','uncertain')),
    validity TEXT NOT NULL CHECK(validity IN ('current','stale','superseded')),
    source_path TEXT, source_hash TEXT, updated_at TEXT NOT NULL,
    layer TEXT NOT NULL DEFAULT 'knowledge',
    resolution TEXT NOT NULL DEFAULT 'resolved'
        CHECK(resolution IN ('resolved','unresolved','ambiguous')),
    line_start INTEGER, line_end INTEGER,
    PRIMARY KEY(scope_id,id),
    FOREIGN KEY(scope_id,source_id) REFERENCES nodes(scope_id,id),
    FOREIGN KEY(scope_id,target_id) REFERENCES nodes(scope_id,id)
);
-- Provenance attachments are attributes of nodes/edges, not a second graph.
-- An independently navigable observation is a nodes row, linked through edges.
CREATE TABLE evidence (
    scope_id TEXT NOT NULL REFERENCES scopes(id), id TEXT NOT NULL,
    node_id TEXT, edge_id TEXT, description TEXT NOT NULL,
    source_path TEXT, source_hash TEXT,
    validity TEXT NOT NULL CHECK(validity IN ('current','stale','superseded')),
    updated_at TEXT NOT NULL, PRIMARY KEY(scope_id,id),
    CHECK((node_id IS NULL) != (edge_id IS NULL)),
    FOREIGN KEY(scope_id,node_id) REFERENCES nodes(scope_id,id),
    FOREIGN KEY(scope_id,edge_id) REFERENCES edges(scope_id,id)
);
CREATE TABLE symbol_details (
    scope_id TEXT NOT NULL, node_id TEXT NOT NULL,
    qualified_name TEXT NOT NULL, signature TEXT, language TEXT,
    PRIMARY KEY(scope_id,node_id),
    FOREIGN KEY(scope_id,node_id) REFERENCES nodes(scope_id,id)
);
CREATE TABLE file_details (
    scope_id TEXT NOT NULL, node_id TEXT NOT NULL,
    declaration_status TEXT NOT NULL DEFAULT 'pending'
        CHECK(declaration_status IN ('pending','partial','verified','stale','blocked','excluded')),
    relationship_status TEXT NOT NULL DEFAULT 'pending'
        CHECK(relationship_status IN ('pending','partial','verified','stale','blocked','excluded')),
    inspected_hash TEXT, exclusion_reason TEXT, remaining_work TEXT,
    PRIMARY KEY(scope_id,node_id),
    FOREIGN KEY(scope_id,node_id) REFERENCES nodes(scope_id,id)
);
CREATE TABLE history (
    id INTEGER PRIMARY KEY, happened_at TEXT NOT NULL,
    action TEXT NOT NULL, detail TEXT NOT NULL
);
CREATE INDEX nodes_kind ON nodes(scope_id,kind);
CREATE INDEX nodes_source ON nodes(scope_id,source_path);
CREATE INDEX edges_source ON edges(scope_id,source_id);
CREATE INDEX edges_target ON edges(scope_id,target_id);
CREATE INDEX evidence_node ON evidence(scope_id,node_id);
CREATE INDEX evidence_edge ON evidence(scope_id,edge_id);
INSERT INTO metadata VALUES ('schema_version','3');
PRAGMA user_version = 3;
COMMIT;
