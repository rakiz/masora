---
description: Run the masora CLI and interpret the result
---

The user invoked /masora with: $ARGUMENTS

Run `masora $ARGUMENTS` in the shell and capture BOTH stdout and stderr,
then interpret the combined output: state whether the operation succeeded
or failed. If a diagnostic code appears (E-* or W-*), explain it and
suggest the concrete fix, applying the masora skill's knowledge-base
rules. Correct a failed invocation AT MOST ONCE — and say what you
corrected. When a base-taking subcommand (check, search, gc, compact,
index) fails because its first positional does not exist as a base
directory, the first word was part of what the user meant, not a path:
re-run with the positional omitted entirely (the base then resolves from
the checkout's masora configuration). For `search`, quote the remaining
words together as the single query, e.g. `masora search 'shard key'`; for
the other base-taking subcommands, simply drop the invalid first
positional and keep any other arguments and flags as given. The MCP
search tool also resolves the base on its own. Never loop: at most one
corrective re-run.
