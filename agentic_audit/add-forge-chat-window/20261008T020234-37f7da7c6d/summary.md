# Forge chat review

Implemented `forge chat` with a responsive local browser UI, model/provider
selection flags, persistent multi-turn history, project documentation/request
context, saved transcripts and call evidence, and failed-reply retry.

Verification:
- All 27 automated tests passed, including HTTP authentication/origin checks,
  multi-turn persistence, failed HTTP replies/retry, model isolation, and CLI flags.
- Browser verification in isolated headless Chromium passed: suggestion buttons,
  send/reply, safe text rendering, history, new chat, failure/retry, mobile width.
- Desktop and mobile screenshots visually inspected.
- Wheel built; all three browser assets verified in the package.
- `forge chat --help` works in the installed editable user-level CLI.
- JavaScript syntax and Git whitespace checks passed.

Live cloud/local model calls were not performed. Browser tests used an offline
provider stub. Replies do not stream, and chat does not edit project files.
