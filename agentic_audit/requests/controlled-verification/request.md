# Request: Controlled verification execution

## Description
Implement the suggested next step for the harness: close the verification loop with controlled test execution and exercise it on realistic local tasks. Commit early and often.

## Technical Details
Add opt-in, user-configured named verification commands to approved coding runs. Models select names, never supply shell text or arguments. Bound runtime and captured output, record execution evidence, and make results available for repair and review. Preserve explicit plan approval and honest acceptance-criteria reporting. Commands execute trusted project code with local user permissions, not an OS sandbox.

## Acceptance Criteria
- [x] Unconfigured or unknown commands cannot execute.
- [x] Configured checks are included in planning and bound to the prepared run.
- [x] Results include command, exit status, bounded output, and timeout/cancellation evidence.
- [x] The agent can use failing checks to repair code and rerun checks.
- [x] Completed checks are not replayed after interruption; ambiguous interrupted checks are reported.
- [x] Review distinguishes recorded check outcomes from unverified acceptance criteria.
- [x] Required unittest suite passes; implementation and verification are committed in small stages.
