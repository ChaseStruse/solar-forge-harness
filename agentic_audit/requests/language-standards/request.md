# Request: Language-specific coding standards at initialization

## Description
Enhance forge init to create starter model guidance templates for Python, TypeScript, and JavaScript projects. Continue committing early and often.

## Technical Details
Provide packaged, editable coding-standard templates selected during init or by CLI flags. Detect likely project languages for defaults, support mixed-language projects, and retain generic guidance when no supported language is selected. Write selected guidance into the existing .forge/standards/coding.md so it is included through normal project context. Preserve existing guidance and configuration on repeated initialization. Save new-project language selections for restoring missing guidance.

## Acceptance Criteria
- [x] Python, TypeScript, and JavaScript each have practical starter coding standards.
- [x] Interactive initialization supports language selection with detected defaults.
- [x] Scripted initialization supports explicit selection and bounded automatic detection.
- [x] Mixed-language and generic projects are supported.
- [x] Generated coding guidance reaches model context and remains editable.
- [x] Repeat initialization preserves custom files and can restore missing guidance from saved selections.
- [x] Documentation and required unittest verification are complete, with incremental commits.
