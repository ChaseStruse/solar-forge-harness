# Request: Live run visibility

## Description
Implement the first recommended enhancement: show what Forge is doing during a run, including the current action, changed files, latest verification result, elapsed time, and token usage when providers report it. Make long runs easy to follow and stop. Continue committing in small stages.

## Technical Details
Integrate progress with the existing terminal chat and audited workflow. Report actual execution events and provider-reported token counts, never estimates presented as usage. Keep Ctrl+X cancellation and existing approval/recovery behavior. Avoid exposing file contents or credentials in the compact progress view; preserve evidence under each run's audit.

## Acceptance Criteria
- [ ] Terminal chat updates while model calls and coding actions are running.
- [ ] Users can see the current action, changed-file summary, latest check outcome, and elapsed time.
- [ ] Reported token usage is normalized, audited, and displayed with clear unavailable/partial states.
- [ ] Cancellation remains responsive at supported boundaries and is visible in the UI.
- [ ] Progress survives completion and can be inspected after reopening a run.
- [ ] Tests cover progress updates, failures, cancellation, usage, and legacy compatibility.
- [ ] Required unittest suite passes; documentation and verification evidence are committed.
