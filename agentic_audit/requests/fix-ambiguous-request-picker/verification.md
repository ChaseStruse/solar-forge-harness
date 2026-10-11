# Fix and verification

Read-only inspection of the user's test-harness project confirmed default/request.md still contains the Your request title template, beside the completed calculator request. Picker discovery excludes invalid templates but current_request counts all bundle files. The single-valid-option shortcut therefore bypassed the menu even though the resolver considered the request ambiguous.

The shortcut now checks current_request and only bypasses selection if the resolver returns the sole valid option. Otherwise it opens the picker, including the one-valid-request plus unused-template case. The unused template remains excluded from selectable choices; no external project files were changed.

Regression test reproduces the exact layout through TerminalChat, verifies the menu opens with one valid option and no model call, confirms selection, and checks /prepare completes without the ambiguity error. Read-only request_options on the actual test-harness project returns its calculator request for /prepare. All 139 tests pass using the installed Forge Python 3.12 interpreter. git diff --check passes. Restarting the existing Forge process is necessary to load updated code.
