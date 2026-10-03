# INPROGRESS

## Current phase

**Working now:** nothing — the sync selection feature (TODO.md Phase 2.5,
`--only`/`--exclude`) is committed (67f3fbb) and eligible for the next release. The owner-facing
audit is in AUDIT.md (uncommitted): top items = wire the structural proof
replay, fix the publication-gate deletion bug, freshness automation. Next
task: run the pre-registered evaluation, then the first rollout (TODO.md).

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
