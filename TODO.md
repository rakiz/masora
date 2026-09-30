# TODO

## Context

AI coding agents re-derive the same project knowledge every session, forget corrections, and re-invent wrong deductions. Masora is a git-backed, append-only knowledge base of claims anchored to code and documentation artifacts, with provenance, a verification lifecycle and self-invalidation; the stable requirements are in SPEC.md, the design brief in MASORA_DESIGN.md.

## Open questions

Settled 2026-09-25 with the design owner — decisions recorded in MASORA_DESIGN.md §12 and reflected in SPEC.md: items 1–5 and 7. Items 6 (`same-as`) and 8 (co-change mining) remain postponed. Non-blocking refinements from the design review are listed at the end of MASORA_DESIGN.md §12.

## Phases

### Phase 1: v0 core

Objective:

A minimal end-to-end core, enough to see whether Masora changes agent behaviour (MASORA_DESIGN.md §13).

Tasks:

- [x] Pre-flight: check name availability — `pip index versions masora`, GitHub, npm (§3). Kept: **masora** (PyPI free; npm empty 2020 placeholder; GitHub username taken, irrelevant).
- [x] `masora setup --base <url>`: writes `~/.config/masora/config.toml` from the base's own `base.toml` (+ first-run init). → `masora/setup.py`, `masora/config.py` (remote normalization, `MASORA_HOME`), sub-directory bases via `#<path>` (partial clone + sparse checkout).
- [x] Claim/verify/doubt/undoubt/refute/unrefute `.md` format + layout of §7 (month-bucketed lineage dirs). → **FORMAT.md**, frozen after the full audit chain (commit 6162bbc).
- [x] Decide the frontmatter schema (Q5) — settled 2026-09-25, see MASORA_DESIGN.md §12.5 (mandatory `summary:`, explicit `unanchored:`, neighbour snapshot, `.verify` events).
- [x] `masora check`: validates event schema and append-only history (local command; run by `sync`). → `masora/` package, standalone whole-tree mode, 190 tests, fold proven by brute force (commit 3869b49); append-only diff vs merge-base lands with `sync` (§7.9).
- [x] `masora sync`: runs `masora check`, batches local events into one branch + PR to the shared base.
- [x] Documentation: human-readable README (what/why, the Masoretes story, event lifecycle write→check→sync→PR→merge→recall, quick start) + troubleshooting table for every `E-*`/`W-*` diagnostic code (cause + remedy, generated from `masora/diagnostics.py` so it cannot diverge) + `AGENTS.md` for AI sessions pointing at the canonical contracts (FORMAT.md, SPEC.md) instead of re-deriving from code. → README.md, docs/ARCHITECTURE.md, docs/TROUBLESHOOTING.md (33-code table), AGENTS.md, tests/test_docs.py two-way sync guard.
- [x] `masora gc`: deletes whole lineages on explicit, confirmed request (`--lineage`); no auto-suggestions in v1. → `masora/gc.py` (plan-then-confirm: plan exits 3, `--yes` executes; pre/post `masora check`; tombstone appended to `deleted.toml`, event files removed; `sync` accepts tombstoned whole-lineage deletions and applies them to the merged tree).
- [x] SQLite index + resolution algorithm of §6.2 + FTS. → `masora/index.py` (full-rebuild SQLite+WAL DB at `<masora_home>/indexes/<base-slug>/<repo-slug>-<hash>.db`, FTS5, tombstone exclusion, base-HEAD staleness) + `masora/resolve.py` (pure §6.2 status tuple over `masora/fold.py`, injectable provider registries, `suspect` per §12.4) + CLI `index`/`search` (E-IDX-*/W-IDX-* diagnostics); `code` anchors report `unknown` until the cppgraph provider.
- [x] MCP tools: `note`, `verify`, `doubt`, `undoubt`, `refute`, `search`, `list_stale`. → `masora/mcp.py` (hand-rolled MCP stdio server: newline-delimited JSON-RPC 2.0, protocol version pinned `2025-06-18` and negotiated the standard way — the initialize result always carries it, `initialize`/`notifications/initialized`/`tools/list`/`tools/call` only, parse-error resilience with W-MCP-PROTO) + `masora/write.py` (one event-writing path: base resolution explicit `base` param → mapping match → `default_base` → `E-MCP-NO-BASE`, shared `check_base` pre-check + post-write `check_base` with unlink-on-failure atomicity, write-time anchor resolution + fingerprints + snapshots via `masora/providers.py`, canonical block-style emission with control-char escaping, `E-MCP-GRAPH` behind-HEAD refusal per §5.2, verify drift refusal `E-MCP-DRIFT` per §7.7; lineage ids ride the fold to the displayed version; `search`/`list_stale` auto-build a missing index, surface `W-IDX-STALE` without rebuilding).
- [x] Write path rejects credential-shaped content. → The shared write path (`masora/write.py`, single pipeline → covers all MCP write tools and future CLI writes) scans `summary`/`statement`/`reason`/`evidence` for HIGH-CONFIDENCE shapes only — PEM private-key blocks, AWS `AKIA…` ids, token prefixes (`ghp_`, `github_pat_`, `sk-`, `xoxb/bp/app`), and `password=`/`token=`/`secret=`-style assignments with 20+ char mixed-class values — and refuses with `E-WRITE-SECRET`, nothing written (FORMAT.md §6). Discussing passwords passes (deterministic regexes, no dependency; documented in docs/TROUBLESHOOTING.md).
- [x] Code anchor provider via cppgraph with per-symbol definition fingerprint.
- [x] Edge-set fingerprint per symbol (hash of outgoing edges) — input to the settled `suspect` rule (§12.4).
- [x] Neighbour snapshot (per-anchor snapshot: each anchor's own edge-set hash plus its direct neighbours, identity → edge-set hash) recorded at write time and in `.verify` events — baseline for `suspect` comparison. (Provider-side computation: `masora/providers.py` answers both for the index; the write path records at write/verify time.)
- [ ] Injection of known facts into cppgraph responses (requires changes in the separate cppgraph repo).
- [x] `masora facts --repo [--symbol]`: versioned JSON contract for the cppgraph injection (docs/CPPGRAPH_INTEGRATION.md). → `masora/facts.py` (strictly read-only: base resolved via the config mappings/default_base for `--repo`, existing index read and never built — missing/unusable = exit 1 with `E-FACTS-NOINDEX`/`E-IDX-CORRUPT` on stderr, nothing on stdout; one compact JSON document `{contract_version, repo_head, graph_commit, stale_warning, facts[]}`; `--symbol` matches the displayed version's anchors verbatim, or the newest version for `resolution: none`/founderless lineages where `displayed` is null; `stale_warning` = the `index_stale()` four-axis drift comparison (base HEAD, code HEAD, graph indexed commit, filesystem freshness — see the freshness item below), `null` when nothing is comparable; the two warning classes stay in-band and never error).
- [ ] Fallback without cppgraph: exercise the base via CLI/MCP `search` by symbol.
- [x] Injections emitted as evidence envelopes (validity, anchor, provenance). → The `masora facts` contract (contract_version 1, docs/CPPGRAPH_INTEGRATION.md §3) carries all three SPEC-line-16 legs per fact: validity (resolution + verification `verified(<source>)`/`unverified` + flags), anchor (the effective version's FULL `anchors` identity list beside `anchors_matched`) and provenance (`source`/`name`/`effort` — FORMAT.md unified provenance); the cppgraph-side rendering of these fields stays with TODO line 35.
- [ ] Skill / AGENTS.md instructions: search-before-investigating, when to `note`, capture triggers from §10.3.
- [ ] `E-MCP-NO-BASE` remedy: when a tool call omits `repo_root`, the diagnostic suggests passing it (first-rollout friction: the error read as a config problem when it was a call-site omission). → `masora/write.py` message, `tests/test_mcp.py`.
- [ ] `note` tool description states the field split: `summary` = the injected one-liner (≤ 120 chars), `statement` = the full text (first-rollout friction: an agent hit `E-SUMMARY` at 123 chars and did not know the split). → `masora/mcp.py` tool descriptions, `tests/test_mcp.py`.
- [x] Index freshness on uncommitted writes (rollout friction: a `note` wrote an event file but the SQLite index stayed frozen — `masora facts`/`search` silently missed the just-written claim, because the staleness axes compare git HEADs and an uncommitted write moves none). → `masora/index.py`: `index_stale()` gained a FOURTH axis — filesystem freshness: the build moment (`built_at` in the index meta, UTC ISO) against the newest mtime across the base tree's event `*.md` + `deleted.toml` (one cheap walk per read, no caching, ~2 s tolerance); fires with reason "events written since the index build (uncommitted or unsynced writes move no git HEAD)" — the reason text flows into the `W-IDX-STALE` message (CLI + MCP `search`), `masora facts` keeps the bare `stale_warning` boolean (no contract shape change); a rebuild makes the index fresh again. Tests: `test_uncommitted_write_fires_freshness_axis`, `test_freshness_tolerance_respected`, `test_freshness_axis_ignores_non_event_files_but_walks_deleted_toml` (test_index.py), `test_facts_stale_warning_true_after_uncommitted_note` (test_facts.py), `test_search_freshness_axis_catches_uncommitted_note` (test_mcp.py).
- [ ] `masora init` — base bootstrap command (git init + `base.toml` scaffold + first commit): today the first base is hand-made inside the shared repo; friction observed during the first rollout. → new `masora/init.py` + CLI + tests + docs.
- [ ] First rollout: create the base on the author's `employees/` dir + Confluence install page (install, `masora setup --base <url>`, usage); migration to a dedicated repo if adopted.
- [ ] Agent-graded evaluation of the phase objective — define the protocol first (task list, rubric for "repeated wrong deduction", metrics), then: seed the base with the claims and refutations produced while building it, run ~20 routine tasks with and without Masora; success = fewer repeated wrong deductions and fewer tool calls or tokens per task; plus injected-token accounting.

Clarifications to settle as each task starts (final audit 2026-09-25):

- `check` append-only baseline: diff against `origin/main` by file content; distinguish a `gc` whole-lineage deletion from tampering; tolerate dangling events across PRs (index warns and ignores).
- Index location and scope: one index per base × code repo; rebuild triggers (write, pull, HEAD change, cppgraph reindex); full rebuild (disposable).
- Contract for cppgraph reading the index: path discovery, schema version, concurrent readers, which checkout the statuses were computed for.
- Neighbour-snapshot cap for hub symbols (deterministic truncation + `truncated` flag).
- Credential-shaped content: detector (gitleaks-style patterns + entropy), scanned fields, reject-with-error at `note`.
- YAML details: monotonic ULID generation; `unanchored` reason field name (distinct from `reason`); `ambiguous` outcome at `note` returns candidates and writes nothing.
- MCP transport (stdio) and the envelope JSON shape (cap + omitted-count fields).
- Envelopes always show `source` (+ `name`/`effort` when present — FORMAT.md unified provenance; solo-base loophole: nothing prevents self-verifying Stop-hook extractions; review is the trust path).
- `cost_tokens` is passed by the agent when it knows it (skill guidance); the tool never invents it.

Out of scope:

- Non-code anchor providers (`file`, `url`).
- Advanced MCP tools: `unrefute`, `recheck`, `history`, `explain` (evidence-chain trace for an injected fact).
- CI pipeline wiring (publication is PR-based; `masora check` runs locally in `sync`).
- Duplicate-lineage handling (`same-as`).

### Phase 2 — beyond cppgraph

Deferred — a spec seed recorded on 2026-09-29; reopen when non-code knowledge
is wanted, without cppgraph.

- [ ] Agent hooks (an injection channel without cppgraph):
  - `SessionStart`: background pull of the base with silent failure, plus a summary of stale lineages;
  - `UserPromptSubmit`: FTS over the prompt, injection of 2-3 claims;
  - strict caps (summary ≈ 100 tokens, 2-3 claims per prompt);
  - FTS thresholds (minimum prompt length, minimum score — search is lexical, false positives are a risk);
  - injected-token accounting in the evaluation protocol;
  - purpose = non-code knowledge, without cppgraph.

<!-- Block template to duplicate per phase:

### Phase N: <name>

Objective:

Tasks:
- [ ] ...

Out of scope:

-->
