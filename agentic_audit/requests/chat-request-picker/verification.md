# Verification and change summary

Implemented in commits 18f7b62 (selection service) and ee23ac7 (terminal picker). Final documentation and approval regression test are committed separately. Prior authorized session-log work was committed as 07b9330.

Missing run selection for /plan, /run, /discover, /answer, /changes, and /approve now opens a terminal request menu. Ambiguous request selection for /prepare, /edit-request, /request show, and /next also opens the menu. Existing selections and explicit command arguments retain their behavior; request-only actions resolve a sole request automatically. Up/Down moves the selection and scrolls it into view, Enter chooses it, and Escape cancels without losing the command. Empty projects provide a request-creation hint.

Request choices show titles and latest run status. Provider-free selection resumes the latest coding run, records the selection, and clears previous plan review state. Unprepared requests offer /prepare in the composer. Selecting through /approve opens /run review and never starts coding automatically. Invalid/unreadable request bundles are excluded; disappearing selections fail without launching the original command.

The full required unittest discovery ran using the project dependency in /tmp/forge-check-venv and unrestricted localhost fixture access: 138 tests passed. Full output is in unittest.log. Actual terminal pipe-input tests verify Up/Down, Escape, Enter, continuing /plan, ambiguous /prepare, empty/unprepared requests, and maintaining approval requirements. git diff --check passed.
