# Request: Add Forge chat window

## Description
Provide `forge chat` to open a familiar chat window for the user's designated
model. Reuse project provider configuration and retain project-local chat audits.

## Technical Details
Use a loopback-only browser UI served by the Python CLI, without adding runtime
dependencies. Reuse the Provider interface for plain conversation. Keep API keys
on the server, persist multi-turn conversations, and display provider failures
without losing a message or duplicating it on retry. Chat has no file-edit tools.

## Acceptance Criteria
- [ ] `forge chat` opens a browser window and displays the configured provider/model.
- [ ] User can send multi-turn messages, start a new chat, and reopen saved chats.
- [ ] Conversations, context, and call evidence persist under agentic_audit.
- [ ] Provider failures can be retried without duplicate user messages.
- [ ] Browser content renders safely; other origins cannot call the local backend.
- [ ] Tests verify the service, HTTP interface, and CLI integration.
- [ ] Usage and architecture documentation are updated and changes committed.
