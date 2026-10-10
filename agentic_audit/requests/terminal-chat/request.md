# Request: Use terminal chat

## Description
Make forge chat open a terminal chat interface rather than a browser window.
Eliminate the need to launch a browser while chatting with the designated model.

## Technical Details
Reuse the existing ChatService, project provider configuration, saved sessions,
and audit trail. Provide a full-screen terminal interface with a conversation
pane, session history, multiline composition, background replies, and retry.

## Acceptance Criteria
- [x] forge chat opens in the current terminal and launches no browser/server.
- [x] Configured providers/models and prior saved chats remain supported.
- [x] Messages, multiline input, history navigation, and failed-turn retry work.
- [x] Active replies are saved before graceful exit.
- [x] Installed user-level command includes the terminal UI dependency.
- [x] Automated tests, real PTY smoke, and clean wheel verification pass.
- [x] Documentation and development audit reflect the terminal interface.
