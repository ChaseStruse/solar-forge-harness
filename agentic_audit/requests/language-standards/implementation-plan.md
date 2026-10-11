# Implementation plan

1. Package separate Python, TypeScript, and JavaScript guidance resources and compose selected sections into the existing coding.md template.
2. Add validated harness.languages configuration for new projects. Detect supported languages from a bounded inventory excluding dependencies, build folders, secrets, symlinks, and audit files.
3. Add the fourth guided setup step and repeatable --language flags (including generic). Explicit flags override detection on new projects. Existing projects preserve saved configuration and files; conflicting flags produce an actionable error rather than silently rewriting guidance.
4. Test per-language and mixed generation, context inclusion, detection, explicit overrides, cancellation before writes, repeated setup, missing-template repair, configuration validation, and packaging.
5. Update maintained documentation, run the required unittest suite, and record evidence in this request folder.
