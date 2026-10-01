---
description: Run the masora CLI and interpret the result
---

The user invoked /masora with: $ARGUMENTS

Run `masora $ARGUMENTS` in the shell and capture BOTH stdout and stderr,
then interpret the combined output: state whether the operation succeeded
or failed. If a diagnostic code appears (E-* or W-*), explain it and
suggest the concrete fix, applying the masora skill's knowledge-base
rules. If the invocation was malformed (a guessed base directory, an
unknown flag), correct it once — the base-taking subcommands (check,
search, gc, compact, index) resolve the base from the checkout's masora
configuration, and the MCP search tool resolves it on its own — and say
what you corrected. Never loop: at most one corrective re-run.
