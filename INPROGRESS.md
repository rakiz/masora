# INPROGRESS

## Current phase

**Working now:** nothing — the audit's Phases 3-6 are implemented,
evaluated (5 batches, the verdict + the saturation analysis recorded in
the off-repo sheet) and RELEASED as 0.8.0 (tag pushed 2026-10-05). The
hooks (SessionStart + UserPromptSubmit) ship in the release; the cppgraph
side runs the v3 contract on the workstation. Next candidates, in the
owner's hands: the colleague rollout, the keywords backfill, the
per-turn hint dedup, the symbol-addressed search fallback (TODO Phase
2). Nothing pushed ahead of the owner.

## Context the next session needs

- A shared knowledge base was REFOUNDED on 2026-10-02 (owner reset): every
  kept lineage re-emitted through the 0.7.0 write path (fresh ULIDs,
  write-time commit + `lines` stamps, anchors re-fingerprinted, fresh verify
  snapshots), then force-pushed over the base's remote `main`. The old base
  is archived (workstation: ~/.local/share/masora/bases/masora-mdb-archived-*).
  The base is 195 lineages / 309 versions, ALL current on mongo master.
- The eval (docs/EVALUATION.md, amended 2026-10-04): WITH models the real
  deployment; the record lives in ~/.local/share/masora/eval-2026-10-03/
  (the Mac) and on the workstation (the final batch) — OFF this repo.
- The workstation (sebastien-mendez-9e5.workstations.build.10gen.cc) =
  mongo master + the full-history clone + the graph + the deployed tools:
  the reference ground; the Mac's ~/code/mongo is a June feature-branch
  snapshot (123 stale THERE is an artifact, not a base problem).
- Standing policy (SPEC.md, first Goal): the base holds architect knowledge
  of the CODE only. The skill and docs/AGENT_INSTRUCTIONS.md teach it.
- Known limitation: standalone `check` does not replay structural proofs
  (W-REPLAY) — the replay provider is not wired.
