# Fix and verification

ChatService defines list() before request_options(). Python 3.12 evaluates list[dict] in that class namespace immediately, resolving list to the method and failing import. Python 3.14 deferred annotation behavior hid the startup problem in prior verification.

Added from __future__ import annotations to defer annotation evaluation consistently across supported Python versions.

Verified the actual installed /home/snoodle/.local/bin/forge launcher (Python 3.12.14) with forge --help: imports and CLI startup succeed. Required unittest discovery passed all 138 tests using that installed interpreter, including terminal keyboard tests and localhost HTTP fixtures. Full output is in unittest-python312.log. The suite also passed all 138 tests on Python 3.14.7. git diff --check passed. No reinstall is needed because the installed launcher imports the project source directly.
