# INPROGRESS

## Current phase

**Working now:** Phase 5 (evaluation, AUDIT.md wave 4) — the RUN of the
pre-registered protocol (docs/EVALUATION.md). Seed-check done 2026-10-03:
the base masora-mdb is now branched on this machine (setup from
git@github.com:10gen/masora-mdb; fresh clone = post-refoundation main;
`masora check` PASSED — the only warning is the known W-REPLAY), the index
is rebuilt for ~/code/mongo (195 lineages / 309 versions; W-CTX-DEGRADED on
114 — shallow clone, recorded not fixed), the cppgraph graph for mongo is
fresh (source_commit = checkout HEAD), and the contamination check is clean
(no masora trace in the checkout's or the global agent config). The corpus
is bound: 20 tasks (16 grounded + 4 controls) → claim ULIDs, run order
shuffled once (seed 20261003), all in the recording sheet at
~/.local/share/masora/eval-2026-10-03/SHEET.md — OFF this public repo
(private base content). Steps: [x] seed-check + binding; [ ] harness dry
run (claude -p, stream-json, per-condition MCP configs); [ ] the 40-run
batch in seeded order (owner-validated cost before launch); [ ] score
(a)–(d), join conditions, apply the §6 verdict rule, archive the sheet.
**The 40-run batch is EXECUTING in the background** (nohup,
~/.local/share/masora/eval-2026-10-03/run_batch.sh, log batch.log, rows in
runs.csv; harness validated by an unscored probe). Scoring happens after
the last run. In parallel (different repo, zero interference — the eval
uses the installed masora 0.7.0 snapshot):

**Phase 6 (team life, AUDIT.md proposals 5-7), wave 6a in progress:**
`unrefute` MCP tool, `masora doctor`, `reset --from-origin`
(plan-then-confirm, never automatic) + the refoundation runbook doc.
Wave 6b follows: SessionStart hook + auto re-index, per-author pending
branch, tombstone-union tooling, CI check action. Nothing pushed.

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
