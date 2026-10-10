# Implementation checkpoints

## F1: run discovery

Centralized discovery in Audit.discover and filtered full run paths before opening them. Request attachments named state.json are ignored; real runs with the slug requests remain supported. Unreadable run JSON emits a warning while healthy runs remain discoverable.

Validation: 16 request and chat-workflow tests pass, including attachment collisions through CLI status, chat history, and /runs.

## F2: model artifact destinations

Reserved request and implementation-plan filenames, legacy request directories, and root audit-note names are rejected by Workspace's non-internal write path. Documented the exact policy and reinforced model tool instructions. Application code/product docs and internal audit summaries remain supported. The old policy test now checks that no root request file appears.

Validation: 17 agent, request, and foundation tests pass, including a complete model loop attempting ten prohibited destinations and two valid application destinations.
