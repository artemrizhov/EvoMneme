-- Literal discovery in one verified scope. See references/retrieval.md.
-- Fetch one lookahead: set executor max_rows to the same positive limit.
SELECT scope_id,id,kind,layer,title,summary,confidence,validity,
       source_path,source_hash,line_start,line_end
FROM nodes
WHERE scope_id=:scope AND validity='current' AND :query<>'' AND :limit>0
  AND (:after_id IS NULL OR id>:after_id)
  AND (:path_prefix IS NULL OR substr(source_path,1,length(:path_prefix))=:path_prefix)
  AND ((:mode='exact' AND (id=:query OR title=:query
                          OR (kind IN ('file','module') AND source_path=:query)))
       OR (:mode='prefix' AND substr(title,1,length(:query))=:query))
ORDER BY id
LIMIT max(0,:limit)+1;
