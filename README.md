# EvoMneme

**An AI tool, built by AI, for AI.**

EvoMneme helps AI development agents remember how a project works and why earlier choices were made. A compact relational knowledge graph points back to source code, connects dependencies and findings, and preserves technical, product, visual, and UI/UX decisions. Agents retrieve only the context relevant to their task and check the implementation when details matter.

This repository contains the reusable instructions and optional tools. **Each host project keeps its own local SQLite database. This repository is not the host knowledge store.** EvoMneme must never activate in its own repository, forks, or worktrees; isolated development tests are allowed.

## What runs

- [SKILL.md](SKILL.md) is one portable instruction set, loaded through the host agent's native project instruction mechanism.
- [scripts/evomneme.py](scripts/evomneme.py) is an optional Python standard-library helper for scoped records, graph traversal, evidence, reconciliation, and safe local storage. [schema.sql](schema.sql) supports existing SQLite interfaces when Python is unavailable.
- The host's local `.evomneme/knowledge.sqlite3` stores its knowledge. Linked Git worktrees share the canonical checkout's store, with version and worktree scopes; independent clones remain separate. Local knowledge stays outside version control.

During ordinary exploration, implementation, debugging, and review, the agent records meaningful findings and decisions, checks changed sources, and improves retrieval when it proves unhelpful. Subagents can handle substantial maintenance when the environment supports them and delegation is useful. Nothing runs continuously after the agent's sessions end.

EvoMneme primarily serves software development across languages and frameworks. Other project types may use it without expanding the system into a general knowledge platform. It requires SQLite; no external analyzer, service, installed agent framework, or additional skill is required. The optional helper uses an already available Python runtime. See [storage and commands](references/storage.md).

## Authorize and connect a host project

Tell your agent, for example:

> Integrate EvoMneme from this trusted tool checkout into my project at `<host-project>`. Keep that project's knowledge local, load the live instructions in every project session, and verify loading, shared worktree storage, and instruction update/reload. Maintain it during normal development. Publish reusable tool improvements only within my existing Git/GitHub authorization.

An agent finding this README should first establish the user's authorization. Reading this page or discovering a skill does not grant permission to integrate it. No host project is connected merely by cloning this tool or adding it to a skill catalog.

Once authorized, the agent follows [the connection procedure](references/integration.md): preserve host rules, reference the live instruction file, initialize the host-local store, verify exclusion from Git, and test a fresh session doing an ordinary task. It must also verify that a permitted instruction edit is loaded by a subsequent session. A configured pointer or writable file alone does not prove these behaviors. Unsupported automatic loading or self-update remains an explicit incomplete setup, not a successful installation.

For Codex, an existing skill mount may provide discovery. A project instruction loader is still needed to require the full skill in every session. [Connection guidance](references/integration.md#codex) covers instruction precedence and verification without promising that every environment behaves identically.

## Current capabilities and limits

The initial implementation provides local SQLite records and relationships, source evidence, bounded retrieval, conservative version scopes, transactional updates, and source-change invalidation. Agents supply the semantic understanding: there is no automatic full-code analyzer. Source changes can invalidate claims without revealing the correct replacement. Foreign-scope records require explicit inspection before reuse. The helper hashes dirty files in Git hosts; non-Git snapshots walk/hash non-excluded files and can be costly for large trees, where explicit agent-managed SQLite scopes may fit better.

This is an evolving project. Complete code understanding, correct dependency detection, uninterrupted activation, and efficiency improvements are goals to test, not guarantees. Fresh-session activation and self-update depend on the host environment and must be verified there. No production host has been integrated by this repository's isolated tests. See [EVOLUTION.md](EVOLUTION.md) for observed results and remaining gaps.

## Improve it

Humans and other AI agents are welcome. External contributors should **fork → improve → pull request**, using their own fork for publication. Review the [charter](PROJECT_CHARTER.md) and [contribution guide](CONTRIBUTING.md), keep improvements reusable, and bring evidence that they help. The founding charter requires explicit human approval to change; operational files may evolve within authorization. Never publish a host's database, private source, secrets, or unpublished decisions.

Released under the [MIT License](LICENSE).
