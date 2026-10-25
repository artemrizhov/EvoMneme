# Host-local storage and commands

Use this reference to initialize, retrieve, update, reconcile, or recover an **authorized host's** knowledge. Never point the helper at EvoMneme itself, its forks, or worktrees. Isolated synthetic host fixtures are permitted for development.

## Optional helper

Use an already available Python 3.11+ with its standard-library SQLite support. Examples use shell-neutral placeholders; quote actual paths for the configured shell. Run the script from the trusted tool checkout and give the host explicitly:

```text
python <tool>/scripts/evomneme.py --project <host> init
python <tool>/scripts/evomneme.py --project <host> status
python <tool>/scripts/evomneme.py --project <host> search "session" --limit 8
python <tool>/scripts/evomneme.py --project <host> traverse session-service --depth 1 --limit 12
python <tool>/scripts/evomneme.py --project <host> update <host>/.evomneme/batch.json
python <tool>/scripts/evomneme.py --project <host> reconcile
python <tool>/scripts/evomneme.py --project <host> verify
python <tool>/scripts/evomneme.py --project <host> integrate --skill <tool>/SKILL.md
```

`init` creates/validates the store and excludes local state from Git. Git hosts use the canonical main checkout's `.evomneme/knowledge.sqlite3`, shared through Git common-directory/worktree identity. Independent clones have separate canonical paths and stores. Non-Git hosts use the explicitly supplied directory as the project root. State already tracked by Git is rejected: inspect and untrack only the local state with proper authorization; never remove application files to satisfy setup.

Git scope calculation hashes changed and nonignored untracked files, without rereading clean tracked sources. For submodules it includes the indexed gitlink revision, initialization state, actual child HEAD, and recursive dirty/nonignored untracked content. It never initializes or fetches submodules. Non-Git scope calculation walks/hashes non-excluded files, skipping `.git`, `.evomneme`, `.evomneme-tests`, `node_modules`, `.venv`, and `__pycache__`; this may be expensive for large trees. At integration, prefer the SQLite-only workflow with explicit agent-managed scopes or existing environment change metadata for such hosts. Do not install an analyzer or silently switch routes after an integration failure.

Scopes distinguish branch, worktree, HEAD revision, and dirty content snapshot. Default retrieval includes only current records in the exact current scope; a commit or local change may therefore produce no hits. Use `--all-scopes` on `search`/`traverse` to locate earlier knowledge; results mark it `out_of_scope`. Read source and republish only verified claims into the current scope. `--include-stale` includes stale/superseded history for investigation. Neither flag makes an old claim current. Reuse stable semantic IDs within a scope to avoid duplicates; relations cannot cross scopes.

Search matches IDs, titles, summaries, and kinds as literal text. Traversal follows either edge direction and returns associated evidence. Defaults are 20 results and one hop; limits cap at 100 records, 100 relationships, 100 evidence rows and five hops, with summaries shortened to 600 characters. This is a locator, not semantic search or a completeness guarantee. Refine the query or inspect source when relevant context is missing.

## Atomic updates and evidence

Place temporary batch files under the host's excluded local area, or use `update -` with JSON on standard input. One batch upserts these arrays atomically; failed references or validation roll back the batch:

```json
{
  "records": [
    {"id":"session-service","kind":"component","title":"Session service","summary":"Owns session expiry and emits expiration events.","confidence":"confirmed","source_path":"src/session.py","line_start":12},
    {"id":"expiry-decision","kind":"decision","title":"Expire idle sessions","summary":"Chosen to limit unattended access; permanent sessions rejected for shared devices.","confidence":"confirmed"}
  ],
  "relations": [
    {"id":"session-expiry-policy","source_id":"session-service","target_id":"expiry-decision","kind":"implements","summary":"Idle expiry enforces the session policy.","confidence":"confirmed","source_path":"src/session.py"}
  ],
  "evidence": [
    {"id":"expiry-source","relation_id":"session-expiry-policy","source_path":"src/session.py","description":"Expiry handling inspected; verify behavior with the host's relevant test."}
  ]
}
```

The example is synthetic; substitute actual facts and paths. Each record needs `id`, `kind`, `title`, and `summary`; relationships need `id`, `source_id`, `target_id`, `kind`, and `summary`; evidence needs `id`, `description`, and exactly one of `record_id`/`relation_id`. Confidence is `confirmed`, `inferred`, or `uncertain` (default); validity is `current` (default), `stale`, or `superseded`. Optional record line numbers are positive and require `source_path`. Paths are host-relative regular files contained inside the host. Any path component named `.git`, `.evomneme`, or `.evomneme-tests` is refused; non-Git hosts also refuse `node_modules`, `.venv`, and `__pycache__` components because those trees lie outside snapshot coverage. Git-ignored files cannot be evidence; initialized submodule sources use that submodule's ignore rules. The helper calculates source hashes. Keep reasons and consequential alternatives in concise decision summaries and link the affected entities. Use evidence descriptions for observed behavior, user decisions, tests, and uncertainty when a source file alone is insufficient.

Marking evidence `stale` in an update immediately invalidates its target claim or relationship and affected dependent edges in the same transaction. Fresh claims require renewed source inspection and explicit updates; changing a confidence label does not repair stale evidence.

`reconcile` compares known source hashes across dirty snapshots with this worktree's current branch and HEAD, invalidates changed/deleted sources and claims backed by stale evidence, and invalidates relationships whose endpoints are no longer current. Other branches/revisions retain their observations; retrieval still labels them `out_of_scope`. Reconciliation cannot discover semantic dependents or fix statements automatically. Inspect changes and republish current claims with fresh evidence; a line number alone never proves validity.

For complex inspection, `sql "SELECT ..."` supports bounded read-only SQL; join `scopes` and filter `scope_id`/`validity` explicitly because raw SQL includes history. It blocks writes and file/extension access and bounds execution/row output. Ordinary updates should use the validated batch interface. For local self-assessment, capture a few relevant counters, task outcomes, or retrieval failures in the excluded working area; do not pollute the graph with mechanical logs.

For example, to inspect the decisions a component implements, bind or correctly quote the current scope ID reported by `status` and use:

```sql
SELECT d.id, d.title, d.summary, d.confidence, d.source_path
FROM relations e
JOIN records d ON d.scope_id=e.scope_id AND d.id=e.target_id
WHERE e.scope_id=:current_scope AND e.source_id='session-service'
  AND e.kind='implements' AND d.kind='decision'
  AND e.validity='current' AND d.validity='current'
LIMIT 8;
```

The helper's `sql` command takes SQL text rather than parameter values; substitute a correctly quoted value there. Existing SQLite interfaces can bind `:current_scope` directly. Extend graph queries around the actual host's vocabulary rather than treating the example relationship kind as mandatory.

## Safety, concurrency, and recovery

Writers use immediate transactions, foreign keys, WAL, and a bounded busy timeout. The helper rechecks the source snapshot before committing a batch and rolls back if it changed; reread the affected source before retrying. Retry a busy write only after coordination and reread records before overwriting another agent's conclusions. Partition logical ownership among sessions; do not assume database locking resolves conflicting meaning. State, batches, backups, WAL/SHM companions, receipts, and local feedback all remain excluded from Git.

`verify` checks SQLite integrity and foreign keys; it does not prove the graph's truth or activation. Before schema changes or recovery, stop writers and use an existing SQLite backup facility; verify the backup. Preserve the database and its WAL/SHM companions if corruption occurs. Never delete the only copy or silently downgrade a newer schema. Recovery may restore a verified backup or rebuild disposable locators from source; preserve valuable decisions/evidence before rebuilding and record losses. Respect the configured integration failure boundary.

The helper rejects symlinked state directories/databases and mismatched schema-version metadata. `init` migrates the compatible version-1 data shape to version 2 by adding evidence indexes; newer/unknown versions require inspection rather than a forced migration.

## SQLite-only operation

Python is optional. If it is unavailable, use an existing authorized SQLite shell/library and [schema.sql](../schema.sql); installing SQLite or its libraries is permitted within integration scope. Do not install Python, an analyzer, another skill, or a framework for this system. A failed configured integration requires reporting/authorization for alternatives; runtime absence identified during setup is not permission to bypass a failed integration.

Apply the schema only to an empty host-local database, after resolving canonical project/worktree identity and adding the local-state exclusion. Keep it private to the initializer until identity metadata is bound. Use the **same tables and invariants**, not a second knowledge model. Enable foreign keys and a 10-second busy timeout on each connection, WAL for writers, and immediate transactions for atomic batches. Supply `metadata.project_identity`, `metadata.canonical_root`, scopes, timestamps, and source hashes before storing claims. Scope IDs must distinguish branch, worktree, revision, and dirty snapshot. Verify host identity before every read/write and refuse implicit reuse after a clone or move.

For example, in the SQLite shell use `.read <tool>/schema.sql` on the new database, then bind the following named parameters using the interface's parameter facility. Commit identity before allowing other sessions access:

```sql
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=10000;
PRAGMA journal_mode=WAL;
BEGIN IMMEDIATE;
INSERT INTO metadata(key,value) VALUES
  ('project_identity',:project_identity), ('canonical_root',:canonical_root);
INSERT INTO scopes(id,branch,worktree,revision,snapshot,created_at)
VALUES(:scope_id,:branch,:worktree,:revision,:snapshot,:utc_timestamp);
COMMIT;
```

The helper's canonical hash encoding is defined in `Host.__init__` and `Host._snapshot`; reproduce it with existing platform facilities when sharing a database with the helper. SQLite-only agents may instead manage explicit stable project IDs and exact version/worktree scopes, but must record that choice locally: the helper will reject the different identity. Never mix identity schemes or import another host's store implicitly. If compatibility cannot be established, stop before mixing writers and report the limitation.

Use parameter binding or correctly quoted SQL literals, positive ordered source locations, enum checks, same-scope relationship endpoints, and exactly one evidence target. Resolve and hash source bytes inside the host; reject path/symlink escapes, ignored/private state, and missing evidence sources. Invalidate claims whose evidence changes and edges whose endpoints become stale. Restrict retrieval to the exact current scope and current validity by default, bound output, and visibly label historical results. Run read-only SQL with the interface's read-only mode and no extension/file functions; do not execute SQL supplied by stored data as instructions.

The portable schema declares its version in both `PRAGMA user_version` and metadata. Record significant local operations in `history`; maintain useful semantic feedback separately. Test initialization, a record/edge/evidence transaction, rollback, source invalidation, isolation, and bounded retrieval through the chosen interface before declaring the SQLite-only connection working. A missing SHA-256 or native instruction facility remains a concrete integration limitation; do not claim the shell path was exercised merely because the schema parses.
