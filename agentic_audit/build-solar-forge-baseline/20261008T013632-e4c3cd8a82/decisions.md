# Bootstrap decisions

- Python chosen within the user's Python-or-Rust preference.
- Standard-library runtime keeps installation and provider boundaries simple.
- Provider-agnostic JSON actions enable local models without native tool support.
- Every generated domain question blocks planning; answers persist immediately.
- Plan approval is required before file edits; new questions require a revised plan.
- Shell, Git, and deployment execution remain future work pending an isolated runner.
- No additional user answers were required for this baseline; application-specific
  decisions are deferred to project guidance and generated request questions.
- The user explicitly requested frequent commits, recorded below.

This is a retrospective bootstrap audit of the development session. It was not
produced by the new CLI's model workflow, and it contains no simulated model calls.
