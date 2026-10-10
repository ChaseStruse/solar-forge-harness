# Request: Mandatory request bundles

## Description
Require a requests folder inside the audit directory, with a separate folder per request containing request.md and optional user context. Keep all request-specific plans, change records, and audits under agentic_audit.

## Technical Details
Enforce agentic_audit/requests/<request-name>/request.md in CLI, setup, chat, and workflow preparation. Include supporting text documents and preserve existing audit history. Move repository request and implementation-plan documents into request bundles.

## Acceptance Criteria
- [x] CLI and chat create request bundles inside agentic_audit.
- [x] Requests outside the mandatory layout are rejected.
- [x] Supporting text documents are included and changes invalidate preparation.
- [x] Existing requests and implementation plans are organized under agentic_audit.
- [x] Regression tests pass.
