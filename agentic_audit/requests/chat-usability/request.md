# Request: Improve Forge chat

## Description
Add request selection, editable drafts, streamed replies and safe cancellation, clearer review, visible context budgets, and linked conversation continuation. Keep implementation and token usage economical; commit incrementally.

## Technical Details
Preserve explicit plan approval, audit history, request location policy, and provider identity checks. Implement commands in the service/workflow and expose them through terminal chat.

## Acceptance Criteria
- Users select requests and edit individual fields without restarting.
- Context inspection and continuation operate without extra model calls.
- Plan review and actual changes are clearly distinguishable.
- Replies can stream with supported adapters; cancellation saves partial evidence and stops coding between actions.
- Regression tests pass and changes are committed.
