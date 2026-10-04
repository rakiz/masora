# INPROGRESS

## Current phase

**Working now:** nothing committed in flight — the evaluation has now run
THREE scored batches (2026-10-03/04). Batch #1 VOID (dead injection
channel: installed cppgraph 0.4.5 vs facts v2); batch #2 scored FAIL on
the tool-call clause; batch #3 (extended cppgraph instrument: find/outline
injection + presence hint) scored FAIL on the wrong-deductions clause
(3 WITH vs 2 WITHOUT) — with the paired analysis showing the T04/T13
pairs netting to zero and the single task-level delta involving no
injection: noise around a treatment that engaged 8/20 runs but delivered
ONE real fact (plus 26 presence-hint lines). Full record in the local
sheet (~/.local/share/masora/eval-2026-10-03/SHEET.md — off this repo).

The instrument has since advanced: masora facts contract v3 is DEPLOYED
(anchor_leaf, examined/matched counters, masora-owned presence_hint —
commits da8c076, bf10a3c, 354f535; NOTE: `uv tool install --force` served
a stale cached wheel, `--reinstall` is required); the cppgraph side
c1d543c implements §9.10-12, and the remaining cppgraph adaptation to v3
(the verbatim hint field + the differentiated staleness line) rides the
§9 ritual. The standing §6 action is unchanged: FIX RECALL — the untried
lever is Phase 2's UserPromptSubmit hook (prompt-time injection); a
batch #4 measures the full stack once it exists.

Phases 3-6 of the audit are all implemented and committed (through
354f535); 891 tests green. Nothing pushed.

## Context the next session needs

- A shared knowledge base was REFOUNDED on 2026-10-02 (owner reset): every
  kept lineage re-emitted through the 0.7.0 write path (fresh ULIDs,
  write-time commit + `lines` stamps, anchors re-fingerprinted, fresh verify
  snapshots), then force-pushed over the base's remote `main`. The old base
  is archived on the workstation (full git history). Any clone made before
  that swap must fetch + reset onto the remote main before writing anything.
  Rollout details stay OFF this public repo — private base, private
  workstation.
- Standing policy (SPEC.md, first Goal): the base holds architect knowledge
  of the CODE only — no process/workflow fiches, no ticket references, no
  evergreen/CODEOWNERS content. The skill and docs/AGENT_INSTRUCTIONS.md
  teach it.
- Known limitation surfacing in rollout: standalone `check` does not replay
  structural proofs (`W-REPLAY`) — the replay provider is not wired.
