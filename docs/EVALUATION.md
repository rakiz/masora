# Evaluation protocol (pre-registered)

> **Amendment 2026-10-04 (recorded before the next run; prior numbers
> void).** Three scored batches showed that the untaught channels do not
> engage: 0 masora tool calls across 60 WITH runs, one claim delivered via
> the cppgraph channel, one via the prompt hook — while the REAL rollout
> ships the usage instructions (docs/AGENT_INSTRUCTIONS.md, the skill).
> The neutral-prompt rule measured a configuration that never ships. It is
> amended to: the task prompt stays neutral (it never mentions Masora, the
> base, or the evaluation), but the masora-delivered context — the recalled
> claims AND the one-line usage instruction carried by the masora hooks —
> is part of the WITH condition by design. The WITH condition now models
> the real deployment. Per the voiding rule above: every number scored
> under the previous rule (batches #1-4) is DISCARDED — the sheet keeps
> them as instrument history, no verdict stands; the next full batch
> (same seed, same corpus, same rubric) computes THE verdict.

This document is written **before** any evaluation run is executed. A
protocol amended after seeing results is void: if a rule here changes, the
change is recorded in this file *and* every number scored under the old rule
is discarded — the batch re-runs from zero. The purpose is to keep the
verdict honest when the person running the evaluation wrote the base being
graded.

## 1. Question and success criteria

Does Masora change agent behaviour, in the direction the phase objective
(MASORA_DESIGN.md §13) claims? Concretely, on the same tasks run under both
conditions:

- **Primary**: fewer **repeated wrong deductions** — assertions the agent
  makes confidently that a recorded claim contradicts or corrects (§4a).
- **Primary**: lower **cost per task** — fewer tool calls or fewer total
  tokens (§4b, §4c).
- **Secondary (the tax side)**: the injected-token cost per task in the WITH
  condition (§4d) — what the injection adds, read against what it saves.

Success is decided by the verdict rule in §6, computed from the recording
sheet — never from narrative.

## 2. Design

Paired A/B, same task, same agent:

- Each task runs **twice** with the SAME agent, model and settings: condition
  **WITHOUT** (no `masora mcp` registered, no injection) and condition **WITH**
  (`masora mcp` registered; the cppgraph injection active with
  `CPPGRAPH_MASORA=1`).
- A **fresh session per run** — no memory of the sibling run, no memory of
  previous tasks.
- The task prompt is identical and neutral in both conditions: it never
  mentions Masora, the base, or that an evaluation is running; in the WITH
  condition the MCP tools and the injected facts speak for themselves.
- **Blind scoring where feasible**: transcripts are scored keyed by run id
  only; the condition label is joined after scoring. The same person runs and
  scores (see §7) — the rubric and the claim-list reference are what keep the
  judgment fixed, not the scorer's memory.

## 3. Task corpus

~20 routine tasks grounded in the REAL base content (the live base holds
~96 lineages over the mongo change-stream / resume-token / SBE areas). A
task must be answerable from the code, and there must be a recorded claim
that prevents a known wrong turn on it — that is the mechanism under test. At
the seed-check (§5) each task is bound to the real recorded summaries it
exercises; a task the base cannot inform is a **control task** — at least 4
of the 20 — included to detect false help (a wrong injection pushing the
agent off a correct answer counts against Masora, §4a).

Example templates (the shape; final wording binds to recorded summaries at
the seed-check):

1. "Where does resume-token invalidation happen, and what triggers it?"
2. "What is the max size a change event can reach before splitting, and what
   enforces it?"
3. "Walk me through the bring-up sequence for the change-stream components —
   in what order do they start?"
4. "Does the change stream re-open when the resume token is null?"
5. "Which lock must be held before calling commitShard, and who acquires it?"
6. "How does SBE stage X decide between slots Y and Z — where is that
   decided?"
7. "What happens to in-progress events when the stream is interrupted
   mid-batch?"
8. "Which component owns the post-batch cleanup, and when does it run?"

For each task the sheet records the claim ULIDs a correct answer must agree
with (the grader's reference list, §4a).

## 4. Scoring rubric

Per run, four numbers:

- **(a) Repeated wrong deductions** — the count of confident assertions in
  the transcript or final answer that a recorded claim contradicts or
  corrects. "Confident" = stated as fact, not raised as a question or
  hedged. The reference is the claim's summary (and, where needed, its
  statement), read by a human grader with the task's claim list at hand.
  Injected misinformation that produces a wrong deduction counts here —
  Masora-caused errors are not hidden.
- **(b) Tool calls** — the run's tool-call count, from the session log.
- **(c) Total tokens** — the run's token total, from the agent's own
  accounting.
- **(d) Injected tokens** (WITH condition only) — the token estimate of the
  rendered `masora:` lines in the responses, counted from the logs; the §6
  rendering budget bounds it (≤ 2 facts, ≤ ~60 tokens per response).

## 5. Procedure

1. **Seed-check** — immediately before the batch: `masora check` on the base
   is clean; the index is rebuilt for the checkout under test; the task list
   is finalized and bound to the recorded claim ULIDs (each task names the
   claims a correct answer must agree with; control tasks name none).
2. **Run order** — the task × condition pairs are shuffled once (seeded RNG,
   seed recorded here: chosen at the first run and written into the sheet)
   and executed in that order, fresh session per run.
3. **Recording sheet** — one row per run: task id, run id, condition
   (joined after scoring), date, session/transcript path, tool calls (b),
   total tokens (c), injected tokens (d), repeated wrong deductions (a) with
   the contradicting claim ULIDs, notes.
4. After the last run: score everything, join conditions, compute per-task
   differences and the totals.

## 6. Verdict rule

The phase objective is met — Masora changes agent behaviour for the better —
when, over the batch:

- the WITH condition's total repeated wrong deductions (§4a) are **strictly
  fewer** than WITHOUT's, **and**
- the WITH condition shows **no token-cost regression beyond the injected
  tokens**: for the batch, `sum(c_WITH − d_WITH) ≤ sum(c_WITHOUT)` — the
  injection's cost is paid for by fewer tool calls / fewer non-injected
  tokens; and tool calls do not regress (`sum(b_WITH) ≤ sum(b_WITHOUT)`).

Anything else is a fail for this phase: the base ships more tokens than it
saves, or it does not prevent the mistakes it exists to prevent. The numbers
decide adoption — a failed verdict is a result, recorded in the sheet and
acted on (shrink the injection, fix recall, or retire the feature), not
narrated away.

## 7. Honest limits

- **Single-author bias** — the base was written by the same person who runs
  and grades the evaluation; the pre-registration, the fixed rubric and the
  claim-list reference are the controls, and they are weak ones.
- **Small n** — ~20 tasks; a single mis-scored deduction can move the
  verdict. The sheet is the raw record; re-grading is allowed only before
  unblinding.
- **Lexical recall** — `search` is FTS: a claim without the query's words
  cannot help, and the injection can miss where it would have mattered. The
  corpus over-represents areas the base covers well; the result does not
  generalize past them.
- **The base knows its author's blind spots** — tasks are chosen where a
  recorded claim prevents a KNOWN wrong turn; a task nobody ever got wrong
  cannot show the effect. The measurement is of prevention, not of general
  competence.
