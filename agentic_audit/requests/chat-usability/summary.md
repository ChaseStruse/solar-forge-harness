# Chat usability implementation

Added /requests and /select for request selection with current run status; /edit-request and /edit FIELD TEXT for incremental draft changes. Existing bundle paths and extra Markdown sections are preserved, with concurrent-edit checks at save.

Added /context for included documents, exclusion rules, prompt bytes and an 80% warning. Added /continue for an offline extractive handoff into a linked conversation that retains request, run and draft references without transferring reviewed-plan approval. Existing transcripts remain intact. Handoffs contain abridged recent user excerpts, not a complete model-generated summary.

Plan prompts request affected files, steps, verification and risks. Review output labels proposed plans separately from actual saved diffs after coding.

Added native Ollama streaming and terminal Ctrl+X stop requests. Other adapters retain full-response behavior. Cancellation is cooperative at reply chunks and coding action boundaries; active blocking network reads must return or time out first. Partial reply evidence is saved without committing it as a completed answer. Pending coding actions are checkpointed before stopping and can be resumed through the existing approval flow.

Provider reference: https://docs.ollama.com/api/chat (stream flag, message content and done marker). No live hosted-model calls were made.

Verification: all 73 tests pass. Added coverage for selection/editing, preserved extra sections and concurrent changes, context/continuation without model calls, stream completion/error handling, partial evidence and cancellation before another chunk, and safe coding stop before a write. Full test output is in tests.txt. Git diff whitespace check passes.

Commits: 355395b scope; 88507d9 selection/editing; 1ba620d continuation regression specification; 403cced context/handoff implementation; 6e70aad streaming/cancellation. Final documentation and cancellation refinement are committed separately.
