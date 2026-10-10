# Implementation checkpoints

## F1: run discovery

Centralized discovery in Audit.discover and filtered full run paths before opening them. Request attachments named state.json are ignored; real runs with the slug requests remain supported. Unreadable run JSON emits a warning while healthy runs remain discoverable.

Validation: 16 request and chat-workflow tests pass, including attachment collisions through CLI status, chat history, and /runs.
