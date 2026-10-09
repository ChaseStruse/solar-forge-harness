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

Terminal chat uses prompt_toolkit for full-screen rendering and keyboard input.
The provider, workflow, and audit layers use the standard library. Packaging uses setuptools. To run directly
from this checkout without installing:

```sh
PYTHONPATH=src python -m solar_forge --help
```

## Start a request

Run inside the project you want the agent to work on:

```sh
forge init
```

Forge walks you through three steps:

1. **Choose your model service.** Pick Ollama, OpenAI, Claude, or an
   OpenAI-compatible server. Enter your model name, keep or change the service
   address, and choose the API key environment variable if needed. Forge never
   asks you to paste an API key into setup or stores one in the settings file.
2. **Choose your documents folder.** Enter an existing folder inside the project,
   or let Forge create `docs/` at the project root. Absolute paths inside the
   project work too. Existing documents are kept.
3. **Choose future document search storage (RAG).** Reserve a local folder
   (default: `.forge/rag/`) or choose “Set up later.” Forge saves your choice
   and creates the local folder if selected. Document search and indexing are
   not implemented yet.

Setup creates `request.md`, `.forge/config.toml`, and editable guidance in
`.forge/standards/`. It ends with a list of created or preserved files, your
selected settings, and instructions for your first chat. Existing files are
preserved; running `forge init` again keeps your configuration and restores
missing request or guidance templates. To change saved settings, edit
`.forge/config.toml`. Cancelling during the prompts leaves no setup files behind.

For scripts, run `forge init --no-interactive`. Prompts are also skipped when
input is not a terminal. This creates templates and `docs/`; set the model in
`.forge/config.toml` before chatting.

To start, run `forge chat` and type `/request`. Forge guides you through the
title, description, details, and results you want. Use `/ask` followed by a
question whenever you need model advice. Type `/save-request` to save the draft,
then `/prepare`, `/answer` if questions are needed, and `/plan`. Read the plan
and type `/approve` when you are ready for coding. Press Enter to send and
Ctrl-Q to leave chat. You can also edit `request.md` directly.

Customize the project guidance and replace the request template, for example:

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
`harness.docs` list in `.forge/config.toml`. Entries can be individual files or
folders. Folders load `.md`, `.txt`, and `.rst` files, including subfolders, in a
stable order. Known credential paths, symlinks, build folders, and dependencies
are excluded from folder discovery. Collection is limited to 500 documentation
files and the configured file/context size limits. Missing documentation is
reported in the context snapshot. Documents are sent to the selected model
service as context; this does not build a search index.

## Choose a provider

Choose a provider during `forge init`, or edit the `[provider]` section in
`.forge/config.toml` afterward. `model` must be a model
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

This opens a full-screen chat interface in your current terminal with the
configured model, a scrollable conversation, saved-chat navigation, and a
multiline composer. No browser or local web server is needed.

| Key | Action |
| --- | --- |
| Enter | Send the message; open the selected chat when history is focused |
| Alt+Enter (or Ctrl+J) | Insert a newline in the composer |
| Tab / Shift+Tab | Move between panes |
| Arrow keys | Move within the focused pane or select a saved chat |
| PgUp / PgDn | Scroll the focused conversation/history pane |
| Ctrl+N | Start a new chat |
| Ctrl+L | Focus history; show numbered history on narrow terminals |
| Ctrl+R | Retry a saved pending message |
| Ctrl+Q / Ctrl+C / Ctrl+D | Exit after any active reply or workflow action has been saved |

On narrow terminals, use Ctrl+L, then type `/open NUMBER` in the composer to
reopen a saved chat. Multiline paste is supported. Start directly in a saved
conversation with `--resume`:

```sh
forge chat --provider ollama --model YOUR_INSTALLED_MODEL
forge chat --resume agentic_audit/forge-chat/RUN_ID
forge --project /path/to/project chat
```

You can complete the request workflow in this window:

| Chat command | What it does |
| --- | --- |
| `/request [TITLE]` | Draft `request.md`, one question at a time |
| `/request show` | Read the current request |
| `/save-request` | Save the finished draft; explicitly replaces an existing `request.md` |
| `/prepare [FILE]` | Find questions in a request (default: `request.md`) |
| `/answer` | Record answers one at a time |
| `/answer Q1 TEXT` | Record a specific answer |
| `/plan` | Create and display the coding plan |
| `/run` | Display the plan for review, including interrupted runs |
| `/approve` | Approve the displayed plan and start or resume coding |
| `/status` | Show progress, unanswered questions, and the next step |
| `/changes [FILE]` | Review saved file diffs |
| `/runs`, then `/use NUMBER` | Continue an existing coding run, including one started with the CLI |
| `/discover` | Retry failed preparation for the selected run |
| `/next` | Take the next available step; coding still requires `/approve` |
| `/ask TEXT` | Ask your model for advice at any step |
| `/cancel` | Leave request drafting, question answering, or plan review |
| `/help` | Show all available actions |

To continue an existing run, use `/runs`, then `/use` with its displayed
number. You can then enter `/plan`, ask questions about the plan, and enter
`/approve` to start coding. Run paths also work with `/use`; `/plan`, `/run`,
`/discover`, and `/status` accept an optional run number or path. Quote paths
that contain spaces.

Ordinary messages go to the model. While drafting a request or recording an
answer, ordinary messages fill in that prompt instead; use `/ask TEXT` to ask
for help without saving the advice as an answer. The current mode and next step
are shown above the composer. Drafts and the selected run persist when you reopen
the saved chat. Request drafts leave files unchanged until `/save-request`.

Only a user-entered `/approve` starts coding. The approval applies to the exact
plan displayed by `/plan` or `/run`; changing that plan requires another review.
Model replies do not execute commands or approve edits. New execution questions
pause coding and require answers, a revised plan, and a fresh approval. Failed
preparation can be retried with `/discover`; interrupted coding can be reviewed
with `/run` and resumed with `/approve`.

Chat sends the current project documentation, `request.md` if present, and the
selected run’s questions, plan, and summary to the model when you ask for help.
It shares the existing provider adapters, so cloud providers require the same
API-key environment variables. Coding runs retain their own audit records and
file diffs. Suggested tests are displayed for you to run; Forge has no shell
command runner.

Conversations are stored under `agentic_audit/forge-chat/<run-id>/`, including
`transcript.md`, `state.json`, context, events, and provider-call inputs/outputs.
Messages persist before model calls; Ctrl+R retries that pending message after a
failed reply. Existing conversations from the earlier browser UI remain compatible.
Saved conversations from a different provider/model can be viewed, but start a
new chat to send with the currently configured model.

Replies arrive in full rather than streaming. Conversation size and successful
turns use `max_prompt_bytes` and `max_turns`; start a new chat when those limits
are reached. Exiting while a reply or coding action is active waits for it to
finish or pause and save. Actions run in the background while the terminal stays
responsive; another message or action can be sent after the current action ends.
Forced process termination can leave a stale audit lock; use the same recovery
procedure as agent runs below. `forge chat` requires interactive terminal input
and output. The former `--no-browser` and `--port` options have been removed.

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
