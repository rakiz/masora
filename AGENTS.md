# AGENTS.md

For AI sessions working **in this repository** (the Masora tool itself — not
a Masora base). Read in this order; on disagreement the earlier file wins:

1. **FORMAT.md** — the canonical event-file contract. It wins over
   MASORA_DESIGN.md; on conflict, amend the design doc, never deviate.
2. **SPEC.md** — stable requirements: goals, non-goals, constraints.
3. **MASORA_DESIGN.md** — design rationale; §12 records settled decisions.
   Items marked *open* are raised, never decided silently.
4. **CONVENTIONS.md** — code and documentation conventions: comments
   describe intent, not history; pushed docs describe state, not evolution,
   in English.
5. **docs/ARCHITECTURE.md** — how the code maps onto the contract:
   canonicalization/schema layer, the fold, checker validation order, the
   sync pipeline, what is not built yet.
6. Dev-workflow state: **TODO.md** (roadmap), **INPROGRESS.md**,
   **CHANGELOG.md** (entries added when work is done, never before);
   process in `.opencode/skill/dev-workflow/SKILL.md`.

## Invariants

- The `.md` event files of a Masora base are append-only: never modify or
  delete an existing event (FORMAT.md §1). Corrections are new events — a new
  claim version, a refute, an unrefute. Whole-lineage deletion belongs to
  `masora gc`.
- Diagnostic codes are the error surface: a new code goes into
  `masora/diagnostics.py` **and** `docs/TROUBLESHOOTING.md` in the same
  change; `tests/test_docs.py` enforces the two-way sync.
- The fold rule is proven by an executable spec
  (`tests/test_fold_bruteforce.py`); when touching `masora/fold.py`, keep the
  oracle and the brute-force coverage intact.

## Commands

- `uv run pytest -q` — full suite, must stay green (the pre-commit check runs
  it).
- `uv run masora check <base-dir>` / `uv run masora sync --help` — exercise
  the CLI; `tests/fixtures/` holds example bases.

## Review culture

- Every change goes through review; findings are graded MAJOR/MINOR and each
  one is addressed explicitly — fixed, or reported back, not dropped.
- No silent semantic invention: a failing case is never quietly skipped or
  narrowed. Skipped, deferred or out-of-scope work is reported as such.
