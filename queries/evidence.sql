-- Evidence for one selected current target. See references/retrieval.md.
-- Fetch one lookahead: set executor max_rows to the same positive limit.
SELECT p.scope_id,p.id AS evidence_id,p.node_id,p.edge_id,p.description,p.validity,
       p.source_path,p.source_hash,p.updated_at
FROM evidence p
WHERE p.scope_id=:scope AND p.validity='current' AND :limit>0
  AND (:after_id IS NULL OR p.id>:after_id)
  AND ((:target_type='node' AND p.node_id=:target AND EXISTS (
         SELECT 1 FROM nodes n WHERE n.scope_id=p.scope_id AND n.id=p.node_id AND n.validity='current'))
       OR (:target_type='edge' AND p.edge_id=:target AND EXISTS (
         SELECT 1 FROM edges e WHERE e.scope_id=p.scope_id AND e.id=p.edge_id AND e.validity='current')))
ORDER BY p.id
LIMIT max(0,:limit)+1;
