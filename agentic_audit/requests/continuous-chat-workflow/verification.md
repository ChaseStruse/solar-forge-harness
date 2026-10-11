# Change and verification

Initial continuous flow committed as b6ded10. Primary chat path is now /start → answer any blocking questions → review the plan → explicit /approve for development. Home screen, help, saved-request hint, workflow hints, recovery options, and documentation emphasize this path.

/start prepares a selected request (including discovery) and automatically builds/reviews a plan when requirements suffice. Blocking questions open answer mode immediately; the last saved answer automatically builds/reviews the plan. /ask remains advice without saving an answer. Guided mode is durable and copied when continuing a chat. Advanced /prepare clears guided mode and preserves its individual-stage behavior.

/next runs the same state-aware continuation, retrying unfinished discovery or planning in the saved run and stopping at questions or plan review. It never executes or approves development. /start with an explicit request path starts a fresh run; plain /start resumes the selected run. Finished runs show their saved results. Existing identity, current-context, plan hash, lock, and approval checks remain active. Changed requests/context are detected before retry model calls and return an actionable /start FILE hint. Cancellation between preparation and planning preserves resumable state.

Plan review panel opens for guided commands and final ordinary answers. Recovery offers /next for guided preparation failures. Development results carry the third-stage heading. Existing manual stage commands and CLI behavior remain available.

Required unittest discovery passed all 162 tests on installed Forge Python 3.12.14. New tests cover no-question preparation directly reaching review without approval; questions/advice/final-answer progression; planning timeout retried without duplicate discovery/run; stopping between stages and resuming; and changed request preventing stale model calls. Existing explicit approval and UI/CLI tests pass. Full output: unittest.log. git diff --check passed. No live model calls or external project settings were changed.
