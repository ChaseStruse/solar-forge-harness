# Forge chat implementation plan

This browser design was superseded by [terminal chat](terminal-chat-implementation-plan.md) at the user’s request.

1. Commit this plan and structured request before implementation.
2. Add a provider-independent chat service using existing project context,
   audit artifacts, and Provider.complete. Persist a pending user turn before
   calling the model; retry that same turn after failures. Bound conversation
   size and serialize operations on each session.
3. Add a standard-library HTTP server bound to 127.0.0.1. Authenticate API calls
   with an ephemeral session token and validate Host/Origin. Limit request sizes
   and timeouts. Provider credentials remain in the Python process.
4. Package a responsive chat UI with a history sidebar, configured model badge,
   accessible composer, loading/error feedback, and retry. Render model and user
   text through textContent; no unsanitized HTML. This increment waits for a full
   reply using the existing non-streaming adapters.
5. Add forge chat with provider/model overrides, optional port, and no-browser
   mode. Open the system browser by default, print the URL, and stop on Ctrl-C.
6. Test service persistence/retry and HTTP authorization end to end, verify the
   browser interface, update documentation, and commit tested increments.

Chat supplies explicit project guidance and the current request if present. It
has no agent tools or edit approval: users continue through prepare/plan/run for
implementation. A local browser window is the baseline UI; native desktop and
terminal chat interfaces can be added later behind the same service.
