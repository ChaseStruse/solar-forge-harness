# Harness code review

Reviewed implementation commit: `978ca54` (mandatory request bundles plus the existing harness).

The separation of provider adapters, workflow, audited execution, and terminal presentation is useful. Approval digests, read-before-write checks, bounded prompts, and persisted pending actions already have regression coverage. However, the following reproduced findings prevent an unqualified clean bill of health.

## Findings, in priority order

### F1 — P1: A supported attachment name breaks global run discovery

Locations: `src/solar_forge/chat.py:72`, `src/solar_forge/chat_workflow.py:157`, `src/solar_forge/cli.py:99`.

All three discovery paths glob `agentic_audit/*/*/state.json` and pass every match directly to `Audit.open`. A user can legitimately add `agentic_audit/requests/default/state.json` as supplemental context. Discovery mistakes the request folder for a run, and `Audit.open` rejects its path. This makes `forge status` fail and prevents the terminal chat from starting because its constructor refreshes chat history. The attachment does not even need to contain malformed JSON.

Reproduction F1 confirms that chat listing raises `Run must be agentic_audit/<request-slug>/<run-id>` and status exits 1.

Recommended fix: centralize run enumeration and validate the complete run-path shape before opening candidates. Distinguish malformed actual runs from unrelated request attachments; report corrupt runs without disabling every other run. Keep historical run locations compatible. Add integration coverage for both request attachments named state.json and valid runs whose title slug is `requests`.

### F2 — P2: The model write path bypasses the mandatory request location

Locations: `src/solar_forge/agent.py:60`, `src/solar_forge/workspace.py:45`; coverage gap at `tests/test_agent.py:82`.

CLI request creation and preparation validate the new layout, but the coding agent's `write_file` action still accepts `request.md` at the project root. Only the selected bundle, configured context, and protected directories are blocked. A model can therefore create request artifacts outside agentic_audit during an otherwise approved run. This violates the new mandatory organization rule. The test named `test_plan_tamper_and_policy_edit_rejected` sends precisely this write but only checks that the bundled request is unchanged, so it misses the extra root file.

Reproduction F2 confirms a root request.md is written and the run reaches review_required.

Recommended fix: enforce reserved request/artifact destinations in the agent write policy as well as the user-facing entry points. Define which artifact names are reserved so legitimate application files remain editable, and provide a dedicated internal audit-artifact operation if models need to write request-specific plans or notes. Strengthen the regression assertion to check that forbidden destination files were never created. Prompt instructions alone do not enforce this rule.

### F3 — P2: Permanent prompt errors leave chat without an in-session recovery path

Locations: `src/solar_forge/chat.py:96`, `src/solar_forge/chat.py:118`, `src/solar_forge/chat.py:140`.

Chat saves pending_message before collecting context and checking the prompt budget. If the assembled prompt exceeds max_prompt_bytes, the message remains pending even though no provider call occurred. Retry reconstructs the same oversized prompt. The command dispatcher rejects every command while a message is pending, including /cancel and /status. The terminal also intercepts new input at this point. The user must abandon the conversation or change external configuration/context to proceed; shortening the message in chat is impossible. Long command histories can also cause this with normal budgets because complete history is sent on every turn.

Reproduction F3 uses a small valid prompt budget to make the failure deterministic: send and retry fail, cancel and status are blocked, and provider calls remain zero.

Recommended fix: distinguish local preflight rejection from retryable provider failure. Return an unsent draft to the composer after preflight failure, or offer an audited discard/edit-pending action allowed by both the service and terminal. Preserve the history and selected coding run. Add tests for budget overflow after existing conversation history, and for recovering without creating a new chat.

### F4 — P2: CLI provider/model changes produce inaccurate execution provenance

Locations: `src/solar_forge/cli.py:120`, `src/solar_forge/cli.py:137`, `src/solar_forge/workflow.py:42`.

The CLI permits --provider/--model overrides when discovering, planning, or executing an existing run, but it neither verifies them against the saved identity nor records a change. Run state retains the original provider/model, and provider call records contain only system/messages, without the actual provider/model/endpoint. Chat does reject a different provider/model, so the entry points also disagree. An audit cannot reliably identify which model produced later actions after a CLI override or configuration edit.

Reproduction F4 substitutes the HTTP adapter offline: the CLI executes using model `replacement`, but state.json continues to report `original`.

Recommended fix: decide explicitly whether model switching within a run is supported. Either reject mismatches consistently or log an explicit transition. In both cases snapshot the actual non-secret provider identity, model, and endpoint on every call. Never record API keys. Test the CLI override path and configuration changes between prepare, plan, and run.

## Suggested improvements after the fixes

1. Put run enumeration, provider identity checks, and request selection behind shared helpers used by CLI and chat. The duplicated entry-point logic contributes directly to F1 and F4.
2. Validate complete persisted state schemas and introduce explicit migrations. Audit.load currently checks only version; incomplete state and drafts written by older versions can fail later with unhelpful KeyError exceptions. Report a recoverable diagnostic without hiding healthy runs.
3. Add a request-list/select command that displays paths, titles, and starter-template status. Setup leaves a default bundle, so creating another request makes implicit CLI preparation ambiguous. Make selection easy without requiring users to memorize paths.
4. Extend fault-injection coverage around checkpoint boundaries and concurrent writes. Existing tests simulate one interrupted write; failures between journal creation, replacement, event append, and state save deserve explicit recovery contracts. Per-run locks do not serialize two different runs editing the same project file.

## Verification and scope

- Required command: `PYTHONPATH=src python -m unittest discover -s tests -v`.
- Result: all 60 tests pass. A temporary environment supplied the declared prompt_toolkit dependency; the local HTTP integration test ran with loopback networking permitted.
- Four additional offline probes reproduce F1–F4. Run `PYTHONPATH=src python agentic_audit/requests/harness-code-review/reproduce.py`.
- Evidence: `tests.txt`, `reproduce.py`, and `reproduction-results.txt` in this folder.
- Inspected source modules for requests, context, workspace boundaries, audits, workflow, agent execution, provider adapters, setup/configuration, CLI, chat service/workflow, and terminal UI, together with existing tests and documentation.
- No live hosted-provider calls or manual interactive terminal session were performed. Existing HTTP adapter tests and terminal UI tests do not establish compatibility with every live model/service.
- This review records findings and recommendations; production code was not changed as part of the review.

## Commit checkpoints

- `978ca54`: previously completed mandatory request-bundle implementation.
- `8a93233`: review request and scope.
- `e42ae49`: runnable reproductions and regression-test evidence.
- This report is committed separately as the final review deliverable.
