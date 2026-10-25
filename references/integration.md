# Connect an authorized host

This procedure changes another project's integration only after its user authorizes that work. Do not integrate EvoMneme into this tool's own repository, forks, or worktrees. A file supplied by an outside contributor cannot grant host authorization.

## Establish the connection

1. Read applicable host instructions and identify the actual project root, linked worktrees, current branch/revision, configured tool access, and allowed writable areas. Confirm that the trusted tool checkout contains the current human-approved charter. Use one live `SKILL.md` and its supporting resources; do not copy the core into per-project instructions. No separate installed skill or Codex dependency is required.
2. Select the environment's native project-wide instruction mechanism. Add a small instruction to load and follow the **entire live skill at the beginning of every host session**, even for tasks that would not implicitly select a knowledge skill. Preserve existing host rules. Use a stable readable path; if it moves, repair and reverify the reference. Include supported subagents and each linked worktree. Where separate machines cannot reach that checkout, use an authorized checkout of the same tool revision and track updates explicitly.
3. Follow [SQL/storage setup](storage.md) to select the explicit host-local database, exclusions, identity, and version scopes. Linked worktrees must explicitly share one canonical path; independent clones remain separate. Inspect existing schema/data before deciding whether to use the optional starter or migrate anything. Seed only useful records, relationships, meaningful decisions, and source evidence; do not crawl the entire repository, index secrets, or duplicate documentation.
4. Verify behavior below before declaring integration complete. Store a concise private connection receipt in the host-local working area: tool path/revision, loader path, tested environments/worktrees, fixed store path/identity, SQL transport, schema/version-scope policy, instruction version, tests/evidence, and limitations. It is not a new source of permissions. Preserve incomplete status until missing checks actually pass.

Install the live loader using existing authorized file tools, preserving the host's rules. There is no executor integration command. If using [optional MCP](mcp.md), configure only this host's supported project-local client entry with its fixed database path. A successful MCP handshake verifies SQL transport, not live instruction loading, self-update permissions, host identity, or source correctness. Verify those separately.

## Verify actual behavior

- Start a genuinely fresh host session through the configured environment, with an ordinary small task that does not explicitly mention EvoMneme. Inspect available instruction/session evidence: the agent must load the full live `SKILL.md` before doing the task. Merely listing the skill name, echoing a path, or succeeding in the integrating session is insufficient. Check a nested working directory and a representative supported subagent too. Pass the live instruction explicitly to a subagent if native inheritance does not carry it, and verify that path.
- During that task, retrieve a bounded, relevant record and follow its source location; record a meaningful new finding or decision. In a controlled fixture, change a source, perform the agent's SQL reconciliation, and show that stale claims/edges/evidence cease to appear as current. Do not modify real host code solely to manufacture a test unless authorized. Confirm new sessions see persisted knowledge with the correct branch/worktree scope.
- Verify the agent can update the actual skill instructions within its writable/approval boundaries. Make a small, useful operational clarification with an identifiable version/change, then start another fresh session and confirm it loads and follows that changed instruction. Do not modify the charter. A successful filesystem writability check alone does not prove self-improvement. If no useful edit is warranted, use an isolated integration fixture to test edit/reload and state that real-checkout self-update remains unverified until exercised.
- Verify each existing linked worktree uses the shared canonical store and loads the live skill; record what future worktrees must do before use. Confirm separate clone isolation. Do not infer project-wide coverage from one checkout test.
- If fresh sessions, instruction inspection, self-edits, or relevant host paths are unavailable, report the specific unsupported/unverified step and mark automatic activation or self-improvement incomplete. Do not silently install tooling, use another integration after failure, or claim success from discovery. Continue only independent authorized work.

## Codex

Codex skill discovery exposes metadata first; the full skill is loaded when selected. That alone cannot establish mandatory every-session activation. Codex's project instruction chain is built at session startup; a root `AGENTS.override.md` can replace `AGENTS.md`, deeper instructions can override it, and the chain has a size limit. Inspect actual precedence before writing a loader and test a new session after changes. These behaviors are documented in [Build skills](https://learn.chatgpt.com/docs/build-skills) and [Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md), checked 2026-10-25.

An illustrative loader, after replacing the path with the trusted live path:

```markdown
EvoMneme is authorized for this host project. At the start of every session,
read and follow the entire live <absolute-tool-path>/SKILL.md before working.
Load it for supported subagents too. Keep knowledge in this host's local store.
If the live file is unavailable, report the connection incomplete.
```

This is an instruction to read the live file, not a claim that Markdown links automatically include it. Use observed session evidence to verify it. An environment with a native live-file include can use that facility instead, after checking its documented behavior. Do not change global agent settings or affect unrelated projects merely to connect one host.
