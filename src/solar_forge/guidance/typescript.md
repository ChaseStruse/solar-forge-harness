## TypeScript

Apply these defaults to TypeScript and TSX files. Follow the existing framework,
compiler settings, module system, and browser or server compatibility targets.

- Use the project's formatter and linter. Use camelCase for functions and values,
  PascalCase for types and classes, and existing filename/export conventions.
  Keep formatting-only changes separate from unrelated behavior changes.
- Preserve the configured strictness. Prefer precise types, discriminated unions,
  and narrowing over any, broad casts, or non-null assertions. Use unknown for
  untrusted values and validate them at runtime; static types do not validate
  JSON, API responses, environment variables, or user input.
- Make public API and shared data contracts explicit. Represent absent values
  deliberately and handle union cases completely. Use type-only imports where
  compatible with the project's compiler and module settings.
- Keep modules focused and separate side effects from data transformations. Avoid
  shared mutable state; prefer readonly contracts where mutation is not intended.
  Follow framework lifecycle rules and clean up subscriptions and event listeners.
- Await promises or deliberately handle their rejection. Propagate useful error
  context, avoid empty catch blocks, and support cancellation for work that can
  outlive its caller. Do not block the event loop with avoidable synchronous work.
- Respect trust boundaries: validate inputs, avoid unsafe HTML insertion, and keep
  secrets out of client bundles and logs. Use the project's dependency manager and
  lockfile; do not introduce a new build system or framework without a reason.
- Test runtime behavior as well as type contracts, including invalid inputs,
  asynchronous failures, and affected UI interactions when applicable. Run the
  existing type check, lint, build, and relevant test scripts; report actual results.
