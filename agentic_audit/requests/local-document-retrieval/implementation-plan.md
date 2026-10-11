# Implementation plan

- Implement a bounded, versioned local JSON passage index and deterministic lexical ranking using Python standard-library tools. Source paths, line ranges, and content hashes accompany results. No embeddings service is required.
- Add separate `rag.sources` so large reference collections need not be loaded as always-on guidance. Empty sources fall back to `harness.docs` for compatibility with existing local setup.
- Expose `forge index`, `forge search QUERY`, `forge index --status`, and chat `/index`, `/search`, `/rag`. Retrieval commands work without a configured model service.
- Automatically retrieve passages for user messages and request preparation; add a `search_docs` coding tool. Core guidance remains explicit. Audit retrieval results and support retrieved source citations.
- Refuse stale indexed excerpts. Bind prepared runs to retrieval configuration and source fingerprint; source/config changes require reindexing and new preparation. Protect retrieval sources and storage against agent file writes.
- Exercise ranking, exact provenance, boundaries, stale/corrupt indexes, CLI/chat workflows, automatic context and model-directed retrieval. Document limits and commit tested increments.
