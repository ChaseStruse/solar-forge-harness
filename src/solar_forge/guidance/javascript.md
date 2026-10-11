## JavaScript

Apply these defaults to JavaScript, JSX, MJS, and CJS files. Respect the project's
runtime targets, framework, and existing ES module or CommonJS conventions.

- Follow the configured formatter and linter. Use camelCase for functions and
  variables, PascalCase for classes/components, and existing filename conventions.
  Prefer const; use let when reassignment is needed, and avoid introducing var.
- Prefer strict equality and explicit conversions. Handle null and undefined
  intentionally. Choose nullish defaults when zero, false, and empty strings are
  valid values; do not hide them with accidental truthiness-based fallbacks.
- Validate external data at runtime. Use clear object shapes and focused functions;
  add JSDoc for public APIs or non-obvious contracts when consistent with the
  project. Do not add TypeScript-only syntax to JavaScript files.
- Keep side effects explicit and avoid accidental globals or shared mutable state.
  Do not mutate caller-owned data unexpectedly. Follow framework lifecycle rules
  and remove listeners, timers, and subscriptions when they are no longer needed.
- Use async/await where it fits the codebase. Await promises or explicitly handle
  rejections, preserve useful error context, and avoid empty catch blocks. Support
  cancellation where appropriate and avoid blocking the event loop unnecessarily.
- Respect browser/server boundaries. Do not expose secrets in browser bundles or
  logs, insert untrusted HTML, or interpolate untrusted input into commands or
  queries. Use supported runtime APIs and the existing dependency manager/lockfile.
- Add focused tests for changed behavior, coercion and missing-value boundaries,
  rejected promises, and affected UI interactions. Use existing lint, build, and
  test scripts; report executed checks and remaining verification separately.
