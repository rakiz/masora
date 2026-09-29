# Masora — design brief (bootstrap document)

Status: **contract frozen (FORMAT.md); Phase 1 core implemented — check, sync, setup, gc, index/search, MCP server, facts, unified provenance (remaining tasks in TODO.md).** This document
captures every decision made so far, the reasoning behind it, the open questions,
and the prior art to study before writing the schema. It is meant to bootstrap an
agent that will build Masora. Where something is marked *open*, do not decide it
silently — raise it.

---

## 1. The problem

AI coding agents are "very smart with Alzheimer's":

- They spend many tokens (grep/find/read) to understand something, then forget it
  at the end of the session.
- When they can't find the answer they infer one; it's often *almost* right but
  wrong in the details.
- When the human corrects them, the correction is lost next session, and the same
  wrong deduction is re-invented.
- cppgraph (github.com/rakiz/cppgraph) fixed the *structural* part for C++ (exact
  call graph, references, hierarchy, impact from a SCIP compiler index). What is
  still missing are the **indirect / semantic dependencies the compiler can't see**:
  "X depends on Y through this config flag", "lock L must be held before calling
  f", "this value is serialized here and read back in another process there".

**Goal:** a knowledge base the human and the agent build together over time, where
each piece of knowledge is anchored to what it talks about, carries its
provenance and proof, and **knows by itself when it may no longer be true**.

## 2. Identity and guard-rail

Masora is **not** a scratchpad memory (like Serena's `write_memory`/`read_memory`,
which are free-text sticky notes with no provenance, no link to code, no
staleness detection). It is a base of **claims anchored to things, with a
verification lifecycle and self-invalidation**.

Guard-rail (non-negotiable): **no claim without anchor + provenance + (proof or an
explicitly assumed `unverified` status).** Unanchored claims are allowed only when
explicitly declared `unanchored`. The day we store unanchored free text "so we
don't lose the info", we have built Serena with more tables.

Verification is the core, not storage. Recalled knowledge is presented to the
agent as **evidence with a status, never as an instruction**.

## 3. Name

**Masora.** The Masoretes were scribes — not priests proper — who transmitted
the Hebrew Bible text (roughly 7th–10th c.); *massora* denotes the tradition they
handed down. Their problem is ours: keep a text exact across centuries of copies
made by people who err. Their method is our design:

- **Notes anchored in the margin**: the *Masora parva* (side margins, abbreviated)
  and *Masora magna* (top/bottom margins) are knowledge attached to a precise word.
- **Checksums before their time**: they counted letters and words, recorded the
  middle letter/word of each book, the number of occurrences of rare forms. A copy
  that didn't match was wrong → our fingerprints.
- **Never edit the text**: when a word should be read differently, they wrote it
  in the margin and left the text untouched → code is never touched; knowledge is
  append-only beside it.

The name itself: six letters, pronounced the same in every language.

TODO before committing to the name: `pip index versions masora`, check GitHub and
npm. (Web search found no AI/knowledge project named Masora; only unrelated repos.)

## 4. Packaging

- **Separate project** from cppgraph, open source like it. Reason: the knowledge
  layer is useful beyond code (docs, specs, design notes).
- Masora only knows an abstract notion of **anchor**, provided by **anchor
  provider plugins**:
  - `code` → cppgraph (SCIP symbol, fingerprint of definition, replayable graph
    queries). SCIP strings exist for other languages too (scip-python,
    scip-typescript, …) so the code provider is not C++-only in principle.
  - `file` → path + section + content hash (docs, specs, notes).
  - `url` → URL + content hash.
- cppgraph **optionally** integrates: if Masora is installed, cppgraph implements
  the anchor-provider interface and **injects known facts into its tool responses**
  (see §9). If not, nothing changes.
- Each project has its own README/install doc. cppgraph's `setup.sh` may offer
  "also install Masora?" and point to its doc. Install doc follows the cppgraph
  style: "tell your agent: follow instructions to install <repo>".

## 5. Data model

### 5.1 The claim

A claim is a statement plus:

- **anchors**: one or more stable identities (SCIP symbol string for code — **never**
  an interned DB row id, which changes on every rebuild); single symbols only,
  multiple anchors per claim — no edge/subgraph anchor types (§12 item 3);
- **source** (axis 1): `human` | `llm` | `graph` — unified on **every** event
  kind, including `.verify` (§12.10); declarative, writer-asserted;
- **name** (optional): free string self-signed by the writer — the git
  `user.name` when `human`, the model name when `llm`, empty/absent for
  `graph` today (a later deriving tool may sign e.g. `cppgraph@0.4`);
- **effort** (optional, llm only): `low` | `medium` | `high` — the declared
  strength of the writing analysis, calibrating doubt-escalation (§12.10);
- **verification** (axis 2): `unverified` | `verified` — recorded as `.verify`
  events like refutations (§6.4, §12 item 5), never a frontmatter field on the
  claim: no `.md` file is ever modified after creation. *Stale is never stored*
  (§6.2);
- **verified_at**: the code commit (+ graph commit) at the moment of
  verification; the fingerprints attested are the claim's immutable set
  (§12 item 5) — they are not repeated on the event;
- **evidence**: links that prove the verification (graph queries, file ranges,
  tests, URLs);
- **cost_tokens**: how much it cost to establish (tells how expensive a re-check
  will be) — read against the writer's **name** (48k tokens are not the same
  cost depending on the model); the agent passes both when it knows them, the
  tool never invents them. `cost_tokens` is economics only; `effort` is the
  trust dial (§12.10).
- **contradicts / reason**: if it replaces or disagrees with an earlier version,
  it must say what is wrong with it and why (enables later arbitration);
- a **lineage id** (§6.1).

The two axes are orthogonal on purpose: "added by LLM **and** verified in code"
must be expressible, and "all unverified claims an LLM added" must be queryable.

### 5.2 Two classes of claims

- **Structural** ("A calls B", "X inherits Y", "F is the only caller of Z", and
  especially negatives: "there is no path from A to B"). Stored as **a replayable
  query + expected result**. Storing "A calls B" alone is worthless (the graph
  knows it); the value is in costly-to-find facts. Replay happens when a
  verification is recorded or re-checked (`verify` / `recheck`), never in bulk at
  reindex — a query that no longer replays invalidates the *verification*, not
  silently the claim. **Auto-verifiable** (proof replay) and **auto-invalidatable**
  (fingerprint mismatch → stale).

  Proof query format (v0): `{tool, args, expect, provider_version}` — `tool` from
  a whitelist of read-only cppgraph tools, `expect` the normalized expected
  result; replay succeeds iff the result set-equals `expect` over symbol strings.
- **Semantic / behavioural** ("lock must be held", "hot path", indirect
  dependencies). **Not verifiable from a static graph.** Proof is manual (human,
  test, link). They can only **auto-doubt** (become stale/suspect when anchors
  change), never auto-confirm. These are the ones that solve the original problem.

### 5.3 Negative knowledge

Refuted claims are kept and surfaced: "NO, X does not reach Y indirectly, because
…" is probably the most valuable entry type — it stops the agent from re-inventing
the same wrong deduction. Surfacing channel: on anchor match, a lineage with no
current version — or whose newest version is refuted — injects a distinct
**negative envelope**: "NOT: <summary> — refuted: <reason>".

### 5.4 Fingerprints

- **Per symbol, not per file.** File-level fingerprints (`meta.dirty_fingerprints`
  in cppgraph is a starting point) are too coarse: any edit in a big .cpp would
  stale every claim anchored in it, and noise kills trust in the signal.
- Definition fingerprint = hash of the symbol's definition range **source text,
  whitespace/comment-normalized** (a reformat must not stale claims).
- Edge-set fingerprint = hash of the **sorted callee SCIP strings from `calls`
  edges only** (used for `suspect`).
- Fingerprints always come from cppgraph's **indexed commit** (recorded beside
  `verified_at.commit`); `note`/`verify` refuse to write fingerprints when the
  graph is behind HEAD (re-index first).

## 6. Versioning and validity

### 6.1 Principles

- **The knowledge repo is separate from the code repo** and is **always read at
  its latest state**. Do *not* tie knowledge git history to code git history.
  (If knowledge lived in the code repo, checking out an old commit would bring back
  old *errors* too.)
- **Append-only.** Nothing is ever rewritten; new versions and events are added.
- Each piece of knowledge has a **lineage**; each version has a **ULID**:
  generated without coordination, time-sortable. The ULID *is* the
  ordering — no separate timestamp field that could contradict it (a human-readable
  created_at may be derived for display).
- **Fingerprints, not timestamps, decide applicability to code.** Timestamps only
  order knowledge versions among themselves. (Comparing knowledge dates to code
  commit dates is wrong: branches, rebases, cherry-picks.)

### 6.2 Resolution algorithm (at index time)

For each lineage:

1. sort versions by ULID, newest first;
2. skip versions that are refuted (and not un-refuted);
3. the first version whose anchor fingerprints match the current checkout →
   **current**;
4. if none match → show the newest as **stale** ("changed since verification").

Properties:

- a colleague on old code automatically gets the old version that matches their
  code, **and** gets error corrections (refutations apply everywhere);
- a code revert makes the matching fingerprint valid again → the old claim comes
  back by itself;
- if two versions match the same fingerprint, the newest wins (written with more
  understanding).

**Computed status lives only in the SQLite index, never in the .md files.** The
next indexer does the same computation; files are never touched for status.

**Computed status is a tuple**, rendered in every envelope:

- `resolution`: `current` (first version matching — **all** anchors must resolve
  and match fingerprints) | `stale` (no version matches; the newest is shown) |
  `restored` (current because a newer version of the lineage was refuted) |
  `none` (every version of the lineage is refuted);
- `verification`: `verified(<source>)` | `unverified` — folded from `.verify`
  events;
- flags: `suspect` (§12 item 4), `doubted` (iff some active doubt targets an
  active verify of the displayed version), `pending` (events not yet merged —
  §8), `unknown` (an anchor provider was `unavailable`; shadows the resolution
  instead of guessing). An anchor that is `not_found` simply fails to match.
- Status precedence is `none` > `unknown` (shadowing) > `current`/`restored` >
  `stale`; `restored` applies only when the chosen version is older than some
  refuted version. Event folding follows FORMAT.md's active-event rule (which
  verifies, refutes, doubts and undoubts are active); activity is evaluated
  backwards in descending ULID order to a fixed point before folding, and
  resolution requires the founding claim — a v2+ version whose founder
  (`id == lineage`) is absent is excluded.
- A later `.verify` never clears a doubt; only `.undoubt` does.
- An explicitly `unanchored` claim has no fingerprint resolution: it is always
  surfaced, and its `unanchored` flag is the validity signal (the §2 guard-rail
  makes it rare and loud).

Optional later qualification of a mismatch using `git merge-base --is-ancestor`
between verified_at.commit and HEAD: `stale` (verified commit is an ancestor),
`ahead` (HEAD is an ancestor — not yet true on this code), `divergent` (other
branch). Fingerprint stays the judge; git only qualifies. Falls back to plain
current/not-current if the commit is unavailable (shallow clone).

### 6.3 Two kinds of "correction"

- **The claim was always wrong** (agent hallucinated) → **refute** the wrong
  version. Refutation is a fact about the claim, independent of code version.
- **The code changed** → **new version** in the same lineage with new
  fingerprints; the old version stays valid for its fingerprints.

Deciding which is a judgment. Tool guidance: if the anchor fingerprint has not
changed since verification, the code didn't change → it must be a refute. If it
changed, **ask explicitly** rather than guess. A new version alone does not fix an
old error on older code (v1 at F1 wrong, code now F2 → a v3 carries F2; users on
F1 would still see v1) → refute is required for that case.

### 6.4 Refutations are events, reversible, justified

- A refutation is **its own file** referencing the refuted version's ULID, with a
  reason, author, and evidence. An **un-refute** is another file. Result: no
  existing file is ever modified → no merge conflicts, full history (event
  sourcing; the index folds the events).
- A refutation can itself be wrong; lifting it makes the version a candidate again.
- If refuting v3 makes v2 resurface as current, flag v2 **"restored — re-verify"**
  instead of silently presenting it as trusted: we know v3 is wrong, not that v2 is
  right.
- Keeping all versions enables "re-check what we believed before, in case the new
  belief isn't better": `history(lineage)` + "re-verify v2 against current code"
  (re-do v2's reasoning with its evidence instead of starting from scratch).

## 7. Storage layout

```
knowledge/
  2026-09/                                   # month of lineage creation
    01J8Z3K…-resume-token-shard-key/         # lineage dir: <ulid>-<slug>
      01J8Z3K….claim.md                      # v1
      01J8Z3K….verify.md                     # verifies v1 (targets its ULID)
      01JA4QX….claim.md                      # v2 after code change
      01JB7RM….refute.md                     # refutes v1 (targets its ULID)
    01J8ZP2…-lock-before-commit/
      01J8ZP2….claim.md
```

- One directory per lineage; its history is its file listing.
- Slug is cosmetic, fixed at creation, never an identity, never renamed.
- Suffix gives the event kind: `.claim`, `.verify`, `.doubt`, `.undoubt`,
  `.refute`, `.unrefute` (later `.same-as`). Verification is an event (§12 item 5):
  promoting or re-verifying appends a file, nothing is ever edited in place.
- Month bucket avoids tens of thousands of entries per dir while staying readable.
- **Layout is convention, not law**: `masora check` validates content (unique
  ULIDs, resolvable references), never file locations; the index parses the whole
  tree, so moving files changes nothing. New files are written month-bucketed by
  convention (collision avoidance), nothing more.
- **Never organise by symbol/module**: claims have several anchors (indirect
  dependencies have ≥2), code gets reorganised. Lookup by symbol is the SQLite
  index's job; the tree only prevents collisions.

Example claim frontmatter (schema settled — §12 item 5):

```yaml
format_version: 1
id: "01JA4QX…"               # version ULID
lineage: "01J8Z3K…"
kind: claim
class: semantic              # structural | semantic
source: llm                  # human | llm | graph
name: "glm-5p3-flash"        # optional: git user.name when human, model name when llm
effort: high                 # optional, llm only: low | medium | high
summary: "Resume token invalidated by a shard key change"   # mandatory one-liner, used verbatim in injections
statement: "The resume token of a change stream is invalidated if the shard key changes, via …"
anchors:                     # >=1, unless unanchored
  - provider: code
    identity: "scip-clang cxx . . mongo/ResumeTokenData#makeResumeToken()."
    fingerprint: "7b21…"     # definition fingerprint at write time
    snapshot:                # provider-typed; for code:
      edges: "3f9d…"         # edge-set hash of this symbol
      neighbours:            # per-anchor suspect snapshot (identity → edge-set hash)
        "scip-clang cxx . . mongo/ShardKeyPattern#extract(key).": "9c04…"
recorded_at: { commit: abc123, graph_commit: 7e8f90 }   # source version at write time; fingerprints judge, commits qualify
unanchored: false            # explicit; true only with a reason (§2 guard-rail)
proof_query: null            # for structural claims: replayable query + expected result
contradicts: "01J8Z3K…"      # optional, with reason
reason: "v1 assumed … but …"
cost_tokens: 48000
# no `verification` / `verified_at` here: they live on `.verify` events, e.g.
#   .verify: { format_version: 1, id, lineage, kind: verify, targets: "01JA4QX…", source: llm,
#              verified_at: { commit: def456, graph_commit: 9a01bb }, evidence: […], snapshots: { … } }
```

**Index:** a SQLite DB rebuilt from the .md files (FTS5 for text search;
embeddings later if ever). Like cppgraph's graph.db, it is **disposable**; only the
.md in git are precious. Both SQLite DBs can be rebuilt; git is the single durable
store.

Known future problem: two people independently create two lineages for the same
knowledge. The index can flag lineages sharing anchors with similar statements; a
`same-as` event file merges them. Postpone.

## 8. Publication workflow (git)

- The agent writes .md **locally**, indexed immediately → usable from the next
  session, no waiting.
- Publication is a separate `sync` step that batches a session's work into
  **one branch and one PR** (never one PR per note, or nobody writes anything).
  `sync` runs `masora check` locally before opening the PR; the review notifies
  the author. Direct push stays available for a solo base.
- **Lifecycle of local, unpublished events**: they are commits on a local branch
  `masora/pending`, rebased onto `origin/main`; envelopes tag them `pending`.
  `sync` pushes that branch and opens **or updates** the single PR (forge CLI if
  available, otherwise prints the compare URL). Squash-merges are harmless:
  events are compared by file content. Events whose PR was rejected are
  discarded explicitly with `masora sync --drop`.
- **No CI in v1.** `masora check` is a local command, not a pipeline. A verified
  claim's strength is its recorded evidence (proof query replayed at verify
  time; code pointers + explanation), reviewable in the PR. CI wiring (schema
  validation, anchor resolution at the recorded commit, replay of proof queries)
  is deferred until adoption makes validation a real problem; the intent stays:
  everything provable passes automatically, human review is only for what no
  machine can decide.

## 9. Installation, configuration, retrieval of bases

- Config is user-side, **nothing in the code repo** (you can't commit to an
  upstream anyway): `~/.config/masora/config.toml`.

```toml
# Hosts below are fictional examples: a base is any git URL, hosted wherever
# its community wants (GitHub org, self-hosted GitLab, …).
[bases.perso]
remote = "git@github.internal:org/employees.git"
path   = "rakiz/knowledge"        # sub-directory
branch = "main"

[bases.team-query]
remote = "git@github.internal:org/query-knowledge.git"

# which bases for which project, matched on the code repo's git remote
[[mappings]]
code_remote = "github.com/mongodb/mongo"
bases = ["team-query", "perso"]   # read together; write to the first by default
```

- An environment variable can override for special cases.
- **The base documents itself** (`base.toml` at the **base directory's** root:
  display name + `code_remote = [...]` remotes it serves; README with the
  ready-to-copy config block). A new contributor runs
  `masora setup --base <url>[#<path>]` — sparse-clone (at `path` for a base
  living in a sub-directory of a shared repo), read `base.toml`, write the local
  `config.toml` (base + mappings) in one step. Where does the URL come from?
  The team's onboarding doc or a colleague — handing over access is the one
  human step, the rest is tooling. Nothing ever goes into the code repo: on
  upstream repos (mongodb/mongo…) nobody has commit rights there anyway.
  Code remotes are compared after normalization (lowercase host, no scheme,
  no trailing `.git`).
- **Masora hosts nothing.** A base is an ordinary git repo owned by its community
  (company GitLab, a GitHub org, …); the tool only clones and indexes them —
  nobody's knowledge ever lands in the Masora project itself. The default story
  is **one shared base per team** that everyone reads and enriches; the
  multi-base config above stays as a capability for later.
- **A project that matches no mapping** (no git remote, unknown remote) gets no
  injection, and `note` refuses to guess: it asks for an explicit base, or uses
  a configured `default_base` if present.
- Install UX mirrors cppgraph: a `setup.sh` (pip install + MCP registration +
  hooks + first-run config), so the agent instruction stays "follow instructions
  to install masora". Masora itself is pure Python + SQLite — nothing to
  compile; cppgraph's `setup.sh` may offer "also install Masora?" and point to
  its doc.
- Sub-directory retrieval works with partial clone + sparse checkout; Masora does
  it itself into `~/.local/share/masora/bases/<name>` (user never sees it):

```sh
git clone --filter=blob:none --sparse <remote> <dest>
git -C <dest> sparse-checkout set rakiz/knowledge
```

- A personal dir in an `employees/` repo is fine for a personal base; once others
  write, a dedicated repo per team is healthier (permissions, CI, review).
  Multi-base config supports both. Planned rollout: start on the author's
  `employees/` dir, install doc on the team's Confluence (the page hands over
  the base URL — `masora setup --base <url>` does the rest); if adopted,
  migrate the base to a dedicated repo and update the mappings. Caveat: writing
  into a personal dir requires push rights on it — heavy writing moves the
  migration date closer.

## 10. Agent workflow

### 10.1 How the agent finds knowledge (use all three)

1. **Injection in cppgraph responses** (most reliable): `who_calls(X)` also returns
   "2 known facts about X (1 stale)". Anchored, automatic, the agent decides nothing.
2. **Agent hooks**: at session start (Claude Code `SessionStart`), background pull
   + short summary (lineages related to the project, list of stale ones). On each
   prompt (`UserPromptSubmit`), fast FTS on the prompt, inject 2–3 matches. This is
   what makes non-code use work (no cppgraph there). opencode: equivalent plugin
   mechanism.
3. **Skill / AGENTS.md** instructions ("search before investigating") — useful but
   often forgotten; never the only mechanism.

Also: re-compute statuses automatically on git HEAD change (pull, branch switch).

### 10.2 Anchoring and verification

- **Anchoring happens at write time and the tool computes it**: the agent calls
  `note(statement, anchors=["makeResumeToken", "ShardKeyPattern::extract"])`; Masora
  resolves them via the provider (cppgraph → exact SCIP symbols), computes
  fingerprints, records the commit. The agent never handles hashes.
- **Lazy verification**: never re-verify the whole base on reindex. Rule in the
  skill: "if you rely on a `stale` or `unverified` claim for the current task,
  re-verify it first, then record the result." Verification cost is paid only when
  the knowledge is used.
- Settled (§12 item 2): the LLM may write `verified` on any claim it can back with
  recorded evidence — structural: a replayable proof query, replayed successfully
  at verification time; semantic: pointers to the code that proves it (file
  ranges, graph queries, tests, URLs) plus an explanation of why it proves the
  statement. Humans keep the say: any verification is refutable (reversibly), and
  on shared bases verifications travel through PR review (§8). The `.verify`
  event records the actual writer in its `source` (unified provenance, §12.10).

### 10.3 When to save (by value)

1. **The human corrects the agent** ("no, that's wrong") → immediate, source `human`.
2. **The agent validates in code what the human said** → source `human`, `verified`,
   with evidence.
3. **The agent spent a lot to establish something** (N tool calls / tokens since
   the question) → note it.
4. **Before compaction and at session end** (`PreCompact`, `Stop` hooks): "what did
   you learn worth keeping?" → everything from this path is `llm` / `unverified`
   (distrust of automatic extraction).

### 10.4 MCP tool surface (draft)

`note`, `verify`, `doubt`, `undoubt`, `refute`, `unrefute`, `recheck` (re-verify a
version against current code), `history(lineage)`, `search`, `list_stale`. CLI:
`masora check`, `sync`, `gc`, `setup`. Plus the injection path inside cppgraph.

## 11. Integration contract with cppgraph

Anchor-provider interface implemented by cppgraph (sketch):

- `resolve(symbol) → exists? / exact SCIP string`
- `fingerprint(symbol) → {definition_hash, edges_hash, graph_commit}`
- `replay(query) → result` (for structural proofs)

cppgraph reads the Masora index (optional dependency) to attach facts to its
responses. Reuses: stable symbol identity, incremental update path,
`changed_files_since`, per-file fingerprints as a coarse pre-filter before
per-symbol hashing.

## 12. Open questions

Settled 2026-09-25 with the design owner (decisions recorded here, reflected in
SPEC.md). Items 6 and 8 remain postponed.

9. **MCP transport** — *settled 2026-09-29*: a hand-rolled minimal MCP stdio
   server (`masora mcp`), no SDK — the zero-runtime-dependency ethos (pyyaml
   only) outweighs SDK convenience, and the Phase-1 surface is four JSON-RPC
   methods (initialize / notifications/initialized / tools/list / tools/call).
   Protocol version pinned (`2025-06-18`), negotiated the standard MCP way —
   the initialize result always carries it; tool failures
   are `isError` results carrying diagnostic codes, never protocol crashes;
   Phase-1 tools: `note`, `verify`, `doubt`, `undoubt`, `refute`, `search`,
   `list_stale` (`history`/`recheck`/`unrefute` stay out — TODO "out of
   scope").

10. **Unified provenance (`source`/`name`/`effort`) — *settled 2026-09-29 with
   the design owner*:** provenance is **declarative and unified on every
   event kind**: every event carries `source` — `human` | `llm` | `graph`,
   the writer's nature, writer-asserted — plus an OPTIONAL `name`, a free
   string self-signed by the writer: the git `user.name` when `human`
   (human identity is the base repo's git history; the tool reads the name
   from the base repo's git config at write time), the model name when `llm`
   (the verifying session may sign its own, distinct from the claim
   writer's), empty/absent for `graph` today — a later deriving tool may
   sign e.g. `cppgraph@0.4` — and an OPTIONAL `effort` (`low` | `medium` |
   `high`), ONLY meaningful when `source: llm`: the declared strength of the
   writing analysis, calibrating doubt-escalation. `cost_tokens` is
   economics-only (how expensive a re-check is), read against `name`;
   `effort` is the trust dial (how hard the writing analysis claimed to
   look). All of it is **declarative only**: no credential system,
   writer-asserted; git history + PR review remain the trust path. The fold
   keeps the set
   of `source`s of the active verifies and resolution renders
   `verified(<source>)` / `unverified`. `graph` is NOT writable via the MCP
   tools for now (reserved for deriving tools); graph self-signing is
   deferred.

1. **v1 scope** — *settled*: both classes in v1. Semantic claims are the original
   problem (§1); they can only auto-doubt (`stale`/`suspect`), never auto-confirm
   (SPEC non-goal). The structural machinery (proof queries, replayed at verify
   time and by `masora check`) is required by Phase 1 anyway, so supporting
   semantic adds little machinery.
2. **Who writes `verified`** — *settled*: the LLM may verify any claim it can back
   with recorded evidence: structural ⇒ a replayable proof query, replayed
   successfully at verification time; semantic ⇒ pointers to the proving code
   (file ranges, graph queries, tests, URLs) plus an explanation of why it proves
   the statement. Humans keep the say: any verification is refutable (reversibly),
   and on shared bases verifications go through PR review (§8). The `.verify`
   event records the actual writer in its `source` (§12.10's unified
   provenance). (The minni /
    Provena human-credential gate is answered: they gate all promotion because they
    have no machine-checkable proof class; Masora requires recorded evidence
    instead and keeps refutation + review as the human override.) `source`
    and `name` are writer-asserted with no credential system; forgery is
    an accepted risk left to PR review (the trust path).
3. **Anchor granularity** — *settled*: symbols only, multiple anchors per claim
   (an indirect dependency = one claim anchored to ≥2 symbols). No edge/subgraph
   anchor types: structural claims name their edge/subgraph precisely in the
   proof query, and edge sensitivity comes from per-symbol edge-set fingerprints
   (§5.4). Anchors stay opaque `{provider, identity, fingerprint}`, so an edge
   anchor could be added later without schema surgery. Anchoring rule: a claim
   must anchor every symbol whose change could invalidate it.
4. **`suspect` propagation** — *settled*: a claim anchored to X becomes `suspect`
   iff X's edge-set fingerprint changed, or that of any direct neighbour (1 hop,
   callers or callees; never transitive). Requires a durable snapshot recorded at
   claim write time and at each verification: each anchor's snapshot records its
   own edge-set hash and its direct neighbours (identity → edge-set hash);
   comparison runs per anchor over the union of recorded and current neighbours,
   so removed and added neighbours are seen. A provider that cannot answer yields
   `unknown`, never a silent
   "not suspect". Neighbour body changes are ignored. `suspect` is computed in
   the index only (§6.2 rule unchanged) and composes with `stale`.
5. **Frontmatter schema & event kinds** — *settled 2026-09-25*: six event kinds — `.claim`, `.verify`,
   `.doubt`, `.undoubt`, `.refute`, `.unrefute` (`.same-as` later). Verification
   is an event, not a claim field: no `.md` file is ever modified after creation
   (§6.4's merge-conflict-freedom now holds for every event); promotion and
   re-verification append files; the index folds the newest `.verify` per target
   version. A version's anchor fingerprint set is immutable: a `.verify` attests
   to exactly the set recorded on the claim — verifying against changed
   fingerprints is a new claim version (§6.3). No `.unverify`: a mistaken
    verification is refuted. **Doubt** (recorded with its `source`, with a
    reason) records a
    human disagreement with a verified version *without claiming it is wrong*:
    the version stays visible, labelled "verified by code, disputed by X:
    reason"; `.undoubt` lifts it. Refutation stays for "provably wrong".
    Claim fields: `id`, `lineage`, `kind`, `class`, `source`, `summary` (mandatory
    one-liner, used verbatim in injections — OpenViking L0 lesson), `statement`,
    `format_version` (1; strict MAJOR-version rejection), `anchors`
    [{provider, identity, fingerprint, snapshot?}] — `snapshot` is provider-typed
    (code: `{edges, neighbours}`: the anchor's write-time edge-set hash and its
    per-anchor neighbour snapshot, input to `suspect`), `recorded_at` {commit,
    graph_commit} — the source version at write time (§10.2); fingerprints
    decide validity, the commit only qualifies (§6.2) —, `unanchored` (explicit;
    true only with a reason), `proof_query` (structural), `contradicts` +
    `reason` (optional pair, mandatory together),
    `name` (optional free string per §12.10 — the model name when `source: llm`,
    e.g. "glm-5p3-flash"; `cost_tokens` is read against it), `effort`
    (optional, llm only), `cost_tokens`
    (optional). `.verify`: `format_version`, `targets` (version ULID), `source`
    (unified provenance per §12.10; always shown in envelopes — with no
    credential system, review is the trust path), `verified_at` {commit +
    graph_commit; the per-anchor
    fingerprints are **not** repeated here — the verify attests to exactly the
    immutable set recorded on the claim}, `evidence`, `snapshots` (per-anchor
    mapping, same shape as the claim's anchor snapshots), with `name` (optional,
    same rule as the claim's) since the verifying session may not be the writing
    one. `.refute`: `targets`
   (a version or event ULID), `reason` (mandatory), `source`, `evidence`. `.unrefute`: `targets`
   (the refute event's ULID), `reason`, `source`. `.doubt`/`.undoubt`: `.doubt`
    targets a `.verify` event (disagreement with that verification, not with the
    claim), carries `source` (unified provenance, §12.10) like every event — no
    credential
    system exists — plus a reason;
    `.undoubt` targets the doubt event's ULID. `.refute` and `.doubt` may target
   **any event ULID**: refuting a claim version skips it in the §6.2 resolution;
   refuting a `.verify` (or `.doubt`) event makes the index ignore that event
   when folding. `masora check` validates the schema and
   the append-only history — content-based, never location-based (§7).
6. **Duplicate lineages (`same-as`)** — postponed (unchanged). ULIDs make the
   future event purely additive; search flags possible duplicates instead of
   claiming deduplication.
7. **Non-code provider interface** — *settled* (shape only; `file`/`url`
   implementations stay out of Phase 1): `resolve(ref) → identity | outcome`,
   `fingerprint(identity) → content hash`, `replay(query)` optional and
   code-provider-only. Outcome semantics defined now: `resolved` | `not_found` |
   `unavailable` | `ambiguous`. `file`: canonical path + optional section +
   sha256 of the section's bytes. `url`: normalized URL + digest of the content
   captured at write/verify time — validity never depends on a live refetch
   (rebuild determinism is a SPEC requirement).
8. **Co-change mining from git history** — later (unchanged).

Non-blocking refinements recorded from the design review (not Phase 1 scope):
computed-status presentation matrix (`current + suspect`, `stale + suspect`,
`restored`, provider-`unknown`); canonical proof-query vocabulary with
normalized expected results and recorded provider version; typed evidence
locators with content digests (Provena lesson); injection caps with explicit
omitted-count (already a SPEC requirement).

## 13. Suggested v0

- Claim/verify/doubt/undoubt/refute/unrefute `.md` format + layout of §7.
- SQLite index + resolution algorithm of §6.2 + FTS.
- MCP tools: `note`, `verify`, `refute`, `search`.
- Code anchor provider via cppgraph with per-symbol definition fingerprint.
- Injection of facts into cppgraph responses.
- `SessionStart` hook: pull + stale summary.

Enough to see quickly whether it changes the agent's behaviour.

## 14. Prior art to analyse (extract ideas; none does the whole thing)

None combines: exact compiler-level anchors + per-checkout validity by fingerprint
+ append-only history with refutations in git + replayable structural proofs.
Read their READMEs/docs before fixing the schema.

| Project | What it is | Ideas to extract | Differs from us |
|---|---|---|---|
| **OpenViking** — github.com/volcengine/OpenViking | "Context database" for agents: virtual filesystem (`viking://`), L0/L1/L2 tiered loading (abstract / overview / full), recursive directory retrieval, automatic memory extraction at session end | Tiered loading to save tokens (L0 one-liner in injections, L2 on demand); observable retrieval trajectory (see §14.1) | Automatic LLM extraction may store the very hallucinations we fight; no anchoring, no invalidation; needs VLM + embedding models; AGPL-3.0 |
| **Graphiti** (Zep) — github.com/getzep/graphiti | Temporal knowledge graph, facts with validity intervals | How they model validity/invalidation over time | Invalidation by new conversational info, not by code change |
| **Serena** — github.com/oraios/serena | LSP-based coding agent toolkit with `write_memory` / `read_memory` | The trigger for this project; the minimal MCP surface agents already use | Sticky notes: no provenance, no anchors, no staleness |
| **KSDaemon/seshat** — github.com/KSDaemon/seshat | Per-project knowledge graph of conventions, patterns, decisions via MCP; tree-sitter; Rust + SQLite | **2D-typed nodes** (nature × weight) — compare with our source × verification; **merge-aware decisions** (approved on a branch, survives merge, not re-surfaced); **auto-sync on git HEAD change**; `validate_approach` pre-flight tool; its competitive-analysis doc lists more neighbours (codebase-context, codebase-memory-mcp, axon, megamemory, socraticode, octocode) | By-name AST (no C++), convention detection focus, SQLite not md-in-git |
| **ravnltd/muninn** — github.com/ravnltd/muninn | MCP persistent memory for coding agents: `recall`/`remember`/`track`, Bun + SQLite, hooks installer | **Learning graduation** (proved patterns promoted, contradicted archived); **file co-change correlations** (source of indirect-dependency *suggestions*); decision→outcome linking; one-command multi-editor install + hooks | Statistical, file-level, local `.muninn/`, no human verification axis; AGPL-3.0; installs to `~/.local/share/muninn` |
| **progamesigner/muninn** — github.com/progamesigner/muninn | MCP server over a plain-markdown vault, multi-tenant scopes, human-editable (Obsidian-friendly) | Markdown vault UX; per-scope namespacing; small generic tool surface (9 tools) (see §14.1) | Generic memory, no anchors/verification |
| **infektyd/minni** — github.com/infektyd/minni | Local-first memory + governance daemon, per-agent vaults, review-first learning, audit trails | **Durable writes gated behind human approval by default**; motto **"recall is evidence, not instruction"** (tone of our injections); its README compares mem0, MemOS, basic-memory | Generic, embeddings + daemon, no code link |
| **nkenji09/scholia** — github.com/nkenji09/scholia | Product decisions + rationale linked to implementation changes; controlled vocabulary; plain JSON in git | **Git as the database, one record = one file, append-only decisions** — closest to our storage; controlled-vocabulary idea for claim kinds | No fingerprints, no auto-invalidation |
| **Provena** — pypi.org/project/provena-agent-memory | Evidence-backed memory: each claim points to an immutable source event, with scope, authority, review state, validity time, conflicts, retrieval history; `memory_explain` | **Provenance model** and **explain trace**; conflict representation; candidate claims | Central PostgreSQL service, no code anchoring |
| muninn-remembers — pypi.org/project/muninn-remembers | Semantic memory for OpenCode (ChromaDB), decisions, patterns, symbol index | Session-resumption UX | Semantic search, no verification |
| Magnus-Gille/munin-memory — github.com/Magnus-Gille/munin-memory | MCP memory on SQLite + FTS5 + sqlite-vec; "orient" dashboard; consolidation worker | SQLite/FTS5 stack; `memory_orient` dashboard idea for SessionStart summary; explicit response-budget metadata | Status/project memory, no anchors |

Names checked and **taken** in this niche (don't reuse): Muninn (many), Munin,
Munnin, Minni, Mímir (Grafana), Mnemosyne, Seshat, Symbolon, Scholion, Scholia,
Ratatoskr. Ollam rejected (collides with Ollama).

### 14.1 Verified findings (2026-09-25)

Findings verified against each project's upstream READMEs/docs; corrections to the table above and mechanisms it misses, in table order:

- **OpenViking** — github.com/volcengine/OpenViking: L0/L1 tiers are files stored next to the data (`.abstract.md` / `.overview.md`), not index entries; directory-scoped semantic search; session-end extraction emits editable Markdown; token metrics −34–91%; requires VLM + embedding models; AGPLv3.
- **Graphiti** (Zep) — github.com/getzep/graphiti: bi-temporal `valid_at`/`invalid_at` on fact edges; an episode is a resolvable provenance pointer to the raw event; contradiction detection is LLM-judged and invalidates facts — rejected as a validity decider for us, at most a suggester of refutations; Neo4j/FalkorDB backend; paper arxiv 2501.13956.
- **Serena** — github.com/oraios/serena: memories are per-project Markdown, name-addressable; tools take symbol names, never line numbers; in practice live code retrieval is used far more than stored memories, so unasked injection matters more than recall on demand; README shows an agent-graded eval recipe; SolidLSP is MIT, the app is GPL.
- **KSDaemon/seshat** — github.com/KSDaemon/seshat: 2D nature×weight typing confirmed; "merge-aware" means branch-identity, not content-identity; HEAD-watch auto-sync; `validate_approach` pre-flight; `map_diff_impact` on uncommitted diffs — candidate future feature; detectors are confidence-scored.
- **ravnltd/muninn** — github.com/ravnltd/muninn: 4 tools (recall/remember/track/muninn); Bun + libsql, not plain SQLite; learning graduation by outcome statistics — rejected; co-change predictions from `git log` — usable only as candidate claims; fragility score is an injection-ranking signal.
- **progamesigner/muninn** — github.com/progamesigner/muninn: ~14 tools now, not 9; the vault is the source of truth with a disposable in-memory index rebuilt on config mismatch; YAML frontmatter filterable via tantivy; Rust.
- **infektyd/minni** — github.com/infektyd/minni: approval gate with accept/reject/redact/merge/supersede; evidence-envelope format with instruction detection; approval is delegable but audited — provenance records the actual writer; daemon + FAISS posture rejected.
- **nkenji09/scholia** — github.com/nkenji09/scholia: git-as-database confirmed, but JSON, not md; corrections via typed `supersedes` entries; machine-checkable `effect` field (in-force/replaced); forbids hand-editing — the inverse of our stance, invariants enforced by CI validation instead; Go single binary.
- **Provena** — pypi.org/project/provena-agent-memory: the pip package is only the connector; the service is self-hosted Docker Compose (Postgres + FastAPI + Ollama); dual credentials — review actions require the human credential; branch-scoped memory; `memory_explain` trace.
- **muninn-remembers** — pypi.org/project/muninn-remembers: also targets Claude Code, not just OpenCode; ChromaDB + Ollama; sha1-keyed symbol index without fingerprints — the dead end we avoid.
- **Magnus-Gille/munin-memory** — github.com/Magnus-Gille/munin-memory: mutable state vs append-only log entry types; supersedes + mandatory `expected_updated_at` with `memory_read(as_of)` rewind; review-first capture; trust is prompt-enforced, not structural; response-budget metadata.
