---
name: dev-workflow
description: "Multi-step work cycle of a software project managed by TODO.md, INPROGRESS.md, CHANGELOG.md. Triggers on: starting a new task or phase tracked in TODO.md/INPROGRESS.md, finishing a task, updating progress state, creating or updating a source file's .md companion, preparing or verifying a commit (pre-commit hook, dev-workflow.json), suggesting a /compact compaction at a task boundary."
---

# Dev workflow (TODO → INPROGRESS → CHANGELOG)

## 1. TODO/INPROGRESS → CHANGELOG cycle

(`TODO.md`, `INPROGRESS.md` and `CHANGELOG.md` are the default filenames — configurable via `workflow.todo` / `workflow.inprogress` / `workflow.changelog` in `dev-workflow.json`.)

- **At task start**: read `INPROGRESS.md` (current state — resume exactly where marked) and `TODO.md` if it exists (roadmap, phase in progress). If `workflow.spec` of `dev-workflow.json` points to an existing file (e.g. `SPEC.md`), re-read it too.
- **While working**: update `INPROGRESS.md` as you go — tick `[x]`/`[ ]`, record blockers as soon as they appear. Never only before commit.
- **Task/phase done**:
  1. Add an entry to `CHANGELOG.md` (Keep a Changelog format: `## [version] - date` + Added/Changed/Fixed, or date + summary).
  2. Reset `INPROGRESS.md` with the next phase's detail. Never leave it empty or stale.

## 2. .md companions

If `dev-workflow.json` has `companions.enabled: true`:

- Every **newly created** source file gets its companion `.md` (same folder, same name) created **in the same pass**: role of the file, invariants, pitfalls. Not after the fact.
- An existing source file **significantly modified** → its `.md` companion (if it exists) is updated in the same pass.

## 3. Coding conventions

If `workflow.conventions` of `dev-workflow.json` points to an existing file (e.g. `CONVENTIONS.md`), read it before writing or editing code and follow its rules.

Two baseline rules apply **always** — even if the conventions file does not exist or has not been customized:

1. **Comments describe intent, not code.** A comment explains WHY the code does something (a decision, a constraint, a non-obvious tradeoff) — it never restates WHAT the next line already says in code.
2. **Comments describe the current state, not its history.** Outside `CHANGELOG.md`, code comments never narrate evolution — no "changed from X to Y", "previously did Z", "used to be", "old behavior was", "no longer needed but kept for compatibility" phrased as history. A past decision that matters belongs in `CHANGELOG.md` or a commit message, not in a comment describing what the code does today.

## 4. Safety rules

If `workflow.rules` of `dev-workflow.json` points to an existing file (e.g. `RULES.md`), read it before writing or editing code and follow its rules. Any rule that cannot reasonably be respected must be flagged per the deviation protocol described in that file (inline marker + reason in the final report) — this is not optional: unlike the conventions, violations of the rules file always need an explicit flagged justification.

## 5. Spec/design compliance

If `workflow.spec` of `dev-workflow.json` points to an existing file (e.g. `SPEC.md`), re-read it before committing a change that could deviate from it. If a deviation is necessary, **flag it explicitly to the user** — do not decide alone.

## 6. Before proposing a commit

- Verify (or remind the user) that the pre-commit hook passes: checks are defined in `precommit.checks[]` of `dev-workflow.json` (tests + .md companions).
- NEVER suggest `--no-verify` unless the user explicitly asks for it.

## 7. Memory / compaction

- Suggest `/compact` (never run it automatically) only at **natural boundaries**: phase done and committed, completely different subject starting. Never in the middle of an active debug/refactor.
- The suggested message talks about the **next** task: objective + existing reusable base. Never a summary of what was just done (already in git/CHANGELOG).
