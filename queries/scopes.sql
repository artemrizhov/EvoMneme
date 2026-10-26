-- Discover source/version boundaries; the caller must select applicability.
SELECT id,branch,worktree,revision,snapshot,created_at
FROM scopes
WHERE typeof(:limit)='integer' AND :limit BETWEEN 1 AND 32
  AND (:after_id IS NULL OR id>:after_id)
ORDER BY id
LIMIT max(0,:limit)+1;
