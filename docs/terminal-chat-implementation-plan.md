# Terminal chat implementation plan

Replace the browser launch path with a full-screen terminal interface for the
existing provider-independent ChatService. Preserve saved sessions and pending
turn recovery. Remove browser transport/assets from the shipped CLI.

1. Commit the plan before implementation.
2. Build a terminal UI with a conversation pane, saved-session list, model/project
   header, multiline composer, keyboard navigation, loading feedback, and retry.
   Use prompt_toolkit for terminal input, resizing, scrolling, and portability.
3. Run synchronous provider calls in a worker thread so the UI stays responsive.
   Serialize chat actions, preserve saved pending turns on failures, and finish
   active replies before exiting. Do not add agent edit tools to chat.
4. Change forge chat to launch the terminal UI, add --resume for saved audits,
   and remove browser/port flags. Update runtime dependency and installation.
5. Test keyboard actions, history selection, composer handling, failed-turn retry,
   and CLI wiring; smoke-test the real UI in a PTY. Update docs and audit evidence.
6. Commit tested increments and verify the installed user-level forge command.

Interaction: Enter sends; Alt+Enter adds a line; Tab changes pane; Ctrl+N starts
new chat; Ctrl+R retries a pending turn; Ctrl+Q exits. The interface uses ordinary
terminal rendering rather than spawning or configuring the desktop terminal app.
