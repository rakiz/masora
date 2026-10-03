# AUDIT — 2026-10-03 (validated)

Point-in-time audit of the Masora tool and its contracts, after the 0.7.0
release (branch/version context stamping) and the first shared-base
refoundation. Method: one code-level defect pass, one architecture/product
pass, then an INDEPENDENT heavy-model validation of every load-bearing
claim (false-positive hunt over the cited file:line, missed-major hunt,
judgment check). This document incorporates the validation's corrections —
each finding below was re-derived against the code unless marked otherwise.
Suite state at audit time: 764 tests green, ruff clean.

## Executive summary

The contract work (FORMAT, the fold's brute-force oracle, the two-tier
sel) is unusually rigorous, and the core codebase is sound. But the
product's two CENTRAL claims are both currently unbacked, and the audit's
own first pass missed the channel that matters most:

1. **"Structural claims are machine-verified" — the replay is not wired.**
   `verified` on a structural claim is never machine-checked (H1,
   confirmed and worse than first stated).
2. **"Knowledge is recalled fresh" — freshness is manual**, and the
   primary recall channel (search) is brittle: raw FTS5 MATCH on
   natural-language queries raises syntax errors on ordinary C++
   identifiers, results are oldest-first with no ranking and no cap.
   The pre-registered evaluation would measure THIS broken channel.
3. **Trust labels are forgeable**: any MCP caller can pass
   `source: human`; the tool autofills the owner's git user.name. PR
   review is the only gate on the label the whole trust story rests on.
4. **A data-loss window in `sync --push`**: locally COMMITTED events that
   were excluded from a selection (or written by another session) are
   dropped from the local branch by `update-ref` + `reset --hard` —
   breaking the "excluded events stay pending locally" guarantee for
   committed events (recoverable only via reflog).

No injection or path-traversal holes: subprocess calls are list-form,
path resolution is guarded, the secret scan gates the write path (but
misses fields — M5). The validated severity ladder below replaces the
first draft's.

## Corrected findings ladder

### HIGH (act before anything else)

| # | Where | Finding | Validated fix |
|---|---|---|---|
| H1 | `mcp.py` verify + note paths | Structural `proof_query` is never replayed; the promised suspect-on-replay-mismatch (FORMAT.md:145-150) does not exist; `expect` is authored by the same LLM that verifies. Cheap honest step NOW: a structural `verified` must say explicitly "proof not replayed" (status or flag) + amend SPEC.md:16's promise; real replay (needs cppgraph query execution pinned to a provider version) is its own phase — the S-M estimate was optimistic. |
| H2 | `sync.py:366-372` | **`--push` drops locally committed events** that were excluded/`--only`-filtered: the branch commit tree is origin + selected events only, then `update-ref main` + `reset --hard` — the excluded commits vanish from the work tree (reflog only). Fix: keep unselected committed events on main (rebase onto the pushed tree or refuse when main has unselected commits). |
| H3 | `index.py` search | **Search is the broken channel**: raw FTS5 MATCH — `auth.token`, `what's`, `C++`, `a/b` all raise syntax errors on real code identifiers; no bm25 ranking (`ORDER BY lineage, version` = oldest-first); no cap (`*` dumps the whole base). Fix: quote/escape the match expression, rank, cap + report the cap (SPEC requires it). PREREQUISITE to running the evaluation. |
| H4 | `mcp.py` note/verify | `source: human` is caller-declared and forgeable (prompt-injected agent gets turnkey owner impersonation; instructions tell agents `verified(human)` is trusted). Fix at minimum: `human` requires a local interactive confirmation, or is refused from MCP. |

### MEDIUM

- **M1 (fix revised)**: a graph-unavailable build stores `graph_commit=""`
  and reads stale forever. NOT `stored.get(...)` — that would hide the
  genuine "graph became usable later" staleness. Store the observed
  source_commit in a separate meta key even when unavailable.
- **M2**: anchors fingerprinted twice per build (compose + resolve
  internals) — memoize per `(provider, identity)`.
- **M3 (nuanced)**: a note does 2 full `check_base` parses + an rglob;
  a verify does ~4. O(n) per write, O(n²) bulk — not "~4 parses" for
  everything. Still the perf wall at rollout scale.
- **M4**: no `timeout=` on any subprocess (and no `GIT_TERMINAL_PROMPT=0`)
  — a hung git blocks sync; an MCP search can spend the whole probe
  budget in one call.
- **M5**: secret scan misses `name`, `unanchored_reason`,
  `proof_query.args/expect`.
- **M6 (downgraded)**: explain's sqlite handle not closed — hygiene, not
  a leak (CPython finalizes).
- **M7**: deep-YAML `RecursionError` escapes as a traceback (aliases are
  already rejected — billion-laughs covered).
- **M8 (downgraded)**: base-basename index collision requires the same
  repo + same basename — rare; hash the base path anyway.
- **M9 (new)**: gc's published-ness test reads a possibly stale
  remote-tracking ref without fetch → a lineage on origin/main counts
  "unpublished", skips its tombstone, and is resurrected at PR merge.
  Conversely a tombstoned lineage is a hard `E-TOMBSTONED`: one bad merge
  halts every writer's check and `precheck` refuses all writes.
- **M10 (new)**: event writes are not atomic (`write_text`, no
  tmp+rename) — a concurrent session's check can read a half-written
  file, fail, and unlink its own valid event.
- **M11 (new)**: the ULID wall clock is the fold's logical clock; with
  multi-writer skew a slow clock silently loses tier-2 ordering (skew is
  warned, not solved).

### LOW (bundled)

Order-dependent fold convergence on mutual-refutation cycles
(docstring overpromise) · `gh` JSON traceback · missing git binary → raw
`FileNotFoundError` · non-atomic `deleted.toml` read-modify-write ·
`auto_base` silently skipping a matched-but-malformed mapping
("never silently skipped" violated — wrong-base write risk) · MCP
search without repo_root keys a duplicate index by base dir (double
probe budget) · stdio locale-dependence · event-ULID given to `explain`
renders an empty story · `setup.py` clone without `--` before the URL ·
config regeneration drops comments · concurrent index builds share a
fixed `.building` name · `proof_query` float args stringified.

## Design weaknesses (validated)

1. **Probe budget degrades newest knowledge first** — confirmed
   (ascending-lineage order), but conditional: exhaustion needs ~500+
   distinct establishing commits or a 30+-version hub lineage, and is
   flagged `degraded` when it matters. Real at scale; not today's fire.
2. **`degraded` is per-version, never joint** — confirmed; two
   unprovable versions that only together change the display each read
   `exact`.
3. **`relation_unknown` exempt from `degraded` but can flip tier
   membership** — confirmed; the common squash-repo case slips through.
4. **FORMAT.md overclaims on `lines`, TWICE** — "EVERY line ref" vs the
   silent 16-cap (lexicographic — `main` sorts after `feature/*`), and
   "feeds the off-version guard's evidence" while nothing reads the
   stamp at all. Fix the doc either way; if kept, capture a small FIXED
   ref set (HEAD upstream + default branch), not first-16-lexicographic.
5. **Spec legibility debt**: SPEC.md:11 is a ~2000-character sentence;
   the 5-flag status tuple + three counterfactuals need a readable
   mental-model doc for contributors.
6. **One-shared-base assumptions too deep**: fixed `masora/pending`
   branch (concurrent syncs collide), `main` hardcoded (a
   `master`-hosted base cannot sync), `auto_base` first-mapping-only
   (the "read together" doc describes nonexistent behavior), and sync's
   `_require_repo_root` refuses the sub-directory bases that `setup
   url#path` explicitly onboards — a direct setup/sync contradiction.
7. **Compact's git-free proof covers 3 assignment families** — no
   out_of_line demotions, no mismatch outcomes; a future context kind
   escapes the guarantee silently.
8. **Tombstone "concurrent gc PRs merge by union" is aspirational** —
   git does not union-merge TOML; no union tooling exists.

## Operational risks (ranked)

1. **Silent recall decay** — nothing pulls, nothing rebuilds a stale
   index, no metric observes it; the 2s facts timeout can silently
   disable the primary injection channel.
2. **Forgeable trust labels** (H4) — the injection surface of recalled
   content into every agent's context is unaddressed by the secret scan.
3. **Remote history rewrite reads as tampering** — after a refoundation
   force-push, honest clones report mass `E-REWRITE`. The audit's first
   draft wanted the tool to say "refounded — reset": REJECTED by
   validation — distinguishing refoundation from tampering needs an
   out-of-band signed epoch marker; softening it weakens tamper
   evidence. A `reset --from-origin` helper must require explicit
   confirmation, never run automatically.
4. **Secrets in base history** — high-confidence regex only; removal =
   refoundation. No runbook.
5. **Open publication-gate bug** — deletion detection is
   merge-base-relative; a stale local main hides already-published
   deletions (TODO Bug tickets).

## Product direction (validated reordering)

1. **Search hardening FIRST** (H3) — the evaluation measures this
   channel; running it on a broken ranker is worse than waiting.
2. **Run the pre-registered evaluation** — still the go/no-go evidence.
3. **Publication-gate fix + `--push` data-loss fix** (they guard the
   append-only invariant and are small) + replay's cheap honest step.
4. **Freshness automation** (SessionStart hook + auto re-index).
5. **Multi-writer hygiene** (per-author pending branch, tombstone-union
   tooling, CI check action, `unrefute` tool).
6. **Explicitly cut or freeze**: `cost_tokens` (nobody reads it);
   further facts-contract versions until cppgraph's PENDING items land;
   `same-as`/co-change stay cut. The `lines` stamp: KEEP capturing but
   limited to a fixed ref set; freeze new consumers; fix the two
   FORMAT.md overclaims either way.
7. **Scale ceilings to watch**: full-rebuild index to ~10⁴ events;
   `index_stale()` walks the base tree per read; first MCP call on a big
   base is a minutes-long synchronous build.

## Next-phase proposals (validated order)

| # | Proposal | Effort | Timing |
|---|---|---|---|
| 1 | Search hardening (escape, rank, cap) | S | NOW — prerequisite to the evaluation |
| 2 | Run the pre-registered evaluation | M | Right after 1 |
| 3 | Publication-gate fix + `--push` local-commit preservation | S | Now — append-only invariant |
| 4 | Replay honesty step (mark "not replayed" + SPEC amend); real replay scoped to cppgraph later | S then L | Cheap step now |
| 5 | Freshness automation (hook + auto re-index) | M | Now — top operational risk |
| 6 | Multi-writer kit: per-author pending branch, tombstone union tooling, CI check action, `unrefute` | M | Before a 2nd writer |
| 7 | `masora doctor` + refoundation runbook (explicit-confirm `reset --from-origin`) | M | Month-one support load |
| 8 | Probe-budget scaling (commit-graph ancestry; recency-first with an old-lineage floor) | M | Before base ×10 |

## Hygiene

- FORMAT.md example carries the owner's first name — replaceable.
- Release-trail noise in history (a `chore: release 0.8.0` commit, a
  folded heading) — this project's subject is provenance; keep the
  trail immaculate going forward.
- pyproject/README say Python ≥ 3.13 (not 3.12).
