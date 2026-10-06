# hook.py — the agent hooks (SessionStart freshness + UserPromptSubmit recall)

Role: `masora hook install [--target {claude,opencode}]` plus two hooks'
background work — `session_start()` (the §10.1 freshness automation that
exists for AUDIT.md operational risk 1, "silent recall decay") and
`user_prompt_submit()` (Phase 2's primary recall channel: prompt-time FTS
injection, §10.1 channel 2).

## Install (the skill-install pattern)

- The hook scripts ship in the package (`masora/hooks/session_start.py` +
  `masora/hooks/user_prompt_submit.py`, one canonical copy each) and are
  written VERBATIM into every detected agent home — the shipped ==
  installed invariant is tested, like the skill's.
- Claude Code: BOTH entries (SessionStart + UserPromptSubmit) are MERGED
  into `~/.claude/settings.json` (idempotent — an entry whose command names
  our script is never duplicated, and a PRIOR masora entry in an old shape
  is replaced, never left to shadow the fresh one; foreign keys preserved;
  an unreadable file degrades to the printed manual snippet, never a broken
  settings file).
- The registration command pins the INTERPRETER install ran under
  (`_hook_command` → sys.executable): a bare `python3` may lack the masora
  package entirely or hold a stale copy, and the hook would then silently
  never run — the one failure mode silent-failure discipline cannot
  surface. The shipped scripts additionally re-exec once into a
  masora-capable interpreter (the `masora` CLI's shebang, then the uv tool
  env) when the registered one cannot import the package.
- opencode: its hook surface is a JavaScript plugin file, not a JSON
  setting — the SessionStart script is installed but the registration is
  PRINTED as the manual snippet; writing a .js plugin from here would guess
  at a format. (The prompt hook is claude-native; opencode recall stays on
  the skill's search ritual.)
- `--target` unknown is a clean refusal; re-running install IS the update
  path (overwrite, `installed:`/`updated:` lines).

## The hook's work (session_start) — silent by contract

1. Per configured base (`[bases.*]` from the user config): fetch + `merge
   --ff-only` — NEVER force, NEVER rebase; any failure (diverged clone,
   network, dirty tree) skips the base SILENTLY; `masora doctor` is the
   surface that reports clone health.
2. Per (base, repo) index job (repos from the stored index metas, the same
   source doctor uses): the four-axis `index_stale_reason` decides a
   rebuild, bounded by `REBUILD_BUDGET_S` — a hard wall-clock budget, one of
   the named §10.1 caps (the constants carry the §10.1 pointer).
3. Output: AT MOST two lines — the stale summary `masora: <n> stale
   lineage(s), worst reason: <class>` (only when something is stale) plus
   the standing usage rule (`SESSION_USAGE_LINE`, the AGENT_INSTRUCTIONS.md
   "search before investigating" ritual) whenever any base is configured —
   the one line the prompt hook deliberately never nags with. Nothing
   configured (no/garbage config) prints NOTHING. The count is read AFTER
   the (optional) rebuild; the worst reason class ranks the four staleness
   axes graph > code HEAD > base HEAD > uncommitted writes.

## Invariants

- SILENT FAILURE: `session_start()` never raises, always exits 0, every
  per-base/per-index exception swallowed; even the final print is guarded.
- The hook runs in the background at session start: it must never block a
  session, never prompt (all spawns through `sync.run_git`/`git_env` with
  timeouts), never print more than two lines (the summary + the usage rule).
- The hook NEVER mutates git history: fetch + ff-only merge only — a
  diverged clone waits for a human (or `masora doctor`'s remedies).

## The prompt-time recall hook (user_prompt_submit)

At every user prompt, the hook gives the agent the 2-3 most relevant claims
BEFORE it chooses any tool — the recall fix the pre-registered evaluation
pointed at (the other channels barely engaged: agents never called the MCP
tools unprompted, and the cppgraph injection fired only when the graph was
consulted).

- Resolution: base from the prompt's cwd via `auto_base` (mappings on
  origin, then `default_base`; nothing = silent skip); the EXISTING index
  is opened read-only — missing or stale is a SILENT SKIP, never a
  synchronous rebuild (the SessionStart hook owns rebuilds; a rebuild here
  would cost the prompt its budget).
- Search: the prompt becomes an ANY-term query over the
  content/questions/keywords union (`_prompt_query` reuses the safe
  builder's tokenizer + term cap) — a long natural-language prompt under
  AND semantics would match nothing; precision is recovered by the bm25
  floor plus the top-3 cut, not by AND.
- Thresholds (named constants, §10.1 comments): `PROMPT_MIN_CHARS` (25) +
  `PROMPT_MIN_WORDS` (4) skip commands and pleasantries; `PROMPT_RANK_FLOOR`
  (-0.5) drops stopword-grade matches — bm25 magnitudes are corpus-
  dependent (a two-claim corpus ranks ≈ -1e-5), so the floor presumes a
  real base's idf mass; the tests seed filler lineages to emulate it.
- Selection: at most `PROMPT_MAX_CLAIMS` (3) lines, dedup by lineage,
  better status first (current/restored > stale > none), best rank within
  a status; the `PROMPT_TOKEN_BUDGET` (100) envelope wins over the count
  but at least one claim renders whenever any matched.
- Rendering: the block is prefixed by the one-line usage rule
  (`PROMPT_USAGE_LINE` — the WITH-condition instruction, docs/EVALUATION.md
  amendment 2026-10-04); claim lines render statuses as LABELS per the §6
  trust matrix — `masora: <summary> [status, verification, flags…]`, a
  refuted lineage as the negative-knowledge `masora NOT: <summary>
  [refuted]`, `unverified` rendered silently (its absence is not evidence).
  Nothing matched → NOTHING prints, usage line included: the standing
  instruction belongs to the SessionStart summary, not to every prompt.
- Delivery (eval 2026-10-03 post-mortem): the channel is STDOUT ON EXIT 0,
  and it is reliable — the injected text lands in the UserPromptSubmit
  `hook_response` and reaches the model, interactive or not. The eval's
  "claims missing from the transcript" symptom was TRANSCRIPT VISIBILITY,
  not delivery: claude 2.1.274's `-p --output-format stream-json` omits the
  prompt-turn user message and the UserPromptSubmit hook lifecycle events
  unless `--include-hook-events` is passed — the batch runner carries that
  flag now (probe evidence: the claims appear in the hook_response under the
  exact runner invocation shape, with or without it they reach the model).
- Budget: `PROMPT_BUDGET_S` (2.0) on the whole hook — exceeded means print
  nothing.
- Per-session dedup: with a `session_id` from the payload, the hint goes
  out on the session's FIRST prompt and again only when its CONTENT
  changed (a background pull brought fresh drift); an identical hint on a
  later turn prints nothing. The search itself stays per-prompt — only the
  INJECTION is deduped.
- Invariants: SILENT FAILURE (any exception → nothing printed, exit 0),
  READ-ONLY (no index build, no event files — like `masora facts`; the one
  sanctioned write is the dedup state below), FAIL-OPEN DEDUP (any error
  around the dedup state — missing dir, corrupt/unreadable file, unwritable
  path — degrades to INJECTING, never to silence and never to a crash).

### The dedup state file

- What: `sha256` of the exact hint string last injected for that session
  (hint = usage line + claim lines), one line of text.
- Where: `<masora state dir>/hook-state/<sha256(session_id)>.hint` — the
  session_id is hashed into a flat filename (it can carry arbitrary
  characters); the root follows the config.py per-artifact resolution
  (`MASORA_HOME`/`config.masora_home()` when set, else
  `~/.local/share/masora/hook-state/`); tests override it with the
  `state_dir` parameter.
- Fail-open: a missing or corrupt file reads as "never injected" → inject;
  a failed write is swallowed and the hint still goes out. The dedup can
  only ever SUPPRESS a redundant repeat, never an injection that matters.
- NO cleanup of stale session state files (dead sessions' hashes stay on
  disk): state files are ~70 bytes and sessions are finite, so the leak is
  bounded and noise-level; a cleanup pass would add surface for deleting
  under the user's home for no recall benefit. No GC, no TTL, no rotation.
- Deferral (recorded per review): `_hint_state_path` resolves the masora
  state root locally rather than through a shared config.py helper because
  config.py exposes only `masora_home()` plus per-artifact resolvers (each
  doing its own home fallback) — there is no reusable root helper to route
  through; refactoring config.py for this was ruled out.
