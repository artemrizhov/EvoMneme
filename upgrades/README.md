# Host integration contract upgrades

Required contract: **1**. Required database schema: **3**. Runtime constant:
`scripts/evomneme_contract.py`. These versions are independent of receipt format
`version: 1`, source revision, instruction edits, and SQLite's internal schema
cookie. Bump the contract **only when an existing authorized host must change
its database/data, configuration, launcher, loader or integration instructions**.
An ordinary compatible runtime/skill fix needs no contract bump. Schema changes
follow the separate published schema/migration policy and also bump this contract
when hosts must act.

Publish one immutable numbered transition for every increment, including concrete
checks, migrations/semantic updates, constraints, verification and recovery.
Never rewrite a published transition to demand new work: publish the next one.
Keep the required version here, in the live skill and runtime constant aligned.
Transitions: [unversioned → 1](0001-integration-tracking.md).

## Agent procedure

1. Read the entire live skill and private `.evomneme/connection.json`. Revalidate
   host authorization, identity, canonical database, scope/root and actual schema.
   Missing versions mean **unknown**, not current and not proof of an old schema.
   Corrupt state requires inspection/recovery; a future contract requires the
   matching newer tool, never receipt editing or a downgrade.
2. Read every intervening transition, in numerical order. Inspect the host's
   existing data conventions, configuration, launcher and effective live loader.
   Complete its published changes within existing authorization. Use applicable
   published schema migrations only; make dated local backups before changes.
   Keep unrelated receipt fields and host knowledge. Runtime success proves no
   semantic upgrade or instruction loading.
3. Verify each step's effects. Record concrete evidence and honest limitations,
   then accept **one transition at a time**, for example after initial inspection:

   ```text
   evomneme accept-integration --from-version unversioned --to-version 1 --verification "Actual host checks, completed changes, evidence and limitations"
   ```

   For subsequent transitions use the previous integer as `--from-version`.
   The command validates real binding, root and controlled schema before writing;
   its verification text is an **agent attestation**, never a machine proof of
   semantic completion. Do not invoke it while required upgrade work remains.
4. The command atomically replaces the receipt, preserves other fields, and
   refuses a changed predecessor/receipt. Interrupted work leaves the old accepted
   version until replacement. Reinspect completed steps and actual state before
   resuming; avoid replaying destructive migrations. If replacement completed
   before output was interrupted, read the receipt/history before retrying.
   Concurrent agents must serialize acceptance and receipt edits; the final
   compare-and-replace is not a multi-process lock and has a narrow race window.

If blocked, explain the blocker, known limits and consequences of continuing,
and a concrete recovery/resumption path. Ask whether the user wants to pause and
resolve it or continue without migration. Preserve the old version and warning
until completion. Continuing grants no incompatible-schema access, failed-tool
bypass or extra permissions.

## Diagnostics, streams and coverage

The checker reads a bounded local JSON receipt (up to 256 KiB), path metadata and
in-process constants. It adds no Git/subprocess, SQL/schema scan, hashing, network
or transition-file parsing. Existing source freshness Git calls remain separate.
It checks accepted contract and *recorded* schema only; actual schema validation
continues independently on controlled graph/viewer routes and during acceptance.
Hand editing current numbers cannot certify migration or suppress agent duties.

Bound `evomneme` invocations (navigation, mutations, diagnostics, references,
chains, connect, install and acceptance) diagnose before argument parsing,
dispatch or errors, once per invocation. Direct `discover` and setup paths also
check. SQL CLI, viewer and journal CLI and website export check explicit database
bindings; direct Python Executor construction/each `execute_sql`, Explorer
construction/viewer POST requests and export API also report matching receipts.
The first diagnostic is flushed to **stderr**; stdout text/JSON and returned
Python/HTTP result shapes remain unchanged. Callers must retain stderr as well
as stdout. Viewer request diagnostics use server stderr, not HTTP JSON.

Standalone database routes find a receipt from the current project or beside a
database in `.evomneme`, and require its database path to match. Unbound or foreign
SQL databases remain generic: no receipt is created, modified or stamped. A
managed store elsewhere with no discoverable receipt cannot report host contract
status; inspect its explicit host receipt in the agent workflow. Low-level
helpers taking an already-open SQLite connection, SQL migration files, browser
assets and static website build do not independently locate hosts. They are
covered by their invoking tools/agent procedure, not a universal SQL interceptor.
