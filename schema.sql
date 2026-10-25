-- OPTIONAL starter/example, compatible with the earlier v2 table layout.
-- Never auto-applied: the agent owns schema design, versioning and migrations.
-- Apply only to a new empty authorized HOST database, never the tool repository.
-- Inspect/preserve existing tables and data; do not blindly rerun this script.
-- RAW SQLITE SCRIPT: use an authorized SQLite script facility, not execute_sql
-- or CLI --sql-file (each accepts only one native statement). Never add a splitter.
-- Host identity, scope and source hashes are agent-owned.
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE scopes (
    id TEXT PRIMARY KEY, branch TEXT NOT NULL, worktree TEXT NOT NULL,
    revision TEXT NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE records (
    scope_id TEXT NOT NULL REFERENCES scopes(id), id TEXT NOT NULL,
    kind TEXT NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL,
    confidence TEXT NOT NULL CHECK(confidence IN ('confirmed','inferred','uncertain')),
    validity TEXT NOT NULL CHECK(validity IN ('current','stale','superseded')),
    source_path TEXT, source_hash TEXT, line_start INTEGER, line_end INTEGER,
    updated_at TEXT NOT NULL, PRIMARY KEY(scope_id,id)
);
CREATE TABLE relations (
    scope_id TEXT NOT NULL, id TEXT NOT NULL, source_id TEXT NOT NULL,
    target_id TEXT NOT NULL, kind TEXT NOT NULL, summary TEXT NOT NULL,
    confidence TEXT NOT NULL CHECK(confidence IN ('confirmed','inferred','uncertain')),
    validity TEXT NOT NULL CHECK(validity IN ('current','stale','superseded')),
    source_path TEXT, source_hash TEXT, updated_at TEXT NOT NULL,
    PRIMARY KEY(scope_id,id),
    FOREIGN KEY(scope_id,source_id) REFERENCES records(scope_id,id),
    FOREIGN KEY(scope_id,target_id) REFERENCES records(scope_id,id)
);
CREATE TABLE evidence (
    scope_id TEXT NOT NULL REFERENCES scopes(id), id TEXT NOT NULL,
    record_id TEXT, relation_id TEXT, description TEXT NOT NULL,
    source_path TEXT, source_hash TEXT,
    validity TEXT NOT NULL CHECK(validity IN ('current','stale','superseded')),
    updated_at TEXT NOT NULL, PRIMARY KEY(scope_id,id),
    CHECK((record_id IS NULL) != (relation_id IS NULL)),
    FOREIGN KEY(scope_id,record_id) REFERENCES records(scope_id,id),
    FOREIGN KEY(scope_id,relation_id) REFERENCES relations(scope_id,id)
);
CREATE TABLE history (
    id INTEGER PRIMARY KEY, happened_at TEXT NOT NULL,
    action TEXT NOT NULL, detail TEXT NOT NULL
);
CREATE INDEX records_kind ON records(kind);
CREATE INDEX relations_target ON relations(scope_id,target_id);
CREATE INDEX evidence_record ON evidence(scope_id,record_id);
CREATE INDEX evidence_relation ON evidence(scope_id,relation_id);
INSERT INTO metadata VALUES ('schema_version','2');
PRAGMA user_version = 2;
COMMIT;
