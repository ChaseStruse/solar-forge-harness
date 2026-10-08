# Terminal chat review

forge chat now launches a full-screen terminal interface with history,
conversation, a multiline composer, provider/model display, and retry. Browser
transport and packaged web assets were removed. User-level installation was
refreshed with the declared prompt_toolkit dependency.

Verification:
- 31 tests passed, including actual keyboard Enter/Alt+Enter/Backspace,
  new chat/history reopening, failed reply/retry, graceful pending-call exit,
  resume, submission rejection/draft retention, and terminal-text sanitization.
- Installed forge command passed a real 120-column pseudoterminal test against
  an offline local HTTP model stub: startup, send, persisted reply, Ctrl+Q exit.
- Clean wheel contains terminal_chat and dependency metadata, with no browser
  chat transport or web assets.
- Python compilation and Git whitespace checks passed.

Live cloud/local inference quality was not tested. Replies remain non-streaming;
chat continues to use the existing request workflow for approved file edits.
