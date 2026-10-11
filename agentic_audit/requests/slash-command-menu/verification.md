# Fix and verification

The composer had a completer and populated completion state, but the full-screen layout never installed a CompletionsMenu. Previous tests checked state and autofill but did not check rendered menu visibility.

Added a cursor-anchored completion popup using FloatContainer/CompletionsMenu, capped at eight visible rows with scrolling. Added descriptions from the existing command help and explicit highlighted menu colors. Typing / shows available commands, narrower prefixes filter them, and arrow keys select. Enter or Tab fills the command; a separate Enter sends it. Complete commands and arguments still suppress suggestions.

New actual keyboard regression types / and inspects the rendered screen, asserting command choices are visible before any chat/model action. It moves down, confirms the chosen command, and verifies confirmation did not execute it. All 150 tests passed on installed Forge Python 3.12.14 using required unittest discovery. Full results in unittest.log. git diff --check passed.
