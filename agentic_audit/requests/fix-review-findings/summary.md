# Four review findings resolved

- F1: full-path-filtered, shared run discovery ignores state.json request attachments and retains real historical runs; unreadable JSON produces a warning while other runs remain available.
- F2: the model's project-write boundary rejects documented reserved artifact names and request directories; workflow internals retain permission to save audit artifacts.
- F3: /discard-pending records the discarded text, frees the conversation to continue, and restores an editable /ask draft in the terminal while preserving history, drafts, and run selection.
- F4: CLI and chat reject provider/model/endpoint mismatches for existing work. Actual HTTP call identity is recorded without credentials; legacy audits lacking an endpoint remain readable and enforce their saved provider/model.

Verification: 67 tests pass, including seven new regression tests. Full output is in tests.txt. No live hosted-provider calls were performed.

Commits before the final provenance/verification commit:
- 5826f7f — request and scope
- b33ebc1 — run discovery
- 1843879 — reserved artifact writes
- b9db721 — pending-message recovery
- 0f96a96 — recovery diagnostic compatibility

The artifact policy reserves explicit paths/names; it cannot infer that arbitrary application filenames contain request-specific notes. Model instructions also require all such notes to stay in the audit workflow. Existing histories exceeding prompt limits can now be freed for workflow commands; continuing model conversation may still require a smaller context or larger budget.
