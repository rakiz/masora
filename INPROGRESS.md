# INPROGRESS

## Current phase

**Working now:** Phase 2's UserPromptSubmit hook (TODO.md Phase 2, the
recall-fix lever the eval verdict pointed at): FTS over the prompt →
inject 2-3 claims with status labels (claude-native hook; opencode keeps
the snippet degradation); thresholds (min prompt length, min FTS score),
the §10.1 caps (≤ 3 claims, ~100 tokens, hard wall-clock budget), silent
failure, stateless v1, never a synchronous index rebuild. The shipped
SessionStart hook (6b) stays the freshness channel. After commit +
deploy: eval batch #4 (same seed, same protocol) measures the full stack.

Context: the eval ran three scored batches (verdict FAIL each time, the
failing clause moving — noise around a barely-engaging treatment); the
full record lives in ~/.local/share/masora/eval-2026-10-03/SHEET.md (OFF
this repo). Facts contract v3 is deployed; cppgraph c1d543c implements
§9.10-12, its v3 adaptation rides the §9 ritual. Phases 3-6 committed
(through 354f535), 891 tests green. Nothing pushed.

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
