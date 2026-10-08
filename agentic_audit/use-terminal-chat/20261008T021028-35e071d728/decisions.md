# Terminal chat decisions

- The user explicitly preferred terminal chat over the browser interface.
- Replace the browser path entirely; use the current terminal rather than
  spawning a desktop terminal application or altering desktop configuration.
- Use prompt_toolkit for full-screen layout, input editing, paste, and resizing.
- Retain ChatService and all previous chat audit/session formats.
- Run provider calls in worker threads; graceful exit waits for saved replies.
- Add --resume and terminal keyboard shortcuts; remove browser transport/assets
  and obsolete --port/--no-browser options.

No further domain answers were needed for this presentation-layer change.
This record describes the development session, not a simulated chat run.
