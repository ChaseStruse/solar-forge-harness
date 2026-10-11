# Implementation plan

1. Add a compact durable progress snapshot derived from existing audit events, plus an optional context-local observer for live UI delivery. Keep it separate from authoritative workflow state to avoid stale state overwrites.
2. Preserve provider string contracts while attaching normalized usage metadata to replies/chunks. Record per-call usage including unavailable/partial outcomes and reported usage on rejected responses. Support OpenAI Responses, compatible Chat Completions, Claude, and Ollama.
3. Add a bounded terminal activity panel, updated through thread-safe event delivery and periodic repaint for elapsed time. Retain latest snapshot on completion, load it when reopening, and surface summaries through /status and CLI status.
4. Keep stop controls explicit. Show stop requested while network reads may still be waiting; existing command cancellation remains in force.
5. Test event reduction, snapshots, usage isolation, error/recovery paths, live UI during blocked calls and checks, cancellation, narrow rendering, and legacy runs. Run the required suite and record documentation/evidence.

## Provider references

- OpenAI token counting: https://developers.openai.com/api/docs/guides/token-counting
- Compatible response usage: https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
- Claude cache-inclusive input counts: https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- Ollama chat counters: https://docs.ollama.com/api/chat

Input/output counters are reported quantities, not cost estimates. Claude input
includes cache creation/read counters. Missing values stay unavailable; partial
coverage is labelled. No live API credentials or calls are required for fixtures.
