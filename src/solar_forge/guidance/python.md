## Python

Apply these defaults to Python files. Follow the project's supported Python
versions and existing conventions when they differ from this starter guidance.

- Use four-space indentation, snake_case for functions and variables, PascalCase
  for classes, and UPPER_SNAKE_CASE for constants. Follow the configured formatter
  and import order rather than reformatting unrelated code.
- Add useful type hints to public functions and module boundaries. Model optional
  values explicitly; validate external data at runtime instead of treating type
  annotations as validation. Use syntax supported by the project's Python version.
- Keep functions focused and make side effects explicit. Avoid mutable default
  arguments and unnecessary module-level state. Use dataclasses for structured
  data when they fit the existing design.
- Catch specific exceptions where recovery or added context is possible. Preserve
  the original cause when translating errors. Do not swallow failures or expose
  secrets in exception messages or logs.
- Use context managers for files and other resources, explicit text encodings,
  and pathlib where consistent with the project. Parameterize database queries
  and avoid constructing shell commands from untrusted input.
- Follow the existing environment, dependency, and packaging workflow. Prefer
  the standard library when sufficient; justify new dependencies. Keep imports
  free of avoidable network calls or other surprising side effects.
- Add tests for changed behavior, boundary values, and failure paths using the
  project's test framework. Keep fixtures isolated and tests deterministic; mock
  external services at their boundaries. Run configured formatting, linting,
  type checks, and relevant tests, reporting only checks actually executed.
