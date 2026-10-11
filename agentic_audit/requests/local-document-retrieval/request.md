# Request: Local document retrieval for models

## Description
Continue enhancing the harness so models can pull useful data through a RAG system that is convenient for users. Continue committing early and often.

## Technical Details
Build on the existing local/deferred RAG configuration. Start with opt-in local project document indexing and ranked passage retrieval, without a hosted service or embedding credentials. Keep core project guidance explicit, add independently configured retrieval sources, expose search in CLI/chat and coding tools, and retain source provenance and audit evidence. The user confirmed local project documents first; remote sources are outside this request.

## Acceptance Criteria
- [x] Users can build, inspect, and search a local document index.
- [x] Search results contain bounded passages with source paths and line ranges.
- [x] Chat and request preparation receive relevant retrieved context; coding models can explicitly search.
- [x] Source exclusions, size limits, disabled configurations, and stale indexes are handled clearly.
- [x] Retrieved content is reference data, never workflow authorization; queries and results are auditable.
- [x] Existing configurations and workflows remain compatible.
- [x] Required unittest suite passes and maintained docs explain setup and limits.
