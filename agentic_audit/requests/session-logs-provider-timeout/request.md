# Request: Session logs and preparation timeout diagnostics

Investigate /prepare and /discover failures with LM Studio Qwen3.5-9B. Supplied logs show non-streaming requests disconnected at the configured 120-second timeout while only reasoning had been generated. Add /logs to output exportable diagnostics from the current chat session, including linked workflow failures, for future troubleshooting. Preserve historical artifacts and verify with the repository unittest suite.
