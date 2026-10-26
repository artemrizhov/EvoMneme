-- One hop only; preserve stored direction and uncertainty. See references/retrieval.md.
-- Fetch one lookahead: set executor max_rows to the same positive limit.
SELECT e.scope_id,e.id AS edge_id,e.source_id,e.target_id,e.kind AS edge_kind,
       e.summary AS edge_summary,e.confidence AS edge_confidence,e.validity AS edge_validity,
       e.resolution,e.source_path AS edge_source_path,e.source_hash AS edge_source_hash,
       e.line_start AS edge_line_start,e.line_end AS edge_line_end,
       n.id AS neighbor_id,n.kind AS neighbor_kind,n.layer AS neighbor_layer,
       n.title AS neighbor_title,n.summary AS neighbor_summary,
       n.confidence AS neighbor_confidence,n.validity AS neighbor_validity,
       n.source_path AS neighbor_source_path,n.source_hash AS neighbor_source_hash,
       n.line_start AS neighbor_line_start,n.line_end AS neighbor_line_end
FROM edges e
JOIN nodes r ON r.scope_id=e.scope_id AND r.id=:root AND r.validity='current'
JOIN nodes n ON n.scope_id=e.scope_id
  AND n.id=CASE WHEN e.source_id=:root THEN e.target_id ELSE e.source_id END
  AND n.validity='current'
WHERE e.scope_id=:scope AND (e.source_id=:root OR e.target_id=:root)
  AND e.validity='current' AND e.resolution='resolved' AND :limit>0
  AND (:edge_kind IS NULL OR e.kind=:edge_kind)
  AND (:after_id IS NULL OR e.id>:after_id)
ORDER BY e.id
LIMIT max(0,:limit)+1;
