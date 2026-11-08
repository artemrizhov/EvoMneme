# Transition 0001: inspect unversioned integration and record tracking

From: unversioned integration. To: contract **1**. Required schema: **3**.
No new schema or mandatory bulk graph rewrite is introduced by this transition.

1. Inspect the existing receipt without assuming its database/data is current.
   Verify authorization, project/canonical roots (including explicit linked
   worktrees), database identity, scope/root and actual metadata/user schema
   versions. Preserve the canonical knowledge store and unrelated receipt fields.
   For old schema use only compatible published [schema migrations](../references/schema.md);
   unsupported/custom/future stores block completion. Never relabel the schema.
2. Inspect host data against the current shared ID/path, vocabulary, description
   language and scope conventions in [code graph maintenance](../references/code-graph.md).
   Reconcile actual material inconsistencies using supported maintenance commands,
   preserve historical observations and document unresolved coverage. A convention
   already compatible needs no rewrite. This transition does not order a full
   reindex or erase prior knowledge. Record the inspection boundary and evidence.
3. Inspect effective native project instructions (for example AGENTS precedence),
   the live skill path, launcher and selected transport. Ensure all authorized host
   sessions and supported subagents load the **entire live** skill, including its
   mismatch/migration obligation. Replace copied/stale loaders only where authorized.
   Verify the integration behavior in [connection verification](../references/integration.md),
   including actual schema/viewer compatibility, shell/nested lookup and fresh
   instruction loading where supported. Preserve and report unavailable fresh-session
   tests or other environment limits as incomplete; never manufacture evidence.
4. Record meaningful performed changes, checks and remaining environmental
   limitations in the private receipt/verification notes. Confirm no required
   actionable migration/data/configuration/loader change remains. Then run
   `accept-integration --from-version unversioned --to-version 1 --verification ...`.
   The command stores accepted version 1 and verified schema 3 only after binding
   and schema validation; it cannot judge the truth of the agent's notes.

Before destructive or semantic updates, make dated host-local backups and retain
a step checkpoint. Resume by inspecting actual receipt/database/loader state;
repeat only idempotent checks, never blindly replay schema or data writes. If a
required step is blocked, follow the pause-or-continue procedure in the live skill
and upgrade index. Do not accept merely because current runtime calls succeed.
