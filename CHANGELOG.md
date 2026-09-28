# Changelog

<!-- Keep a Changelog format (https://keepachangelog.com): one entry per
      version / completed phase, newest first. An entry is added when a
      task/phase is done, never before. -->

## [Unreleased]

### Added

- Settled the open questions Q1–Q5 and Q7 of MASORA_DESIGN.md §12 with the design owner: v1 covers structural and semantic claims (semantic = auto-doubt only); the LLM may verify any claim backed by recorded evidence (replayed proof query or pointers to the proving code + explanation), humans override via refutation and PR review; anchors are symbols only, multiple per claim; `suspect` fires on a 1-hop edge-set change against a persisted neighbour snapshot; the provider interface fixes outcome semantics (`resolved`/`not_found`/`unavailable`/`ambiguous`) and digest-based `url` validity. Q6 and Q8 stay postponed.
- Verification is now a `.verify` event (fourth event kind) instead of a claim frontmatter field: no `.md` file is ever modified after creation, promotion and re-verification append files, and a version's fingerprint set is immutable.
- SPEC.md updated accordingly (event kinds, verification authorship, symbol-only multi-anchor rule + neighbour snapshot, `suspect`/`unknown` statuses, provider outcome semantics, edge/subgraph anchors out of scope).
- User-journey review with the design owner: added `.doubt`/`.undoubt` events (human disagreement with a verified version = doubt, not refutation); layout relaxed to convention-only (content-based validation, moving files changes nothing); one shared base per team as the default story (multi-base kept as config capability); publication via one branch + one PR with local `masora check`, no CI in v1; `masora gc` for cleanup; install UX aligned with cppgraph (`setup.sh`); mapping-fallback rule for projects with no matching remote.
- Onboarding gap closed: a base declares itself via `base.toml` (name + served code remotes) at its repo root; `masora setup --base <url>` writes the local config from it in one command — the base URL travels through the team's onboarding docs, nothing lives in the code repo.
- Rollout decided: the first base lives on the author's `employees/` dir, install explained on a Confluence page, migration to a dedicated repo proposed if adopted.
- Provenance du modèle : champ optionnel `model` (chaîne libre, ex. `glm-5p3-flash`) sur les claims et les `.verify` quand l'auteur est un LLM — `cost_tokens` se lit contre lui (48k de GPT-6-astra ≠ 48k de DeepSeek-4.1-flash) ; le modèle de vérification peut différer du modèle d'écriture.
- Source version on claims: `recorded_at {commit, graph_commit}` added to the claim schema (the write-time commit was stated in §10.2 but absent from the field list); commits qualify, fingerprints still decide.
- Same-type schema holes found in a systematic sweep and fixed: anchors carry their write-time edge-set hash (`edges`) — required by the `suspect` rule but previously homeless; `unanchored` claims get an explicit resolution rule (no fingerprint resolution, always surfaced, flag as validity signal); §7 example and §5.1 aligned with the immutable-fingerprint `.verify` model; `cost_tokens` is agent-provided, never invented by the tool.
- FORMAT.md, the canonical event-file contract, frozen after a full audit chain (cheap-review consistency → design-review REWORK → strong-review systemic audit → cross-vendor strong-review-alternative → two verification passes, final 0 MAJOR): six block-style templates, per-kind required/optional/forbidden table, YAML canonicalization, monotonic Crockford ULIDs with clock-free cycle rejection, per-anchor provider-neutral snapshots (code: edge set + per-anchor neighbours), active-event folding as a backward descending-ULID fixed point, `deleted.toml` tombstones, standalone-check vs sync baseline rules.
- `masora check` MVP implemented against the frozen contract: standalone whole-tree validation (schema per kind, canonicalization, cross-file references, cycle rejection, founder resolution, tombstones) + §6 fold producing per-claim status envelopes; the fold rule is proven by an executable spec — brute force over all 13,512 event-graph DAGs at n≤4 against an independent topological oracle (order-independence across 4 evaluation orders) plus 10,000 sampled 5-event DAGs; 190 tests green. Review pipeline (1 MAJOR neighbour-hash quoting + 6 MINOR) applied and verified. The executable spec fed a contract correction back into FORMAT.md §6 (convergence scoped to the acyclic domain).
- Final audit (strong-review, verdict NO-GO then GO-with-reservations once fixed) applied to the docs: `.refute`/`.doubt` may target any event ULID (a refuted `.verify` is ignored when folding); computed status defined as a tuple (resolution × verification × flags) replacing three divergent status lists; negative-knowledge envelope (`NOT: <summary> — refuted: <reason>`) added, resolving the injection contradiction; replay re-timed to verify/check (never reindex), all `--ci` mentions removed; proof-query format fixed (`{tool, args, expect, provider_version}`, set equality, tool whitelist); fingerprint contract specified (normalized definition text, sorted callee SCIP strings of `calls` edges, graph commit recorded, refuse writes from a stale graph); `setup --base <url>#<path>` supports sub-directory bases; pending-event lifecycle defined (`masora/pending` branch, one PR updated, squash-safe, `sync --drop`); doubt uses `source` (not actor); ULID chosen over UUIDv7; `gc` manual-only in v1; MCP/CLI tool surfaces harmonized.

<!-- Entry template to copy:

## [X.Y.Z] - YYYY-MM-DD

### Added

### Changed

### Fixed

-->
