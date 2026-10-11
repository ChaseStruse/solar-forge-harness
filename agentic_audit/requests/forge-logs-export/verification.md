# Change and verification

/logs now writes a uniquely named Markdown export under .forge/logs in the current project and retains an identical copy in the historical chat audit folder. It reports both the relative and absolute export path instead of flooding the terminal with the diagnostic text. The existing pending-reply, linked-run, and no-model-call behavior is preserved. Safe workspace path validation rejects symlinked destinations.

forge init creates .forge/logs for new and existing projects and preserves existing exports. /logs also creates its destination directory automatically for projects initialized with older versions. No files in the user's external test project were changed.

Verified export path/content/audit-copy preservation, repeated exports, pending failed reply handling, init directory creation, repeated initialization preserving an existing export, and recreating the logs folder for an existing project. Required full unittest discovery passed 140 tests on the installed Python 3.12 interpreter; see unittest.log. git diff --check passed.
