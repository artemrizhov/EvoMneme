-- One native statement. Bind all parameters documented in references/schema.md.
WITH RECURSIVE
eligible_edges AS MATERIALIZED (
    SELECT source_id,target_id FROM edges
    WHERE scope_id=:scope AND validity='current'
      AND (:edge_kind IS NULL OR kind=:edge_kind)
),
arcs(source_id,target_id) AS (
    SELECT source_id,target_id FROM eligible_edges
    WHERE :direction IN ('outgoing','both')
    UNION
    SELECT target_id,source_id FROM eligible_edges
    WHERE :direction IN ('incoming','both')
),
reach(id,depth) AS (
    SELECT id,0 FROM nodes
    WHERE scope_id=:scope AND id=:root AND validity='current'
      AND :max_depth BETWEEN 0 AND 32 AND :limit>0
      AND :direction IN ('incoming','outgoing','both')
    UNION
    SELECT a.target_id,r.depth+1
    FROM reach r JOIN arcs a ON a.source_id=r.id
    JOIN nodes n ON n.scope_id=:scope AND n.id=a.target_id
    WHERE r.depth<:max_depth AND n.validity='current'
      AND (:traverse_kind IS NULL OR n.kind=:traverse_kind)
),
nearest AS (SELECT id,min(depth) AS depth FROM reach GROUP BY id)
SELECT n.id,n.kind,n.layer,n.title,n.summary,n.confidence,n.source_path,r.depth
FROM nearest r JOIN nodes n ON n.scope_id=:scope AND n.id=r.id
WHERE :result_kind IS NULL OR n.kind=:result_kind
ORDER BY r.depth,n.id
LIMIT max(0,:limit);
