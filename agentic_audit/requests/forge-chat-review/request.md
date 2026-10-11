# Review and improve Forge chat

Review the current chat workflow, keyboard interactions, UI, and performance. Implement concrete fixes and verify behavior. Preserve explicit approval and existing audit evidence. Commit focused changes.

## Initial findings

- Continue cannot see request draft state returned by ChatService.get, so it offers the wrong action while drafting. Saved plans without a review marker route to /review, which refuses to open them.
- F2 while typing an answer can erase the unsent composer text. Pending messages and turn-limit runs have no appropriate Continue action.
- History listing loads complete chat views and linked runs just to retrieve sidebar metadata.
- Streaming callbacks rebuild and sanitize the full transcript for every chunk and can queue unbounded UI work. Rendering also resets the conversation scroll position.
- Some request-selection routes still suggest /prepare rather than the guided /start flow.

## Verification plan

Exercise Continue through actual service state, reopen a plan without granting approval, preserve unsent answers, test menu keyboard behavior, measure avoided history loads and streaming render work, and run the required full unittest suite.
