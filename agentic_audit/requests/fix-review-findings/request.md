# Request: Fix four harness review findings

## Description
Implement the four accepted code-review fixes and commit early and often.

## Technical Details
Centralize run discovery without treating request attachments as runs. Enforce reserved request artifact locations in model writes. Provide audited in-session recovery for pending chat messages. Preserve accurate provider provenance and consistent model-switch rules across entry points.

## Acceptance Criteria
- Request attachments named state.json do not break CLI or chat discovery.
- Model writes cannot create reserved request artifacts outside agentic_audit.
- Users can discard a failed pending message and continue the same chat.
- Model mismatches are rejected consistently and each HTTP provider call records its non-secret identity.
- Each fix has regression coverage and a focused commit; the complete suite passes.
