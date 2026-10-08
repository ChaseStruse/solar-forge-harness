# Chat implementation decisions

- Use a local browser window, consistent with the requested chat-window experience.
- Reuse the configured model and the provider-independent completion interface.
- Keep the runtime dependency-free; serve packaged HTML, CSS, and JavaScript.
- Provide plain chat with project context; approved edits stay in the coding workflow.
- Save conversations under agentic_audit/forge-chat; save a pending message before
  the model call and allow retry without duplicating the user turn.
- Bind to loopback and authenticate API calls without placing API keys in the UI.
- Use complete replies initially; streaming remains future work.

This is the development-session audit, not a simulated model conversation.
No additional domain clarification was needed to extend the existing provider contract.
