# INPROGRESS

## Current phase

**Working now:** nothing — Phase 3 (correctness sweep, AUDIT.md waves 1-2) is
IMPLEMENTED (uncommitted): H2 sync --push preservation of committed excluded
events, H3 search hardening (safe MATCH expression, bm25 ranking, 20-hit cap
with omitted count), the publication gate (origin tombstones applied from the
post-fetch origin/main; stale local mains neither resurrect nor brick), M10
atomic event writes, M9 gc fetch + tombstone-remedy wording, M5 secret-scan
field coverage, H1 "proof not replayed" honesty step, H4 `source: human`
refused over MCP (E-MCP-HUMAN), the FORMAT/SPEC contract amendments (fixed
`lines` ref set, code-only v1 anchors, M1 graph staleness meta split), and
the M11 ULID skew policy documentation. Suite 779 green, ruff clean. Next:
the orchestrator commits the wave; then Phase 4 (robustness/perf sweep) and
the pre-registered evaluation. The owner-facing audit is in AUDIT.md
(uncommitted).

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
