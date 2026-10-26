# Retrieval evaluation and limits

This records isolated development checks, not a performance guarantee or a host integration. The operating procedure is [task retrieval](retrieval.md); agents do not need this history during ordinary work. No private host code, databases or logs are used in these fixtures.

## Repeatable SQL and source checks

Run from the tool checkout using the existing Python/SQLite environment:

```text
python -m unittest discover -s tests -p test_retrieval.py
python -m unittest discover -s tests -p test_architecture_retrieval.py
python -m unittest discover -s tests -p test_schema.py
python tests/test_retrieval.py --compare
```

By default, the architecture fixture builder creates its database, source copies and neutral receipt inside excluded `.evomneme-tests`; it refuses to overwrite existing output. If selecting another output path, keep it excluded and within the authorized project area:

```text
python tests/fixtures/orientation/build_fixture.py
```

The receipt includes source root, scope/schema/snapshot and two task texts, without answer IDs or titles. Expected maps are in evaluator tests, not the receipt. Source templates establish raw draft editing, explicit admission, wire encoding, a transaction containing saved state and outbox, and replay of pending bytes after a timeout before acknowledgement. They do not implement a remote service or prove restart/concurrency/delivery guarantees. The catalog has six current knowledge architecture cards, pathless decisions, cross-module links, an uncertain responsibility without an implementation, alternate/stale observations and unrelated code with matching task words. Unit-test mutations cover absent architecture and missing edges. A missing match or relationship must remain a gap.

Nine lexical retrieval tests and eleven schema tests passed. The initial architecture suite had eight tests. Two further regressions brought it to ten after a probe exposed the missing audit-parent problem described below. They cover knowledge/code separation, pathless nodes, exact file-entry selection versus explicit declaration enumeration, scope/validity, confidence, direction, clipped previews/full detail, bounded pages, negative cases, actual synthetic source behavior and the read-only audit helper. Scope rows in the fixture share branch/revision/snapshot metadata: scope tests check isolation/paging, not successful human or agent disambiguation from that metadata.

## Lexical selection versus graph expansion

The original comparator deliberately puts twelve substring distractors before a relevant exact title in ID order. Both routes receive the same task term and scope, project the same anchor columns and use `max_rows=8` / `max_output_bytes=12000`. Required IDs are defined by the fixture without supplying an oracle seed ID to the new route. This exposes a failure mode rather than representing a typical workload.

| Synthetic term | Irrelevant seed hits, substring → exact | Required entities found, substring → expanded | Result bytes, substring → all new calls | Calls |
| --- | --- | --- | --- | --- |
| billing | 8 → 0 | 0/2 → 2/2 | 1370 → 1674 | 1 → 3 |
| session | 8 → 0 | 0/2 → 2/2 | 1378 → 1674 | 1 → 3 |
| policy, missing edge | 8 → 0 | 0/2 → 1/2 | 1386 → 1001 | 1 → 2 |

A reasonable exact lexical query (`title=:query`) with the same scope/projection/budget returns the same rows and bytes as anchor-only retrieval:

| Synthetic term | Exact lexical = anchor-only | Anchor + hop | Anchor + hop + selected evidence |
| --- | --- | --- | --- |
| billing / session | 424 bytes, 1 call, 1/2 required | 1283 bytes, 2 calls, 2/2 | 1674 bytes, 3 calls, 2/2 |
| policy, missing edge | 422 bytes, 1 call, 1/2 | 1001 bytes, 2 calls, 1/2 | 1001 bytes, 2 calls, 1/2 |

Bytes count compact UTF-8 shared result objects for every call, including empty/evidence responses. Requests, instructions and MCP wrappers are excluded; this is not model-facing context or a token estimate. Good predicates account for noise reduction. Relationships add a stored decision outside the lexical match at extra cost; selected evidence adds provenance. This does not compare effort to equally sufficient context through good source search versus graph navigation, and does not test discovering differently named responsibilities.

## One fresh-agent orientation observation

A fresh Sol agent with no conversation history received the public skill/retrieval instructions, the fixture receipt and a generic audited SQL launcher. It investigated only the first task: explain safe confirmation-only parcel-reference normalization while preserving raw draft and atomic saved-state/retry behavior. It was not given graph answer IDs, exact architecture titles or source locators. Generator, tests, source templates, previous answers and evaluator expectations were forbidden. Only generated source copies could be read. The launcher uses the released Executor with history disabled and `query_only`; it logs requests, complete results and database hashes.

Observed route: read the type-only catalog, choose responsibilities by meaning, expand selected full descriptions, follow incoming implementation and constraint relationships, then inspect four source files and compare their hashes. The six-card catalog cost 1645 shared-result bytes; all previews were clipped and the agent successfully reached full details. It reused the supplied scope/schema rather than issuing PRAGMA or guessed-column discovery. Thirteen recorded calls returned 13,626 result bytes with no recorded SQL/schema errors, no incomplete pages and unchanged database hashes. Three selected evidence-table lookups were empty; the agent explicitly relied on source locators/hashes and direct reading instead of claiming attached evidence existed.

The first final answer identified the encoding change point, raw edit boundary, pending-before-prepare ordering and transactional saved/outbox boundary. It left UI wiring, injected connection configuration, crash durability and remote deduplication unverified. It generated a reusable context packet, but no second recipient was tested; actual handoff adoption remains unmeasured. Only task zero was run: the second task in the receipt is available for later evaluation, not a second successful trial.

One earlier launcher attempt failed because the audit parent directory was absent. That attempt has no structured audit record; its original command/error and the first final answer were preserved separately. It is excluded from the thirteen recorded-call metrics, so those metrics are incomplete for the whole attempt sequence. The helper was subsequently fixed to create/open the audit destination **before constructing the Executor or executing SQL**, with regressions for missing directories, unavailable audit and database-path misuse. The first probe was not rerun or rewritten after that fix.

Independent audit parsing reproduced 13,626 compact UTF-8 result bytes and 12,815 compact request bytes. The probe reported 42,415 on-disk bytes across full instruction/query/receipt/source files read; its preserved launch prompt is 3114 bytes and handoff 4453 bytes. These are different content representations, not an exact model-delivery measurement or a complete additive cost total. Wrapper text, repeated audit reading and the unaudited first attempt add unmeasured overhead. No token, time or total-context saving is claimed. Raw request/result and preserved prompt/final/error records remain local under `.evomneme-tests/orientation/probe-1/`, excluded from Git. Repeating a fresh-agent observation requires recording the new prompt/version and keeping the first result intact.

This is **instructed synthetic usability evidence**, not independent generalization: the operating guide's parcel example closely mirrors task zero and explicitly suggests commit/draft/delivery concepts. The launch asked the agent to use current instructions; it did not name `architecture.sql` as the first query, but spontaneous choice of this workflow in ordinary development was not tested. The supplied receipt removed scope discovery. Catalog quality is curated, architecture coverage is small, and no matched control agent or application change was evaluated. The observation shows one agent could execute the documented route and distinguish local source guarantees from unverified external behavior. It does not establish improved application correctness, prevention of inherited-validator regressions, reliable future adoption or lower cost.
