# Solar Forge

A Python CLI for request-driven coding agents. The workflow and audit trail are
independent of the model: use OpenAI, Claude, Ollama, or an OpenAI-compatible
server. Model identifiers are always supplied by you.

Write a request, answer application-specific questions, review a plan, and approve
file edits. Every run leaves its request, documentation, decisions, model calls,
and change evidence inside the project.

## Install

Python 3.11 or newer:

For a user-level `forge` command available from any directory, install with uv
from this checkout:

```sh
uv tool install --editable .
forge --help
```

Alternatively, install into a virtual environment. With this option, activate
the environment in each terminal before using `forge`:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
forge --help
```

There are no runtime dependencies. Packaging uses setuptools. To run directly
from this checkout without installing:

```sh
PYTHONPATH=src python -m solar_forge --help
```

## Start a request

Run inside the project you want the agent to work on:

```sh
forge init
```

This creates `request.md`, `.forge/config.toml`, and editable guidance in
`.forge/standards/`. Existing files are preserved. Customize the guidance for your
application and replace the request template:

```markdown
# Request: Export billing invoices

## Description
Allow finance staff to export invoices as CSV.

## Technical Details
Use the existing billing service and authorization rules.
Record any unresolved business rules as questions before coding.

## Acceptance Criteria
- [ ] Export includes invoice number, customer, currency, and total.
- [ ] Unauthorized users cannot export invoices.
- [ ] Date filters have documented timezone behavior and boundary tests.
```

For multiple requests, use `forge request "Export billing invoices" --output
requests/billing.md`. Add domain documents and application standards to the
`harness.docs` list in `.forge/config.toml`. The baseline loads those explicit
paths and supplies a bounded file inventory; it does not index the entire repo.
Missing documentation is reported in the context snapshot.

## Choose a provider

Edit the `[provider]` section in `.forge/config.toml`. `model` must be a model
identifier supported by your chosen service; no model is automatically selected.

| Provider kind | API | Default base URL | Default credential environment variable |
| --- | --- | --- | --- |
| `openai` | Responses | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| `anthropic` | Messages | `https://api.anthropic.com/v1` | `ANTHROPIC_API_KEY` |
| `ollama` | Chat | `http://localhost:11434` | None |
| `compatible` | Chat Completions | `http://localhost:8080/v1` | `LOCAL_MODEL_API_KEY` |

Example for an already installed local model:

```toml
[provider]
kind = "ollama"
model = "your-installed-model"
base_url = "http://localhost:11434"
timeout = 120
```

For a hosted provider, change `kind` and `model`, then export the corresponding
API key. Set `api_key_env` if you use another environment variable. The harness
reads keys from the environment. HTTP is limited to loopback endpoints; remote
endpoints require HTTPS. Redirects are rejected. Authentication is optional for
loopback-compatible servers. Provider/model flags are also available on model
commands, e.g. `forge prepare --provider openai --model YOUR_MODEL`. Changing
provider by flag resets the endpoint and credential variable to provider defaults.

OpenAI uses its API rather than a ChatGPT subscription or browser login. Adapter
contracts follow the official [OpenAI Responses reference](https://developers.openai.com/api/reference/python/resources/responses/methods/create),
[Claude Messages reference](https://platform.claude.com/docs/en/api/messages/create),
and [Ollama chat reference](https://docs.ollama.com/api/chat).

## Chat with your model

Once you have configured `provider.kind` and `provider.model`, run:

```sh
forge chat
```

This opens a local browser window with your configured model, a conversation
sidebar, and a message composer. Enter sends a message; Shift+Enter adds a new
line. Start new chats or reopen saved conversations from the sidebar. Keep the
terminal running while you chat; Ctrl-C closes the server after active replies
have been saved. If your browser does not open, use the URL printed in the terminal.

```sh
forge chat --provider ollama --model YOUR_INSTALLED_MODEL
forge chat --no-browser --port 8765
forge --project /path/to/project chat
```

Chat receives the configured project documentation and the current `request.md`
if present. It helps discuss and refine requests; use `prepare`, `plan`, and `run`
for approved implementation. It shares the existing provider adapters, so cloud
providers require the same API-key environment variables. API keys stay in the
Python process, and the local server accepts authenticated requests on loopback.

Conversations are stored under `agentic_audit/forge-chat/<run-id>/`, including
`transcript.md`, `state.json`, context, events, and provider-call inputs/outputs.
Messages persist before model calls; failed replies expose a retry button that
reuses the pending message. Reopen a saved session to retry after restarting the
server. Saved conversations from a different provider/model can be viewed, but
start a new chat to send with the currently configured model.

The first version displays complete replies rather than streaming. Conversation
size and successful turns use `max_prompt_bytes` and `max_turns`; start a new chat
when those limits are reached. Do not forcibly kill the terminal while a reply is
active: stale audit locks need the same recovery procedure as agent runs below.

## Workflow

```sh
forge prepare request.md
forge status
```

`prepare` creates an audited run and asks generated domain questions in an
interactive terminal. Each question includes its rationale and documentation
sources. Answers are saved immediately. In scripts, use `--no-interactive` and
answer later. Use the run directory printed by the CLI in the following commands;
replace `RUN` with that project-relative path:

```sh
forge answer RUN
# Or answer one question without an interactive prompt:
forge answer RUN --question Q1 --text "Invoice date filters use UTC."
forge plan RUN
forge run RUN
```

`plan` blocks until every question has an answer. `run` displays the saved plan
and asks for approval before allowing edits. `forge run RUN --approve` explicitly
approves that exact saved plan without a terminal prompt. Approval is tied to its
SHA-256 digest. Editing the plan invalidates approval. Changes to the request or
context documents require a new run.

The agent can list files, read text files, write text files, ask new questions,
and finish with a review summary. It must read an existing file before replacing
it. Every write records original content, proposed content, and a diff. New
questions pause execution, invalidate approval, and require answers plus a
revised plan. An interactive `run` asks those questions immediately; then use
`plan` and `run` again to review and approve the revised approach.

Interrupted execution can be resumed with `forge run RUN`. Failed initial
discovery can be retried with `forge discover RUN`; locate its directory using
`forge status`. Provider failures and rejected actions remain in the event log.
Ctrl-C preserves answers and checkpoints. A forced process kill can leave a
`.lock` file: verify the process has exited, remove only that run's lock, and
resume. Turn counts are cumulative; after `turn_limit`, deliberately increase
`harness.max_turns` in configuration or begin a smaller request.

Use `forge --project /path/to/project COMMAND` when working outside the project.

## Audit layout

```text
agentic_audit/
  export-billing-invoices/
    <UTC-timestamp>-<unique-id>/
      request.md             # Original request
      context.json           # Documentation, skipped paths, bounded inventory
      context.md             # Readable documentation snapshot
      questions.md           # Questions, provenance, and recorded answers
      plan.md                # Current implementation plan
      state.json             # Answers, approval digest, conversation, checkpoint
      events.jsonl           # Chronological workflow and tool events
      calls/                 # Inputs and outputs of every model call
      changes/<turn>/        # Before/after text, diff, hashes, and original path
      summary.md             # Human review and suggested verification
```

Repeated requests share a title folder and get distinct run directories. Keep
audit artifacts under your project's version-control and retention policy.
`state.json` is authoritative; Markdown artifacts are readable views. Events and
saved calls retain earlier plans even when `plan.md` is replaced.

## Boundaries of this baseline

This is a single-agent workflow, ready to extend behind provider and tool
interfaces. It edits project files but does not execute shell commands, tests,
Git operations, or deployments. A finished run has state `review_required` and
marks acceptance criteria as unverified. Run suggested checks yourself before
accepting changes.

Traversal, symlinks, known credential paths, and writes to request/context,
policy, Git, and audit files are blocked. File size, initial documentation size,
serialized prompt size, HTTP response size, and agent turns are bounded. These
are application checks for a trusted local user, not an OS sandbox or protection
against a process concurrently replacing paths. Each run has its own lock;
multiple runs in the same project are not coordinated.

Explicit documentation, request text, file names, and agent-read contents are
sent to the selected provider and stored in the audit trail. Credentials in
arbitrarily named files cannot be detected reliably: curate documentation and
review your audit retention policy. API keys are not written by the adapter.

Streaming, cost accounting, retrieval, OS-isolated verification, Git/deployment
actions, and optional multi-agent coordination are follow-up work. See the
[implementation plan](docs/implementation-plan.md) and
[architecture](docs/architecture.md).

## Development

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
```

Tests use scripted responses, mocked adapter payloads, and a temporary loopback
HTTP server to exercise the complete CLI. No paid model calls or real credentials
are needed. The HTTP integration test requires permission to open a local socket.
