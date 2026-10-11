# Verification and change summary

Implemented opt-in named verification commands in approved coding runs, with fixed argv,
minimal environment, POSIX process-group cleanup, runtime/output limits, persistent
intent/result evidence, and recovery without automatic replay. Prepared runs bind the
verification policy and show it beside the plan. Actual outcomes feed the agent loop
and human review; later agent writes flag older outcomes as stale.

## Validation

- Required command: `PYTHONPATH=src python -m unittest discover -s tests -v`.
- Environment: temporary Python 3.12.14 virtual environment at
  `/tmp/solar-forge-verification-venv`, installed from the project's declared dependencies.
- Final result: **88 tests passed**, 5.036 seconds. Full output: `unittest.log`.
- 15 verification-specific tests cover actual subprocess success/failure, environment
  filtering, timeout, bounded output, cancellation, descendant cleanup, unknown/disabled
  commands, argument rejection, missing executables, policy binding, approval, saved
  result recovery, ambiguous recovery, and fresh-read enforcement.
- A scripted provider drives real edit/check/failure/repair/check/success execution
  against a temporary Python project. No live model quality benchmark or paid model
  call was performed.
- `git diff --check` passed.

## Environment notes

The initial system Python lacked prompt_toolkit. Dependencies were installed in a
temporary environment. The restricted sandbox denied local sockets used by existing
integration tests; the final suite ran with approved socket access and passed.

## Limits

Commands are trusted local execution, not an OS sandbox. They can alter files and
use the network. Arbitrary command side effects are not journaled, and the staleness
flag tracks later agent writes only. Hard harness termination or detached processes
can escape normal cleanup. The runner currently requires POSIX. Passing commands
remain evidence for review, not automatic acceptance-criteria certification.

## Commits

- `128a9ac`: request recorded before implementation.
- `2933268`: runner, workflow integration, and initial tests.
- `2362c94`: additional recovery/process tests and maintained documentation.
- Final audit commit records this verification evidence and completed checklist.
