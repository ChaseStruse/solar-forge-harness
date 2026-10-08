# Solar Forge implementation plan

## Objective

Build a Python CLI that turns a structured `request.md` into a documented,
interactive, provider-independent coding workflow. Project policy and recorded
human answers must govern architectural, deployment, and Git decisions.

## Architecture

- **CLI:** thin argparse entry point; readable prompts and resumable commands.
- **Domain:** validated requests, questions, workflow states, and configuration.
- **Context:** explicit project documentation plus bundled guidance, with a
  bounded inventory. File contents are data, not permission to execute actions.
- **Providers:** one text-completion protocol; OpenAI Responses, Anthropic
  Messages, Ollama chat, and OpenAI-compatible chat endpoints behind adapters.
  Model names are configuration, never embedded in orchestration.
- **Workflow:** discover → ask → plan → approve → execute → review. New domain
  uncertainties return control to the user before further changes.
- **Tools:** bounded project listing/reading/writing. No arbitrary shell, Git,
  or deployment execution in the baseline.
- **Audit:** `agentic_audit/<request-title-slug>/<run-id>/` contains immutable
  request/context snapshots, Markdown questions/answers/plan/summary, state,
  provider responses, tool evidence, and chronological JSONL events.

## Delivery increments

1. Commit this plan before implementation.
2. Build packaging, request template/parser, configuration, policy templates,
   context collection, and audit persistence. Test parsing and path boundaries.
3. Add provider adapters and the resumable question/plan workflow. Validate
   adapter payloads with mocked HTTP; do not require credentials for tests.
4. Add a bounded agent loop with explicit plan approval, project tools,
   interruption recovery, mid-run questions, change backups/diffs, and review
   output. Test the full workflow with a scripted offline provider.
5. Document installation, configuration, commands, limitations, and next steps;
   smoke-test the installed CLI and commit each coherent tested increment.

## Baseline acceptance criteria

- `forge init` creates a request template, project configuration, and editable
  coding, architecture, deployment, Git, and testing guidance without overwriting.
- `forge prepare` validates requests, snapshots context, and creates questions
  grounded in named documentation. No project edits happen during discovery.
- `forge answer` prompts in the terminal and records each answer immediately.
- `forge plan` blocks on unanswered questions; `forge run` presents that plan
  and records approval before permitting edits.
- All supported providers share the same orchestration and tool protocol.
- Each run has a collision-resistant directory and a recoverable state.
- Tools reject traversal, symlinks, credentials, policy/audit edits, and oversized
  files. Every attempted tool action and failed model call leaves evidence.
- The loop has a turn limit and returns a review artifact rather than claiming
  that unverified acceptance criteria have passed.
- Tests run offline with the Python standard library.

## Follow-up work

Streaming UI; native provider tool calls behind the common protocol; token and
cost accounting; context retrieval; OS-isolated command/test runners; explicit
Git/deployment approvals; stronger audit integrity; concurrent-run coordination;
optional agent delegation; acceptance-criterion verification. The baseline is a
local trusted-user tool, not an OS sandbox or tamper-proof compliance system.

## Delivery status

All five baseline delivery increments are implemented. Automated verification
covers request/path validation, provider contracts, question gates, plan
approval, audited edits, pause/resume, write recovery, prompt budgets, and a full
CLI workflow through a temporary local HTTP server. Package build and installation
have been checked. Live model quality and cloud connectivity remain unverified.
The bootstrap development record is in `agentic_audit/build-solar-forge-baseline/`.
