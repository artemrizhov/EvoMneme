-- Full selected current node detail, including pathless knowledge nodes.
SELECT scope_id,id,kind,layer,title,summary,confidence,validity,
       source_path,source_hash,line_start,line_end
FROM nodes
WHERE scope_id=:scope AND id=:id AND validity='current';
