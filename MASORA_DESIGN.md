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
  generated without coordination, time-sortable. The ULID orders events,
  breaks selection ties at every tier, and is the whole ordering of tier 2 —
  no separate timestamp field that could contradict it (a human-readable
  created_at may be derived for display).
- **Fingerprints, not timestamps, decide applicability to code.** Among
  matching versions, provable git relation to the asking line ranks first,
  ULID second (§6.2's sel) — provenance preference among content-true
  facts, never a validity judge. (Comparing knowledge dates to code commit
  dates is wrong: branches, rebases, cherry-picks.)

### 6.2 Resolution algorithm (at index time)

Inputs, evaluated for EVERY eligible version — active AND refuted (the
counterfactual `restored` rule and the negative envelope need both):

1. structured outcome of the version's anchors — `match` (all anchors match) |
   `mismatch` (none absent, none unavailable, at least one fingerprint
   differs) | `not_found` (at least one anchor definitively absent, none
   unavailable) | `unavailable` (any anchor cannot be evaluated); the provider
   outcome contract of SPEC.md (§ Constraints) is implemented at this layer,
   never guessed from a bare `None`;
2. the version's establishment context: the `recorded_at.lines` fork-point
   map (FORMAT.md §4 — per known line ref, the merge-base with that line at
   write time) plus the relation of its `recorded_at.commit` to the asking
   checkout's HEAD — `in_line` (provable ancestor OR equal — a freshly
   written fact is in its own line) | `ahead` (provable proper descendant
   that is also an ancestor-or-equal of the asking branch's upstream ref —
   this line's newer history, never colleagues' unmerged features) |
   `out_of_line` (provable, neither) | `relation_unknown` (missing object,
   shallow clone, probe budget exhausted). The relations are DESCRIPTIVE labels; the ranking is the
   TIERS below.

**The selection function `sel(S, B)`** — S is a set of versions, B the
asking branch; sel returns exactly one version (when S ≠ ∅), nothing to
transitivize (rounds 6-8 PROVED every richer scheme fails a real case:
pairwise ancestry+ULID is cyclic; branch-NAME stamps cannot name the landing
line; bare merge-base recency shadows this line under newer trains;
fork-point ranking lets a 9.0-only note shadow master's squash-landed note;
unrestricted `ahead` lets colleagues' unmerged features win). The final
ranking is DELIBERATELY simple — and sound because the stakes are honest:
among MATCHING versions every displayed fact is content-true for this
checkout (fingerprints decide), so the ranking is a provenance preference,
and a NON-matching version can never hide a matching one (the fallback only
fires when nothing matches):

1. TIER 1 — provably on the asking line: the establishing commit is an
   ancestor of, or equal to, the asking HEAD (`in_line`), or a proper
   descendant that is ALSO an ancestor-or-equal of the asking branch's
   UPSTREAM REF as present locally (never fetched — `origin/<branch>`;
   the ref's own commit counts as an ancestor). Detached HEAD or a missing
   upstream means NO `ahead` is provable — colleagues' unmerged features
   and other trains' commits are excluded. Rank within: `ahead` outranks
   `in_line` (the line's newest known history beats an older state of it);
   among themselves, maxima under proper ancestry, then descending ULID;
2. TIER 2 — everything else: descending ULID.

sel(S, B) = the highest non-empty tier, ranked as stated. Always exists for
S ≠ ∅ (founderless/empty eligible sets resolve to `unknown` upstream);
unique; no pairwise order is claimed. The `lines` fork-point map is CONTEXT,
never a ranking input.

The rules (all over `sel`, uniformly):

3. **Display**: `sel(active matches, B)` — resolution `current`;
4. **`restored`** (counterfactual): ONLY when a version is displayed (rule 3
   fired) — some REFUTED eligible version R satisfies
   `sel(active matches ∪ {R}, B) = R`, whatever R's own outcome (the
   uncertainty is R's fingerprints, not its rank). It would have won the
   line had it not been refuted; a refutation that never outranks anything
   triggers nothing;
5. **No match**: the fallback is `sel(active versions, B)` — the SAME
   function, so this line's drifted fact can never be masked by a younger
   off-version; resolution `stale`; `off-version` is set iff the FALLBACK
   VERSION's own composed outcome is definitive absence (`not_found`, none
   `unavailable`) AND the fallback's relation is PROVABLY `out_of_line`
   (a `relation_unknown` fallback stays plain `stale` — conservative, on
   the re-verification list; an in-line or ahead fallback is this line's
   own drift and stays plain `stale` too); another version's `mismatch`
   neither grants nor removes the flag;
6. **Shadow (counterfactual, uniform, ACTIVE versions only)**: an
   `unavailable` version U sets `unknown` on the result iff
   `sel(active matches ∪ {U}, B) = U` — it would display in place of the
   selection. One reading only; the same function on both paths; the
   DISPLAYED version under an `unknown` shadow is the known match that sel
   picked — or, on the no-match path, the rule-5 fallback (an acknowledged
   change from today's newest-active display);
7. **Self-unavailable**: when the displayed/fallback version's own outcome is
   `unavailable`, `unknown` shadows it — a provider-down lineage is never a
   bare `stale` (the one-version lineage included);
8. **`off-version` and `unknown` together**: when `unknown` shadows,
   `off-version` is suppressed — the lineage is not provably inapplicable
   while an unevaluable version might match; it reports `unknown` and stays
   on the re-verification list (conservative).

Resolution stays the closed enum `current | stale | restored | none` (plus
the `unknown` shadow); `off-version` is a FLAG, never a resolution value.

Properties:

- a colleague on old code automatically gets the old version that matches their
  code, **and** gets error corrections (refutations apply everywhere);
- a code revert makes the matching fingerprint valid again → the old claim comes
  back by itself;
- among MATCHES the display is always content-true for this checkout, so
  the ranking is provenance preference, never validity; squash-landed notes
  are tier 2 and ranked by ULID — a fact written today on an old release
  train CAN display over a squash-landed note of the asking line (both tier
  2), an accepted provenance preference documented beside the cherry-pick
  blind spot; a fact whose fingerprints do NOT match can never hide a
  matching one (the fallback only fires when nothing matches);
- under squash merges the establishing commit dies on landing: applicability
  survives (fingerprints decide — the content landed), the relation label
  degrades honestly (out_of_line or relation_unknown, surfaced), and the
  note is tier 2 (its ULID ranks it);
- cherry-picks are a known, accepted blind spot: a cherry-picked establishing
  commit is a DIFFERENT SHA — the matching version still displays
  (fingerprints decide applicability) but is labelled out-of-line ("not
  proven in this checkout's ancestry", never "not on this branch");
  patch-equivalence detection is deliberately out of scope;
- the SQUASH twin of that blind spot (owner-ruled): a squash-landed note is
  provably out_of_line, so when THIS line later renames its symbol the
  fallback fires `off-version` although the note is this line's own — git
  cannot distinguish "landed here by squash" from "belongs to another
  line"; accepted: the note keeps displaying with its context in
  search/explain and only leaves the re-verification list;

**Degradation is visible and deterministic**: `context_ordering: exact |
degraded` is a PER-LINEAGE state (surfaced per fact in facts v2),
counterfactually defined — `degraded` iff some version's UNPROVABLE context
(missing object, probe budget exhaustion) could change sel's result — what
displays, the shadow decision or the restored decision (making it provable
changes one of them; the same counterfactual machinery as the shadow rule,
applied to the tier membership and the ancestry maxima; `off-version` is
OUT of scope — its guard requires a PROVABLE relation, an unprovable one
never grants the flag). Probes
(`git merge-base --is-ancestor` both directions for the tier-1 relations and
their maxima — all probes share the same build budget) are memoized per SHA
pair, and lineages are processed in ascending lineage-id order — adding an
unrelated lineage never changes an earlier lineage's result within the
budget; a version whose needed probe cannot run demotes to
`relation_unknown` — an input to the COUNTERFACTUAL `degraded` test above
(visible, never silent); a failed pairwise
probe among tier-1 candidates is read as INCOMPARABLE (never domination) and
never demotes a proven relation. `explain` re-resolves live with a fresh
budget: its (possibly better) ordering is authoritative for its own output
and both states are surfaced — an index served `degraded` after a later
`git fetch` stays degraded until a rebuild (the staleness axes gained the
object-store blindness knowingly; the degraded label covers it).

**Branch courtesy labels are never persisted as history**: the write-time
`lines` fork-point map is the TOOL's mechanical record (never an agent
argument, never backfilled by rewriting events — absence IS the unknown
value); `git branch --contains` at recall time is a CURRENT-refs courtesy
(merges move it; rebases erase the original); the commit is the
authoritative surface, labels are best-effort, capped, fail-open to
commit-only.

**Computed status lives only in the SQLite index, never in the .md files.** The
next indexer does the same computation; files are never touched for status.
Per-version context (establishing commit, verifying commits per claim version)
is persisted per version row, not per lineage — a lineage-level "establishing
commit" is ambiguous when several active versions live on several release
trains.

**Computed status is a tuple**, rendered in every envelope:

- `resolution`: `current` | `stale` (no version matches; `sel(active
  versions)` is shown) | `restored` (a refuted version would win sel —
  counterfactual, rule 4) | `none` (every version of the lineage is refuted);
- `verification`: `verified(<source>)` | `unverified` — folded from `.verify`
  events per DISPLAYED version (each release line keeps its own verification);
- flags: `suspect` (§12 item 4), `doubted` (iff some active doubt targets an
  active verify of the displayed version), `pending` (events not yet merged —
  §8), `unknown` (conditional shadow or self-unavailable — rules 6-7 above;
  shadows the resolution instead of guessing), `off-version` (the fallback's
  own outcome is definitive absence AND it is provably not of the asking
  line — suppressed while `unknown` shadows; excluded from re-verification
  lists, reported in a separate "not applicable here" list). An anchor that
  is `not_found` fails to match AND is distinguished from `unavailable`
  throughout status, explanation and facts.
- Status precedence is `none` > `unknown` (conditional shadowing) >
  `current`/`restored` > `stale`. Event folding follows FORMAT.md's
  active-event rule (which verifies, refutes, doubts and undoubts are active);
  activity is evaluated backwards in descending ULID order to a fixed point
  before folding, and resolution requires the founding claim — a v2+ version
  whose founder (`id == lineage`) is absent is excluded. The commit-order
  relation and the structured outcomes are INJECTED at recall (the fold stays
  pure; `check` and the format know nothing of git or providers).
- A later `.verify` never clears a doubt; only `.undoubt` does.
- An explicitly `unanchored` claim has no fingerprint resolution: it is always
  surfaced, and its `unanchored` flag is the validity signal (the §2 guard-rail
  makes it rare and loud); it can never be `off-version`.

Recall filtering: the FTS matches every version (unchanged); the DEFAULT
result filter keeps hits on the DISPLAYED version — and on the NEWEST version
for `none` lineages (displayed is null; negative knowledge stays findable,
matching the facts behavior). The explicit any-version mode queries ALL active
eligible versions (never refuted ones — refuted archaeology belongs to a
future `history` tool with refutation-first rendering); a hit on a
non-displayed version renders the HIT version's identity and its own context
(never borrows the displayed version's), with the lineage's status tuple
alongside. Legacy events predating the commit-stamp era (none expected —
stamps shipped with the format) would carry `absent` context: excluded from
context filters, ULID-only ordering, visibly qualified.

The cppgraph injection contract (v2) carries Masora-EVALUATED relations per
fact — `established_commit`, `verified_commit` (short, presentation-only),
`established_relation` (`in_line | ahead | out_of_line | unknown`),
`off_version`, `context_ordering` (the lineage's selection state) — so
cppgraph renders context without computing ancestry itself. The rendering
rule fires when it matters: `off_version`, OR `established_relation` other
than `in_line` (the cherry-picked current fact is labelled out-of-line, the
ahead fact is labelled ahead), OR `context_ordering: degraded` — on
merge-commit repos the common case keeps today's token cost; on SQUASH
repos most landed facts are out_of_line, so the context line renders on
most facts (accepted: the label is one short token cluster).

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
  2026-09/                                   # month the founder was written
    resume-token-shard-key-01J8Z3K…/         # lineage dir: <slug>-<ulid>
      01J8Z3K….claim.md                      # v1
      01J8Z3K….verify.md                     # verifies v1 (targets its ULID)
      01JA4QX….claim.md                      # v2 after code change
      01JB7RM….refute.md                     # refutes v1 (targets its ULID)
    lock-before-commit-01J8ZP2…/
      01J8ZP2….claim.md
```

- One directory per lineage, and exactly one: all events of a lineage live in
  that single directory, its history is its file listing. The directory is
  created with the founder claim in the founder's month; every later event of
  the lineage joins it (the writer looks the lineage up by ULID suffix and
  writes into the existing directory — extensions are never re-bucketed by the
  current month).
- Slug: a deterministic lowercase form of the founder's summary (`[a-z0-9-]`,
  ≤ 24 chars, word-boundary trimmed) — cosmetic, fixed at creation, immutable
  thereafter, never an identity, never renamed; optional for hand-made trees
  (a bare `<ulid>/` directory is equally valid).
- Suffix gives the event kind: `.claim`, `.verify`, `.doubt`, `.undoubt`,
  `.refute`, `.unrefute` (later `.same-as`). Verification is an event (§12 item 5):
  promoting or re-verifying appends a file, nothing is ever edited in place.
- Month bucket avoids tens of thousands of entries per dir while staying readable.
- **Layout is convention, not law**: `masora check` validates content (unique
  ULIDs, resolvable references), never file locations; the index parses the whole
  tree, so moving files changes nothing.
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

11. **Cross-analysis: tests × code** — *open, not scheduled*: cppgraph + masora
   could correlate tests with the code — and the claims — they exercise: the
   graph's call edges already know which symbols a test's code path touches,
   and the base knows which claims anchor those symbols, so the union can
   surface untested behaviours (symbols with no test-reaching path), detect
   claims whose evidence cites no test, and propose test extensions where a
   behaviour is claimed but unproven. The data exists on both sides; nothing
   about the mechanism, the ranking or the surface is decided.

12. **Single base per project** — *settled 2026-10-01 with the design owner*:
    one base per code project is the expected usage in practice; the
    multi-base configuration (§9's `[[mappings]]` / `[bases.<name>]`) stays a
    latent capability documented only in the internal docs (SPEC.md,
    MASORA_DESIGN.md, docs/ARCHITECTURE.md), never in install-facing docs
    (README).

13. **Sync-time stacking audit** — *settled 2026-10-01 with the design owner*:
    a multi-fact "block claim" note is tolerated locally (no command blocks on
    writing one) but must not reach the shared base — the publication gate is
    where containment matters. `masora sync` audits its pending set (the added
    CLAIM events only; verify/doubt/refute are structurally small) with
    conservative stacking heuristics — statement length, anchor count, anchors
    spanning several files — and refuses (`E-SYNC-STACKED`) naming each
    flagged lineage with its fired signals and the split remedy; the refusal
    mutates nothing. `--allow-stacked` is the explicit human decision to
    publish anyway: the refusal becomes a per-lineage `W-SYNC-STACKED`
    warning riding the PR body. The thresholds are conservative constants
    (`masora/audit.py`), pending calibration on the real base — the
    132-lineage audit expects the 7 known block claims to fire and the 125
    clean ones to pass.

14. **gc's unpublished-lineage exception + the stacked reflex** — *settled
    2026-10-01 with the design owner*: a lineage whose event files are absent
    from origin/main's tree was never published — `masora gc` removes it
    locally WITHOUT tombstone rows (`deleted.toml` records only what the
    shared repo knew; a dead-born ULID never reaches the shared ledger), and
    published lineages keep the append-only `[[deleted]]` rule unchanged
    (FORMAT.md §7.10). Published-ness is only knowable from origin/main, so
    gc's "no git spawn" property narrows to "no git mutation — one read-only
    origin/main ls-tree for published-ness" (after a ref-existence probe; a
    missing origin/main or no origin ⇒ everything is unpublished, a git
    failure is an `E-GIT` error — never a silent guess). The stacked-reflex
    loop completes the §12.13 remedy: when sync refuses with E-SYNC-STACKED,
    the agent splits into one atomic note per fact, deletes the unpublished
    block claim with `masora gc --lineage` (no tombstone — origin/main never
    saw it) and re-runs sync; a stacked note is never published by default.

15. **Sync is plan-then-confirm; `STATEMENT_MAX` 2048** — *settled 2026-10-02
    with the design owner*: sync's default must not act — like gc and compact,
    a bare `masora sync` runs the full gate pipeline (local check, diff,
    stacked audit, merged-result validation), prints the pending set in the
    PR body's rendering and exits 3 with nothing written (no branch, no push,
    no PR, no local ref mutation); `--yes` is the single confirmation gate for
    every mutating mode — publish = `sync [--push] --yes`, discard =
    `sync --drop --yes` — while `--push` stays a mode selector and
    `--allow-stacked` is unchanged (the stacked refusal still fires in plan
    mode). `STATEMENT_MAX` is 2048, calibrated on real-corpus evidence:
    real-base atomic notes reach ~1560 characters and must pass the stacking
    audit, so the write-time descriptions state the soft publication limit —
    no hard limit, but above 2048 characters the sync-time audit refuses
    publication by default (E-SYNC-STACKED) — so note writers aim tight
    before sync.

16. **One base over release trains: version-qualified recall** — *settled
    2026-10-02 with the design owner* (owner context: release-train branches
    several release trains, a large distributed team, recall mostly OFF the
    establishing branch; two design-review rounds, the second STOP until the
    semantic contract was finished). Rulings: (a) NO format change — the
    `recorded_at`/`verified_at` `{commit, graph_commit}` stamps already
    carry the code state; the fold already selects the displayed version per
    checkout and attaches verification per version. (b) The selection among
    MATCHING versions couples with commit order per branch (owner: "ULID
    chronology has no value") — in-line matches (establishing commit an
    ancestor of the asking HEAD) outrank out-of-line ones; maxima under
    ancestry, descending ULID tie-break (incomparable ancestors are real in
    merge DAGs); out-of-line displays only when no in-line version matches;
    the fold stays PURE (relation injected at recall; check/format know
    nothing). (c) Structured per-anchor outcomes (match / mismatch /
    not_found / unavailable — SPEC's outcome contract, previously conflated
    behind None) composed per version; an unavailable version shadows only
    when it could outrank the selected match (conditional shadow — owner
    ruling). (d) Shallow/missing-object degradation is VISIBLE
    (`context_ordering: exact | degraded` + a distinct warning class) — the
    silent ULID fallback would reintroduce the shadowing bug the ordering
    exists to kill (owner ruling). (e) Cherry-picks are a documented blind
    spot: ancestry is the conservative relation, out-of-line is descriptive
    ("not proven in this ancestry"), never "not on this branch"; no
    patch-equivalence detection. (f) `off-version` is a narrow flag
    (definitive anchor absence explaining a no-match fallback), leaves
    `list_stale` for a separate "not applicable here" list (owner ruling).
    (g) Compact preserves EVERY active version's witness — universal
    preservation, each release line keeps its verification (owner ruling;
    accepted cost: less compression on long-lived trains). (h) Recall
    filters: displayed version by default, explicit any-version mode over
    ACTIVE versions only — refuted archaeology waits for a future `history`
    tool (owner ruling). (i) Facts contract v2 ships in coordination with
    cppgraph (owner owns both sides and releases them together — "the BEST
    solution, not the least costly"): Masora EVALUATES the relation
    (`established_relation: enum superseded by §6.2 — in_line | ahead | out_of_line | unknown` +
    short commits + `off_version` + `context_ordering`), cppgraph only
    renders it (it cannot derive ancestry from short SHAs), showing context
    only when it matters; branch names never enter the contract. (j) Branch
    labels are lookup-time courtesies (`git branch --contains`, memoized per
    SHA, capped, fail-open to commit-only), never persisted, never labelled
    "establishing branches". (k) Per-version context is persisted per
    VERSION row (plus a verifications table), not per lineage. Legacy
    un-stamped events (none expected) would carry `absent` context:
    ULID-only selection, excluded from context filters, visibly qualified.
    (l) Round-5 deep-audit rulings: the selection ranks EVERY eligible
    version — active AND refuted — and drives display, the no-match
    fallback, `restored` and the shadow test alike.     (m) Rounds 6-7 rulings — the RANKING part superseded by (n) (tiers-2/3,
    line-stamped ranking and the tier-3 off-version guard retired; the
    counterfactual restored, HEAD-equal in_line, off-version suppression,
    compact's refuted closures and the probe budget survive) — deep audits
    #2 and #3; round 7 SCRIPT-ENCODED
    sel and demonstrated that both a branch-NAME stamp and bare merge-base
    recency fail a real case — the stamp cannot name the landing line and
    merge-base recency shadows this line under newer trains): the owner
    ABROGATES the no-format-change premise ("test phase, no real users —
    we will migrate and fill what is missing") and ADOPTS the FORK-POINT
    MAP — `recorded_at.lines`/`verified_at.lines`: `{branch: fork-point}`
    for every line ref known at write time (`merge-base(HEAD, <line
    ref>)`, tool-captured, never an agent argument; absence IS the unknown
    value — events are never rewritten to backfill) — the fork point lives
    ON each line, so it survives squash merges; and the TIERED selection
    `sel(S, B)`: tier 1 = provably on the asking line (in_line/ahead;
    ahead outranks in-line, then ancestry maxima, then ULID), tier 2 =
    stamped for the asking line (fork-point maxima, then ULID), tier 3 =
    the rest (ULID) — resolving the ruling-5 (in-line first) vs squash
    (fork recency) tension by construction; `restored` is counterfactual
    via sel (some refuted R: sel(matches ∪ {R}) = R, guarded to fire only
    when a version displays, whatever R's own outcome); `in_line` includes
    HEAD-equal commits; `off-version` requires the fallback to be tier 3
    (provably not of the asking line — an in-line or line-stamped fallback
    is this line's own drift and stays stale); compact keeps the closure
    of REFUTED versions too (the counterfactual restored depends on them);
    all probes share the build budget with a
    demote-to-unknown-on-exhaustion rule; a dedicated plan stage ships the
    stamp (schema acceptance, canonical key order, tool-side capture,
    templates) BEFORE any writer emits it. (n) Round-8 rulings (deep audit
    #4, script-reproduced): the fork-point map is DEMOTED to context —
    never a ranking input (a fork point recorded at write time cannot know
    where the work lands; bare recency shadowed the asking line); the
    final sel is TWO-TIER — tier 1: provably on the asking line (in_line
    ancestor-or-equal, or ahead RESTRICTED to a proper descendant that is
    also an ancestor-or-equal of the asking branch's UPSTREAM ref
    as present locally (never fetched; detached HEAD or missing upstream =
    no ahead) — colleagues'
    unmerged features excluded), ahead outranks in-line, then ancestry
    maxima, then ULID; tier 2: everything else by ULID; the ranking among
    MATCHES is provenance preference among content-true facts (never
    validity) and a non-match can never hide a match; `off-version`
    requires a PROVABLE out_of_line relation (relation_unknown stays
    stale); the displayed version under an `unknown` shadow is the known
    match (acknowledged change from today's newest-active display); the
    negative envelope keeps its ULID-newest rule explicitly (independent
    of sel). (p) Migration ruling (beta, no real users): NO in-place data
    migration. Indexes are derived caches — rebuild freely after any schema
    bump. Event files without the `lines` stamp stay valid forever (absence
    IS the unknown value, never backfilled — only new writes stamp).
    Obsolete fiches may be purged via `masora gc`. The facts contract flips
    to v2 without a dual-version window: cppgraph (same owner, same
    release train) learns v2 first, then Masora flips
    CONTRACT_VERSION=2 and retires v1 in the same change.
    (o) Round-9 ruling: the SQUASH off-version twin is ACCEPTED
    and documented (§6.2 Properties — a squash-landed note renamed later
    on its own line fires off-version; undecidable from git; the note
    keeps displaying with its context and only leaves the re-verification
    list).

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
