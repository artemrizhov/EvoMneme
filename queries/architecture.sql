-- Paged semantic orientation; no task keyword or physical path predicate.
-- Set executor max_rows=:limit, with positive limit. Preview is character bounded.
SELECT scope_id,id,kind,layer,title,
       substr(summary,1,:preview_chars) AS summary_preview,
       length(summary)>:preview_chars AS summary_truncated,confidence,validity
FROM nodes
WHERE scope_id=:scope AND layer='knowledge' AND kind=:kind AND validity='current'
  AND typeof(:preview_chars)='integer' AND :preview_chars BETWEEN 0 AND 240
  AND typeof(:limit)='integer' AND :limit BETWEEN 1 AND 32
  AND (:after_id IS NULL OR id>:after_id)
ORDER BY id
LIMIT max(0,:limit)+1;
