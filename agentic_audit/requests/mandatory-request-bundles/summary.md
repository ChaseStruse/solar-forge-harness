# Implementation and verification

Required request entry point: `agentic_audit/requests/<request-name>/request.md`.
CLI request creation uses a title-based folder; setup creates a default starter; chat saves and remembers separate title-based bundles. External request paths are rejected by preparation and freshness checks. Request context includes supported text files in the selected bundle, with existing size, secret, and symlink protections. Context changes invalidate prepared runs. Model file tools still cannot write audit data.

Moved the baseline, chat, and terminal-chat source requests and implementation plans from docs into request bundles. Historical run artifacts are unchanged. Added repository-wide mandatory instructions in AGENTS.md and updated user documentation.

Verification: 60 unittest tests pass, including CLI/local HTTP integration, terminal chat, request-path rejection, bundle isolation, context-change detection, size bounds, symlink rejection, and multiple-request selection. Used a temporary virtual environment containing the project's declared prompt_toolkit dependency. Git diff whitespace check passes.

Non-text attachments may be stored alongside requests but are not automatically sent to providers. Existing external requests require relocation and a fresh prepare; historical snapshots remain readable.
