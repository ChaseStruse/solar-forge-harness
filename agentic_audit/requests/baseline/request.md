# Request: Build Solar Forge baseline

## Description
Create a clean, easy-to-use CLI agent harness driven by request.md. The model
provider must be independent of orchestration, supporting OpenAI, Claude, and
local models. Agents should ask specific application and standards questions in
the CLI before making consequential decisions and retain project-local evidence.

## Technical Details
Use Python or Rust. A request contains Description, Technical Details, and
Acceptance Criteria. Load coding standards, deployment guidance, Git strategy,
architecture guidance, and other application documentation. Keep an audit trail
under agentic_audit with a folder named for each request. Establish an
implementation plan and begin implementing. Commit early and often.

## Acceptance Criteria
- [ ] CLI can initialize a project and create a structured request template.
- [ ] Provider adapters share one orchestration contract and accept configured models.
- [ ] Domain questions are stored in Markdown and asked interactively.
- [ ] Answers gate planning; recorded approval gates project edits.
- [ ] Requests, context, questions, plans, calls, and edits have audit evidence.
- [ ] Bundled and project documentation guide the workflow.
- [ ] Offline tests and package installation validate the baseline.
- [ ] Implementation plan, architecture, limitations, and usage are documented.
- [ ] Work is committed in focused increments.
