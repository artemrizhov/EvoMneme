# Navigation validation and limits

This records isolated development evidence for the [navigation CLI](navigation.md). It is optional reading, not normal task context. No host database or prior host experiment was changed. Launchers were installed only in excluded test fixtures; the tool repository was not integrated as its own host.

## Implementation checks

The final targeted run of `python -m unittest discover -s tests -p 'test_navigation*.py'` passed **22 tests**: 12 navigation and 10 setup tests. During implementation, the full Python suite passed 141 tests before the final launcher/copy-command corrections; after those corrections the affected navigation suite was rerun, rather than repeating unrelated viewer/website tests. Scoped whitespace checks and 109 relative documentation links/anchors passed.

The targeted cases cover real-root gaps, current scope/endpoint joins, title/ID ambiguity, meaningful and qualified arguments, confidence and evidence validity, both directions, parallel relationships, self-loops, exact count/list parity, 31 matching cards, high-degree output handling, read-only database hashes and a concurrent WAL snapshot. A 61-link root overview and 31 cards fit the 64 KiB normal output guard. Oversized output produces no partial stdout and a complete-output retry. Native tests execute the returned neighbor command and the oversized-response retry, not merely a separately reconstructed equivalent.

Setup cases cover receipt-field preservation, nested discovery, wrong/copied bindings, missing identity metadata, freshness warnings, isolated actual Git worktrees and independent clones, including a scope belonging to the linked checkout itself. Native Windows PowerShell launches the installed command from nested fixture directories and through pipelines, preserves exit status, and leaves database bytes unchanged. One combined name contains a leading dash, embedded double quotes, an ampersand, an apostrophe, `%PATH%` and Unicode. The actual returned commands preserve this name.

Independent review found defects that the first checks missed: a CMD launcher expanded percent expressions and lost quotes; an initial fixture had mismatched canonical/project roots; and scope checks rejected a valid linked checkout's own scope. The corrected PowerShell launcher transports arguments internally to the existing Python without CMD parsing, new dependencies or execution-policy changes. Ready commands on link rows and output-guard retries now use that installed launcher too. Fundamental identity checks remain strict, while source freshness is a warning. These are concrete regression cases, not proof that every shell or future name is supported.

Some Windows sandbox runs rejected loopback access, Git's local clone helper or PowerShell activation. The same configured-tool commands passed after narrow sandbox escalation. No execution-policy bypass flags, global PATH/profile/registry changes, user-environment install or runtime installation were used. Native POSIX execution was unavailable; POSIX wrapper/activation text was checked statically only. If policy blocks scripts in another environment, setup remains incomplete rather than weakening the policy.

## One fresh-agent CLI observation

A fresh Sol agent without conversation history was instructed to investigate a checkout timeout followed by a form edit and a retry. It received the current skill/navigation instructions, an isolated already-connected fixture, its source working directory and explicit session activation. It was not supplied responsibility IDs/titles or file locators, and was forbidden to inspect implementation, tests, generators, previous probes or database contents directly. It used the documented root/name route and source evidence; no agent-authored SQL, schema query or MCP call was needed.

The first result and raw combined tool outputs were preserved locally under `.evomneme-tests/navigation-probe/cli-observation/cli_probe/`, excluded from Git. The fixture database and source files were not subsequently rewritten. Independent parsing of `observations.json` produced `metrics-reviewed.json`:

| Observed item | Result |
| --- | --- |
| Successful navigation | 10 calls: 3 `nodes`, 7 `links` |
| Initial failed activation attempt | 1; CLI did not run |
| Successful output | 21,548 UTF-8 bytes, including headers/warnings/completion |
| Failed activation output | 882 UTF-8 bytes |
| Root count/list | Card: 5 relationships; root list: 5 rows |
| Scope/completion | All 10 successful outputs used `synthetic-current` and had completion markers |
| Two-name `links`, ambiguity and oversized retry | Not exercised by this agent; covered by implementation tests |
| Source inspection | Four files, hashes matching the cards |
| Database | SHA-256 unchanged from the pre-probe fixture baseline |

The agent's first answer identified pending-before-draft lookup, stable request identity, the intended saved-state/outbox transaction boundary, sending after persistence and acknowledgement after successful sending. It described changes that could break byte reuse. It explicitly left remote delivery/exactly-once processing unverified and stated assumptions about the caller's ID reuse and the send/timeout boundary. It did not run source behavior tests. It wrote a handoff packet; another recipient's use of that packet was not tested.

Evaluator qualification: the first answer's transaction wording was stronger than the inspected evidence. Reading `with self.db` on an injected connection identifies the intended boundary; actual grouping, commit and atomicity guarantees depend on that connection's unverified transaction configuration. The observations explicitly list that configuration as unverified, but this does not make the stronger transaction phrasing proved. The first answer and fixture remain unchanged. Successful navigation and accurate count/list handling do not eliminate this source-contract reasoning gap.

The first sandbox activation failed with an AuthorizationManager error and command-not-found output, although the outer shell returned zero. The identical same-tool invocation outside the sandbox succeeded. That first attempt remains in the evidence and is not counted as a CLI success/error because navigation never started. The initial launch prompt also abbreviated the documentation path incorrectly as `refs/navigation.md`; the agent encountered that missing path and followed the actual live skill link to `references/navigation.md`. This documentation-read error remains recorded.

The agent explicitly activated the same fixture in each child PowerShell invocation, rather than demonstrating a persistent activated session. The native installation tests separately exercise command-directory setup, but this trial does not prove one-time setup in every future agent shell. Git freshness was intentionally unavailable and remained visibly warned throughout; receipt-based scope discovery was not tested because the binding was already supplied.

The fixture retained a separate documented source root and used a nested source working directory. Stored locators were relative to that source base, while the navigation connection's project root was one directory above. Thus this trial verifies files using the supplied source base; it does not show that CLI output alone establishes a relative locator base or that these fixture paths are project-relative. Future fixtures can improve that convention without retroactively changing this first observation. Product output preserves stored locators and still requires host path conventions/source verification.

## What the numbers do not establish

The recorded instruction files account for 30,559 on-disk bytes, source files for 1958 bytes, the preserved launch prompt for 3470 and the handoff for 1645. Recorded shell command strings total 3454 bytes, while their short human-facing CLI portions total 605. These representations exclude or overlap other tool/caller overhead and are not an exact delivered-context total or token estimate. Observed tool wall time was 15.874 seconds for all attempts, including 11.064 seconds for successful calls; this includes repeated shell activation and is not a performance-saving result.

This is one **instructed synthetic usability observation**, with a curated real root and explicit activation/source base, not spontaneous adoption or a matched control trial. The earlier SQL-recipe observation used a different task/instruction setup and must not be treated as a before/after efficiency comparison. Normal navigation demonstrably avoided agent-authored SQL in this route; total cost, application correctness, root quality on other projects and prevention of inherited-boundary mistakes remain unproven.

The ordinary guard is an output-size safeguard, not a guarantee about source completeness or arbitrary graph-query cost. `--all` still has an execution deadline and currently buffers the full text in memory; it is not an unlimited-store streaming guarantee. Counts from separate commands may change with concurrent maintenance. Read-only inspection cannot repair missing/stale graph data or infer disconnected architectural responsibilities.
