---
description: Run the masora CLI and interpret the result. Use when the user wants to check, sync, or otherwise invoke masora directly.
argument-hint: "[args]"
allowed-tools: Bash(uv run masora *)
---

Output of `uv run masora $ARGUMENTS`:

!`uv run masora $ARGUMENTS`

Interpret this output: state whether the operation succeeded or failed. If
diagnostic codes appear, explain them (consult docs/TROUBLESHOOTING.md) and
suggest the concrete fix. Do not re-run the command unless a follow-up
verification is genuinely needed.
