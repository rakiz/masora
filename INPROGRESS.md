# INPROGRESS

## Current phase

**Working now:** nothing — the audit's Phases 5 and 6 are done (2026-10-03).

- **Phase 5 (evaluation)**: the pre-registered protocol RAN on the real base
  (masora-mdb, branched on this machine via setup; seed-check clean, 20
  tasks bound to claim ULIDs, seed 20261003, 40 runs over two batches —
  batch #1 VOID: the installed cppgraph 0.4.5 rejected facts contract v2
  fail-closed so the WITH injection was dead; deploying the dev repo's
  v0.4.8 fixed the channel, verified live end-to-end). Verdict per §6:
  **FAIL** (tool-call clause 266 > 249; wrong deductions 1 < 3 and tokens
  14.73M < 15.85M pass) — with the recorded engagement fact: the WITH
  mechanism never fired in 80 runs (0 injections — no scoped query hit a
  claim-anchored symbol; 0 masora tool calls), so the deltas are paired-run
  noise. Action: fix recall — the passive channel does not engage under
  neutral conditions; the pre-seeded lever is Phase 2's UserPromptSubmit
  hook. Adoption: owner's decision. Full record: the local sheet
  (~/.local/share/masora/eval-2026-10-03/, OFF this repo).
- **Phase 6 (team life)**: wave 6a (commit 03769fd) — unrefute MCP tool,
  masora doctor, guarded reset --from-origin + the refoundation runbook;
  wave 6b (commit d22d01a) — per-author pending branch, masora union,
  SessionStart hook, CI check template. Both waves reviewed APPROVE (zero
  findings), 871 tests green.

Next: the owner rules on adoption (the verdict's action) and whether Phase
2's UserPromptSubmit hook becomes the recall fix. Nothing pushed.

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
