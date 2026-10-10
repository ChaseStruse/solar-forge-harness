# Implementation checkpoints

## F1: run discovery

Centralized discovery in Audit.discover and filtered full run paths before opening them. Request attachments named state.json are ignored; real runs with the slug requests remain supported. Unreadable run JSON emits a warning while healthy runs remain discoverable.

Validation: 16 request and chat-workflow tests pass, including attachment collisions through CLI status, chat history, and /runs.

## F2: model artifact destinations

Reserved request and implementation-plan filenames, legacy request directories, and root audit-note names are rejected by Workspace's non-internal write path. Documented the exact policy and reinforced model tool instructions. Application code/product docs and internal audit summaries remain supported. The old policy test now checks that no root request file appears.

Validation: 17 agent, request, and foundation tests pass, including a complete model loop attempting ten prohibited destinations and two valid application destinations.

## F3: pending-message recovery

Added /discard-pending at both service and terminal entry points. It records the discarded text in audit events, clears the pending state without adding prompt-history bulk, preserves the conversation and selected run, and restores an /ask draft in the terminal so editing remains safe during request/answer wizards. Updated recovery notices and help.

Validation: chat service, chat workflow, and terminal tests cover prompt-budget failure and repeated retry after existing history, discard without provider calls, preserved run/history, a successful shorter follow-up, and recovery during a request wizard.

## F4: provider provenance and consistent identity checks

Existing runs/chats reject provider, model, or endpoint changes through a shared identity check. CLI checks occur before approval or provider calls. New run/chat state records the effective endpoint. Each HTTP adapter exposes its actual identity; call input records and start events capture only provider/model/endpoint, with no keys or authorization headers. Generic test/custom adapters lacking metadata are explicitly marked as using the declared run configuration. Legacy audits without endpoint metadata retain provider/model checks.

Validation: CLI tests cover discovery, planning, and execution against model/provider flags and saved model/endpoint changes; no provider calls or approval mutations occur on rejection. Provider tests cover failed-call provenance, identity mismatch, and absence of API keys in all audit files. Chat tests cover changed endpoints.

## Final verification

All 67 tests pass with `PYTHONPATH=src python -m unittest discover -s tests -v`; output is in tests.txt. The temporary dependency environment was placed first in PATH. Local HTTP/terminal integration checks ran outside the restricted sandbox. A restricted terminal-test run stalled at asynchronous event-loop teardown and was stopped; the unrestricted 26-test chat/terminal run and final full suite both passed. Git diff whitespace check passes.

Production fixes and regression tests are committed in separate checkpoints. Historical audit records were left unchanged. No live hosted-provider calls were needed.
