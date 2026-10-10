# Repository instructions

Request organization is mandatory:

- Before implementation, record the user request in `agentic_audit/requests/<request-name>/request.md`.
- Keep request-specific context, implementation plans, progress notes, verification evidence, and change summaries under `agentic_audit/`. Never create these in the root, `docs/`, or a separate top-level requests folder.
- Each request gets its own folder; optional supporting files and subfolders belong beside its `request.md`.
- Keep historical run artifacts intact. Harness runs store model calls, change snapshots, and audit evidence under `agentic_audit/<request-slug>/<run-id>/`.
- Application source, tests, and maintained product documentation belong in their normal project locations.
- Verify behavior with `PYTHONPATH=src python -m unittest discover -s tests -v`.
