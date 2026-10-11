# Forge chat review results

## Fixed

- Continue now derives its action from saved request/answer state, including pending replies and development turn limits. It saves completed request drafts and reopens unreviewed plans through the audited review command. Opening a plan never grants approval.
- F2 preserves unsent request and question answers and focuses the composer. Settings updates refresh the displayed next action.
- Request selection consistently offers the guided /start or /next flow, resets stale recovery state, and displays the selected run's activity.
- History metadata listing no longer builds full chat views or reads linked-run progress. Empty history queries skip transcript/error searches; capped searches stop before scanning unused requests.
- Streamed text is batched at up to 20 preview updates per second. Saved response handling is unchanged. Closing the preview discards late display callbacks.
- Unchanged transcript text and role styles are cached instead of being sanitized twice per chunk. Updates preserve the reader's cursor/scroll position; following the end still tracks new text.
- Chat creation during send runs off the UI thread. The live activity list is bounded to its six displayed entries.
- Inactive Activity hides during plan review and request/action selection to provide more reading space.

## Evidence

- Required unittest discovery: 173 tests passed on installed Python 3.12.14; full output in unittest.log.
- Nine new regression tests cover real draft/answer state, pending-reply recovery, reopening a plan without a provider call or approval, updated turn-limit settings, lightweight history listing, stream ordering and late callbacks, cached rendering and scroll preservation, complete saved burst responses, and actual F2 keyboard input.
- A 1,000-chunk end-to-end burst response saves all text with fewer than 20 render calls. A separate batching test preserves chunk order with fewer than 10 callbacks.
- History tests reject full-view and progress loading while listing/searching chats. Rendering tests reject repeated sanitation of unchanged earlier messages during preview updates.
- Inspected a rendered 120-column by 30-row plan-review screen using the real prompt_toolkit application.
- git diff --check passed.

## Scope

Provider responses were exercised with deterministic fixtures. This review improves harness responsiveness and navigation; it does not measure or alter live LM Studio inference speed. No live model server was required.
