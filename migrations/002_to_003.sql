-- Published migration for the unextended official v2 starter only.
-- Back up and test an isolated copy first. Use a native script facility.
-- On ANY error the caller must ROLLBACK and stop; never continue the script.
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;
CREATE TEMP TABLE evomneme_v2_guard (ok INTEGER NOT NULL CHECK(ok=1));
INSERT INTO evomneme_v2_guard
SELECT CASE WHEN
    (SELECT user_version FROM pragma_user_version)=2
    AND (SELECT value FROM metadata WHERE key='schema_version')='2'
    AND (SELECT count(*) FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%')=6
    AND (SELECT count(*) FROM sqlite_schema WHERE type IN ('view','trigger'))=0
    AND (SELECT group_concat(name,',') FROM pragma_table_info('metadata'))='key,value'
    AND (SELECT group_concat(name,',') FROM pragma_table_info('scopes'))='id,branch,worktree,revision,snapshot,created_at'
    AND (SELECT group_concat(name,',') FROM pragma_table_info('records'))='scope_id,id,kind,title,summary,confidence,validity,source_path,source_hash,line_start,line_end,updated_at'
    AND (SELECT group_concat(name,',') FROM pragma_table_info('relations'))='scope_id,id,source_id,target_id,kind,summary,confidence,validity,source_path,source_hash,updated_at'
    AND (SELECT group_concat(name,',') FROM pragma_table_info('evidence'))='scope_id,id,record_id,relation_id,description,source_path,source_hash,validity,updated_at'
    AND (SELECT group_concat(name,',') FROM pragma_table_info('history'))='id,happened_at,action,detail'
    AND NOT EXISTS(SELECT 1 FROM pragma_foreign_key_check)
THEN 1 ELSE 0 END;
ALTER TABLE records RENAME TO nodes;
ALTER TABLE relations RENAME TO edges;
ALTER TABLE evidence RENAME COLUMN record_id TO node_id;
ALTER TABLE evidence RENAME COLUMN relation_id TO edge_id;
ALTER TABLE nodes ADD COLUMN layer TEXT NOT NULL DEFAULT 'knowledge';
ALTER TABLE edges ADD COLUMN layer TEXT NOT NULL DEFAULT 'knowledge';
ALTER TABLE edges ADD COLUMN resolution TEXT NOT NULL DEFAULT 'resolved'
    CHECK(resolution IN ('resolved','unresolved','ambiguous'));
ALTER TABLE edges ADD COLUMN line_start INTEGER;
ALTER TABLE edges ADD COLUMN line_end INTEGER;
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
DROP INDEX records_kind;
DROP INDEX relations_target;
DROP INDEX evidence_record;
DROP INDEX evidence_relation;
CREATE INDEX nodes_kind ON nodes(scope_id,kind);
CREATE INDEX nodes_source ON nodes(scope_id,source_path);
CREATE INDEX edges_source ON edges(scope_id,source_id);
CREATE INDEX edges_target ON edges(scope_id,target_id);
CREATE INDEX evidence_node ON evidence(scope_id,node_id);
CREATE INDEX evidence_edge ON evidence(scope_id,edge_id);
UPDATE metadata SET value='3' WHERE key='schema_version';
PRAGMA user_version = 3;
INSERT INTO history(happened_at,action,detail)
VALUES(datetime('now'),'schema_migration','Published v2 to v3: shared nodes and edges; original IDs and provenance retained.');
DROP TABLE evomneme_v2_guard;
COMMIT;
