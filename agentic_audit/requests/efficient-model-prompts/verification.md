# Implementation and verification

First implementation commit: 00f846a. Structured workflow instructions no longer include the full conversational personality guide and its examples. The concise system prompt preserves request priority, project-over-bundled guidance, consequential questions, source grounding, JSON format, no fabricated evidence, and approval boundaries. Chat keeps its full personality. Discovery explicitly asks only blocking unresolved decisions, permits an immediate empty question list, and distinguishes missing documents from missing domain rules. Planning is proportional to scope; coding reuses unchanged available inventory/tool results and keeps summaries concise.

Lossless prompt packing uses compact UTF-8 JSON, shortens the chat command catalog to actual command entries, and replaces exact duplicate document bodies with canonical source references only when shorter. Project document paths are preferred over bundled ones; every source key, unique/conflicting document body, skipped-source record, and inventory entry remains. Full audit snapshots and binding checks are unchanged. No history truncation, output token caps, or undocumented reasoning controls were introduced.

Measurement script uses a deterministic calculator request with generated project guidance duplicating bundled standards, and scripted provider responses. It measures UTF-8 bytes of the same serialized system/messages representation before and after, not tokenizer counts or live latency. No network/model requests are made. Final values:

| Step | Before bytes | After bytes | Reduction |
| --- | ---: | ---: | ---: |
| Discovery | 7878 | 4189 | 46.8% |
| Planning | 7618 | 4125 | 45.9% |
| Coding | 9253 | 5940 | 35.8% |
| Chat | 10359 | 8209 | 20.8% |

Results depend on project guidance duplication and model/tokenizer. This cannot guarantee a faster model answer or eliminate excessive reasoning. before.json, after.json, and measure.py preserve reproducible evidence.

All 149 tests pass on installed Forge Python 3.12.14 using required unittest discovery, including approval, provider, retrieval, source/binding, terminal, and execution tests. New coverage checks exact duplicates with retained source provenance, immutable original context, conflicting/similar guidance preservation, short duplicates never increasing prompt bytes, and lossless Unicode serialization. A retrieval test was corrected to parse supplied JSON rather than require spaces after colons. Full results: unittest.log. git diff --check passed.
