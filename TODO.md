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

- [ ] Pre-flight: check name availability — `pip index versions masora`, GitHub, npm (§3).
- [ ] `masora setup --base <url>`: writes `~/.config/masora/config.toml` from the base's own `base.toml` (+ first-run init).
- [ ] Claim/verify/doubt/undoubt/refute/unrefute `.md` format + layout of §7 (month-bucketed lineage dirs).
- [x] Decide the frontmatter schema (Q5) — settled 2026-09-25, see MASORA_DESIGN.md §12.5 (mandatory `summary:`, explicit `unanchored:`, neighbour snapshot, `.verify` events).
- [ ] `masora check`: validates event schema and append-only history (local command; run by `sync`).
- [ ] `masora sync`: runs `masora check`, batches local events into one branch + PR to the shared base.
- [ ] `masora gc`: deletes whole lineages on explicit, confirmed request (`--lineage`); no auto-suggestions in v1.
- [ ] SQLite index + resolution algorithm of §6.2 + FTS.
- [ ] MCP tools: `note`, `verify`, `doubt`, `undoubt`, `refute`, `search`, `list_stale`.
- [ ] Write path rejects credential-shaped content.
- [ ] Code anchor provider via cppgraph with per-symbol definition fingerprint.
- [ ] Edge-set fingerprint per symbol (hash of outgoing edges) — input to the settled `suspect` rule (§12.4).
- [ ] Neighbour snapshot (anchors' edge-set hashes + direct-neighbour identity → edge-set hash) recorded at write time and in `.verify` events — baseline for `suspect` comparison.
- [ ] Injection of known facts into cppgraph responses (requires changes in the separate cppgraph repo).
- [ ] Fallback without cppgraph: exercise the base via CLI/MCP `search` by symbol.
- [ ] Injections emitted as evidence envelopes (validity, anchor, provenance).
- [ ] `SessionStart` hook: pull + stale summary.
- [ ] Skill / AGENTS.md instructions: search-before-investigating, when to `note`, capture triggers from §10.3.
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
- Envelopes always show `actor`/`source` (solo-base loophole: nothing prevents self-verifying Stop-hook extractions; review is the trust path).
- `cost_tokens` is passed by the agent when it knows it (skill guidance); the tool never invents it.

Out of scope:

- Non-code anchor providers (`file`, `url`).
- Advanced MCP tools: `unrefute`, `recheck`, `history`, `explain` (evidence-chain trace for an injected fact).
- CI pipeline wiring (publication is PR-based; `masora check` runs locally in `sync`).
- Duplicate-lineage handling (`same-as`).

<!-- Block template to duplicate per phase:

### Phase N: <name>

Objective:

Tasks:
- [ ] ...

Out of scope:

-->
