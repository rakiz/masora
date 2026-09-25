# Coding conventions

<!-- Default rules shipped with dev-workflow-kit. They always apply — even if
     this file is never customized. Extend the "Project rules" section below
     with your own (naming conventions, formatting, language-specific idioms,
     error-handling policy, ...). The dev-workflow skill reads this file
     before writing or editing code (path: workflow.conventions in
     dev-workflow.json). -->

## 1. Comments describe intent, not code

A comment explains WHY the code does something — a decision, a constraint, a
non-obvious tradeoff. It never restates WHAT the next line already says in
code.

## 2. Comments describe the current state, not its history

Outside `CHANGELOG.md`, code comments never narrate evolution: no "changed
from X to Y", "previously did Z", "used to be", "old behavior was", "no
longer needed but kept for compatibility" phrased as history. A past
decision that matters belongs in `CHANGELOG.md` or a commit message — not in
a comment describing what the code does today.

## Project rules

<!-- Add your project's own rules here, one subsection per rule, same style
     as the two above. Delete this comment as you fill them in. -->
