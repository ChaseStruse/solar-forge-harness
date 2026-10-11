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

## Mandatory request location

Every request must live at `agentic_audit/requests/<request-name>/request.md`.
Root-level requests and requests under `docs/` or a separate `requests/` directory
are rejected. Use lowercase letters, digits, and hyphens for request folder names.
`forge request "Export billing invoices"` creates a folder named `export-billing-invoices`.
Setup creates a starter bundle named `default`; chat drafts use the request title.
When several bundles exist, pass the desired path to `forge prepare` or `/prepare`.
Chat remembers the request saved or prepared in that conversation.

Put supporting files and subfolders beside `request.md`. Markdown, UTF-8 text,
and reStructuredText documents are automatically included within the configured
file and context limits. Other file types may be stored there but are not sent
to the model. Secret paths, symlinks, and excluded directories are not collected.
Changes to supporting text documents require a new preparation before coding.

Model file tools reject `request.md`, `implementation-plan.md`, and
`*-implementation-plan.md` anywhere, legacy `requests/` and `docs/requests/`
directories, and root-level `plan.md`, `summary.md`, `questions.md`, `decisions.md`,
`context.md`, `progress.md`, and `verification.md`. The workflow writes audit
artifacts internally; application source and maintained product docs remain editable.

All request-specific plans, model call records, change snapshots, and audits must
stay under `agentic_audit/`. Application source edits still go to their normal
project paths. Existing external requests must be moved into a bundle before
preparing or resuming coding; historical audit snapshots remain unchanged.

## Start a request

Run inside the project you want the agent to work on:

```sh
forge init
```

Forge walks you through four steps:

1. **Choose your model service.** Pick Ollama, OpenAI, Claude, or an
   OpenAI-compatible server. Enter your model name, keep or change the service
   address, and choose the API key environment variable if needed. Forge never
   asks you to paste an API key into setup or stores one in the settings file.
2. **Choose your documents folder.** Enter an existing folder inside the project,
   or let Forge create `docs/` at the project root. Absolute paths inside the
   project work too. Existing documents are kept.
3. **Choose local document search (RAG).** Enable a local library
   (default storage: `.forge/rag/`) or choose “Set up later.” After setup, run
   `forge index` or `/index` in chat to build it. No embedding service is needed.
4. **Choose coding standards.** Accept detected languages or select Python,
   TypeScript, JavaScript, or a comma-separated combination. Choose `generic` for
   general guidance. Forge creates editable standards in `.forge/standards/coding.md`.

Setup creates `agentic_audit/requests/default/request.md`, `.forge/config.toml`, and editable guidance in
`.forge/standards/`. It ends with a list of created or preserved files, your
selected settings, and instructions for your first chat. Existing files are
preserved; running `forge init` again keeps your configuration and restores
missing request or guidance templates. To change saved settings, edit
`.forge/config.toml`. Cancelling during the prompts leaves no setup files behind.

For scripts, run `forge init --no-interactive`. Prompts are also skipped when
input is not a terminal. This creates templates and `docs/`; set the model in
`.forge/config.toml` before chatting.

### Language-specific starter standards

Select templates explicitly when creating a project configuration:

```sh
forge init --language python
forge init --language typescript
forge init --language javascript
forge init --no-interactive --language python --language typescript
forge init --no-interactive --language generic
```

Without flags, interactive setup offers detected defaults; noninteractive setup
uses them automatically. Detection inspects up to 500 project paths, excluding
known secrets, symlinks, audit artifacts, dependencies, and build folders. It uses
source extensions and familiar markers such as `pyproject.toml`, `tsconfig.json`,
and `package.json`. A package manifest without TypeScript evidence defaults to
JavaScript. Projects with both `.ts` and `.js` files may select both. Detection is
a starting point: override it for unusual layouts, configuration-only JavaScript,
or larger repositories. No supported language detected means generic guidance.

The selected sections are combined with general coding guidance in
`.forge/standards/coding.md`, which the default `harness.docs` already includes in
model context. Python guidance covers typing, exceptions, resources, dependencies,
and tests. TypeScript covers type boundaries, narrowing, async behavior, and
runtime validation. JavaScript covers coercion, modules, async behavior, lifecycle
cleanup, and tests. Templates defer to existing project requirements and tooling;
they do not install formatters or change compiler/build settings.

New configurations save selections in `harness.languages`. Edit `coding.md`
freely: repeated `forge init` preserves both configuration and existing guidance.
If that guidance file is missing, init recreates it using the saved selections.
Older configurations without `languages` retain generic defaults.

To change an existing project's selection, edit `harness.languages` explicitly
and update `coding.md` to suit the project. If you want a complete fresh template,
back up and remove `coding.md`, then rerun `forge init`. Conflicting `--language`
flags on an already-configured project report this requirement and leave its
files untouched. Any changed project guidance requires fresh preparation for
existing coding runs.

To start, run `forge chat` and type `/request`. Forge guides you through the
title, description, details, and results you want. Use `/ask` followed by a
question whenever you need model advice. Type `/save-request` to save the draft,
then `/prepare`, `/answer` if questions are needed, and `/plan`. Read the plan
and type `/approve` when you are ready for coding. Press Enter to send and
Ctrl-Q to leave chat. You can also edit the request bundle’s `request.md` directly.

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
agentic_audit/requests/billing/request.md`. Add domain documents and application standards to the
`harness.docs` list in `.forge/config.toml`. Entries can be individual files or
folders. Folders load `.md`, `.txt`, and `.rst` files, including subfolders, in a
stable order. Known credential paths, symlinks, build folders, and dependencies
are excluded from folder discovery. Collection is limited to 500 documentation
files and the configured file/context size limits. Missing documentation is
reported in the context snapshot. Documents are sent to the selected model
service as context. Use `rag.sources` for a separate searchable library instead
of loading a large reference collection into every prompt.

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

## Model personality

Forge uses a shared personality across every provider: a warm, capable teammate
with dry wit, light sarcasm, and occasional friendly teasing. The voice is defined
in [guidance/personality.md](src/solar_forge/guidance/personality.md) and used in
chat, discovery, planning, and coding prompts. No Ollama Modelfile or model rebuild
is needed. For example: “You built a small bureaucracy around a boolean. We can
simplify this.” Examples guide the tone rather than serving as repeated catchphrases.

Useful answers come first. Humor becomes quieter during frustration, serious
failures, or sensitive discussions. Ask for “no jokes” or another tone to adjust
conversation style. Structured workflows still require valid JSON, precise tools,
explicit approval, and real verification evidence; personality does not change
those rules. Generated humor and adherence depend on the selected model.

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
| Ctrl+X | Request a stop at the next reply chunk or coding action boundary |
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
| `/requests` | List request titles, paths, and latest run states |
| `/select NUMBER` | Select a bundle from `/requests` |
| `/edit-request` | Open the selected request for editing |
| `/edit FIELD TEXT` | Update `title`, `description`, `technical_details`, or `acceptance_criteria` in a draft |
| `/context` | Inspect included documents, retrieval, exclusions, and prompt bytes; warns at 80% of the limit |
| `/index` | Build or refresh the local reference library |
| `/search QUERY` | Search reference passages with source citations, without a model call |
| `/rag` | Show library size, missing sources, and index freshness |
| `/continue` | Open a linked conversation with a compact handoff, preserving the request, run, and draft |
| `/request [TITLE]` | Draft a request bundle, one question at a time |
| `/request show` | Read the current request |
| `/save-request` | Save the finished draft; saves to the title’s request folder, with an explicit replacement notice if it exists |
| `/prepare [FILE]` | Find questions in a request (selected request in chat, otherwise the only request bundle) |
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
| `/discard-pending` | Discard a failed model message; return it to the composer for editing and continue the same chat |
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

Chat sends the current project documentation, the selected request and its supporting text documents, and the
selected run’s questions, plan, and summary to the model when you ask for help.
It shares the existing provider adapters, so cloud providers require the same
API-key environment variables. Coding runs retain their own audit records and
file diffs. Approved coding runs can execute configured named verification checks
and use their results to repair failures. Other checks are suggested for you to run.

Conversations are stored under `agentic_audit/forge-chat/<run-id>/`, including
`transcript.md`, `state.json`, context, events, and provider-call inputs/outputs.
Messages persist before model calls; Ctrl+R retries that pending message after a
failed reply. Existing conversations from the earlier browser UI remain compatible.
Saved conversations from a different provider/model can be viewed, but start a
new chat to send with the currently configured model.

Ollama chat replies stream live. Other provider adapters currently return complete replies. Conversation size and successful
turns use `max_prompt_bytes` and `max_turns`; start a new chat when those limits
are reached. Exiting while a reply or coding action is active waits for it to
finish or pause and save. Actions run in the background while the terminal stays
responsive; another message or action can be sent after the current action ends.
Forced process termination can leave a stale audit lock; use the same recovery
procedure as agent runs below. `forge chat` requires interactive terminal input
and output. The former `--no-browser` and `--port` options have been removed.

## Workflow

```sh
forge prepare agentic_audit/requests/default/request.md
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
  requests/
    <request-name>/
      request.md             # Mandatory request entry point
      context/               # Optional supporting files and subfolders
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

## Search local documents with RAG

Forge can retrieve relevant passages from a local document library for chat,
request preparation, and coding. Indexing and keyword search run locally without
model calls, embedding credentials, or additional dependencies. Retrieved passages
are sent to your selected model when used as context and saved in the audit.

Enable search in `.forge/config.toml`:

```toml
[rag]
storage = "local"
path = ".forge/rag"
sources = ["reference", "docs/product"]
top_k = 5
max_result_bytes = 12000
```

Choose existing folders or individual Markdown, UTF-8 text, and reStructuredText
files (`.md`, `.txt`, `.rst`). Paths must be inside the project. An empty `sources`
list uses `harness.docs`, preserving compatibility with existing local RAG setup.
Keep essential rules in `harness.docs`; put larger reference collections only in
`rag.sources` so they are searched instead of included in full in every prompt.
Current request attachments remain scoped to their request and are included by
the existing context collector; other requests' audit folders are not indexed.

Build and explore the library:

```sh
forge index
forge index --status
forge search "refund receipt requirements"
```

In chat, use `/index`, `/rag`, and `/search refund receipt requirements`. These
commands make no model calls. Ordinary chat messages automatically retrieve
passages for the latest message. Preparation retrieves passages for the request;
discovery and planning receive those passages. During approved coding, the model
can issue `search_docs` queries to pull more references. Results carry source paths,
line ranges, document hashes, and excerpts; answers are instructed to cite them.
Retrieved text is reference data and cannot approve edits or execute commands.

Search ranks matching words using BM25-style scoring. It does not use embeddings,
understand synonyms, or fetch websites. Specific domain terms usually work better
than vague questions. Search returns up to `top_k` passages within the serialized
result budget. Very small budgets can exclude an entire passage. Long source
lines are split into bounded excerpts that retain their original line number.

Run `/index` or `forge index` again after editing, adding, or removing library
files or changing RAG settings. Search checks source hashes and refuses to return
stale excerpts. Missing indexes and missing source paths are shown explicitly.
Coding runs bind the retrieval settings and corpus fingerprint at preparation;
changes require a freshly prepared run. Agent file tools cannot edit reference
sources or the index. A corrupt cache produces an actionable error; remove its
`index.json` and rebuild, leaving historical audit evidence intact.

The first version supports up to 500 files and 5 MB of source text, within each
file's `harness.max_file_bytes` limit. Passage text is at most 2,000 UTF-8 bytes,
queries are capped at 2,000 bytes, and the index is capped at 20 MB. Automatic
retrieval uses the first 2,000 bytes of the message or request as its query.
Known secret paths, symlinks, dependencies, build folders, and audit folders are
excluded. Credentials in otherwise ordinary documents cannot be detected reliably.
The index contains copied document text; apply the same retention policy as your
source documents. CLI search evidence is saved under `agentic_audit/document-retrieval/`;
chat and coding evidence lives in the corresponding run's `retrieval/` directory.

## Run verification checks

Verification is disabled by default. Add trusted named commands to
`.forge/config.toml` **before preparing a new run**:

```toml
[verification]
commands = { tests = ["python", "-m", "unittest", "discover", "-s", "tests", "-v"] }
env = { PYTHONPATH = "src" }
timeout = 120
max_output_bytes = 20000
```

Use the Python environment containing your project's dependencies, or configure
an absolute executable path. The harness shows this policy alongside the plan;
approving the plan permits these commands during coding. The model selects a
name with `run_check`, without supplying arguments or shell text. Changing the
verification policy requires a newly prepared run. Existing configurations keep
verification disabled.

Commands run in the project root with stdin closed, combined stdout/stderr,
a timeout, and bounded captured output. Only `PATH`, `LANG`, and the explicitly
configured environment are passed; provider credentials are not inherited.
Do not put secrets in `verification.env`: the policy is saved in the audit.
Timeouts and cancellation kill the process group. This runner currently requires
POSIX. Ctrl+X can stop a running check as well as coding between actions.

**Configure only trusted checks.** Test commands execute project code—including
code edited by the agent—with your local permissions. They can access the
network and files outside the project, change files, or start detached processes.
Fixed arguments and process-group cleanup are not an OS sandbox. Command side
effects are not captured by the file-write journal or automatically rolled back.

Each check saves its command, exit status, duration, bounded output, and outcome
under the run's `verification/<turn>/`. Failed checks return evidence to the agent
for repair. Completed results are reused after interruption; a saved execution
intent without a result becomes an unknown interrupted outcome, never an
automatic replay. After a harness crash, inspect any surviving process before
requesting another check.

The final summary lists recorded outcomes and flags checks preceding later agent
file edits as needing a rerun. External edits and command side effects are not
tracked by this staleness flag. Passing commands do not certify every acceptance
criterion or automatically accept the changes.

## Boundaries of this baseline

This is a single-agent workflow, ready to extend behind provider and tool
interfaces. It edits project files and can execute opt-in named verification
commands on POSIX systems. It has no arbitrary shell, Git, or deployment tool. A
finished run has state `review_required`: recorded command outcomes are evidence,
while acceptance criteria still require human review.

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

Streaming, cost accounting, semantic retrieval, OS-isolated verification, Git/deployment
actions, and optional multi-agent coordination are follow-up work. See the
[implementation plan](agentic_audit/requests/baseline/implementation-plan.md) and
[architecture](docs/architecture.md).

## Development

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
```

Tests use scripted responses, mocked adapter payloads, and a temporary loopback
HTTP server to exercise the complete CLI. No paid model calls or real credentials
are needed. The HTTP integration test requires permission to open a local socket.

### Provider identity in audits

Existing runs and chats remain bound to their saved provider, model, and endpoint.
Restore those settings to resume, or prepare a new run to switch models/services.
CLI overrides cannot change an existing run's identity. Historical audits without
an endpoint field still enforce their recorded provider and model.
Each new HTTP call records its provider, model, and full request endpoint in its
input audit and start event, including failed calls. API keys and authorization
headers are excluded. Non-HTTP adapters without identity metadata are explicitly
labelled as using the run's declared configuration.

### Editing and continuing chat

Use `/requests` then `/select NUMBER` to choose a bundle. `/edit-request` loads its
fields; `/edit description New description` changes one field without restarting.
`/save-request` persists changes after checking for concurrent edits. Editing the
title keeps the existing folder; additional Markdown sections are preserved.

`/context` reports the current request, included document paths and sizes,
exclusion rules, and prompt usage in bytes (not estimated model tokens).
`/continue` creates a new linked conversation with an abridged extractive handoff
of the last four user messages and preserved request/run/draft references. It
makes no model call and does not transfer a reviewed-plan approval. The original
conversation stays available; the handoff is not a complete semantic summary.
The same documents still apply, so continuation only reduces conversation history.

Plans request separate affected-file, step, verification, and risk sections.
Review labels distinguish proposed work from actual saved diffs shown after coding.
Approval remains explicit. Ctrl+X stops at a safe boundary; an active network read
may finish or time out first. Partial replies are stored in the call audit and
remain retryable/discardable, never treated as completed answers or tool actions.
