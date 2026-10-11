# Implementation plan

1. Add validated, disabled-by-default named verification configuration and snapshot it during preparation. Reject changed policy on resume; display the executable policy alongside plans.
2. Implement a POSIX subprocess runner with fixed argv, minimal environment, project cwd, timeout/cancellation, bounded combined output, process-group cleanup, and write-ahead execution records. Never replay an ambiguous interrupted command automatically.
3. Integrate named checks into the approved agent loop and human review. Passing checks remain evidence, not automatic acceptance-criteria certification; later edits make earlier checks stale.
4. Exercise actual subprocess success, failure, timeout, output limits, cancellation, recovery, policy changes, and a scripted edit/test/repair/test workflow. Run the complete required suite in a temporary environment with declared dependencies.
5. Update maintained documentation and commit implementation, coverage, and final verification evidence in stages.
