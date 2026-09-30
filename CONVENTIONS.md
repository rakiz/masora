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

## 3. Documentation conventions

The same discipline governs every pushed file — code comments, docs, README,
CHANGELOG:

1. **State, not history.** Documentation describes what the thing IS, never
   how it got there. Framings such as "replaces X", "was Y", "previously",
   "bump", "breaking", "no longer delivery pending" are forbidden: a reader
   must learn the current design, not its evolution. (Sections 1–2 above are
   the same rule for comments: a comment describes intent and the current
   state, never the code's past.)
2. **The CHANGELOG exception.** Within a version, a CHANGELOG section is
   release-notes for the current state only; the history of how the project
   got there lives between released versions (Keep a Changelog format), and
   already-released sections keep that historical form.
3. **English only.** All pushed content is written in English, always. Base
   event files are pushed content: their content (summaries, statements,
   reasons, evidence) is English too.

A past decision that matters belongs in `CHANGELOG.md` (between released
versions) or a commit message — never as evolution talk elsewhere.

## Project rules

<!-- Add your project's own rules here, one subsection per rule, same style
     as the two above. Delete this comment as you fill them in. -->
