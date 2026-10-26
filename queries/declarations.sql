-- Deliberate code-file inventory after selecting an implementation boundary.
-- Set executor max_rows=:limit, with positive limit.
SELECT scope_id,id,kind,layer,title,summary,confidence,validity,
       source_path,source_hash,line_start,line_end
FROM nodes
WHERE scope_id=:scope AND layer='code' AND validity='current'
  AND source_path=:source_path AND :source_path<>'' AND :limit>0
  AND (:kind IS NULL OR kind=:kind)
  AND (:after_id IS NULL OR id>:after_id)
ORDER BY id
LIMIT max(0,:limit)+1;
