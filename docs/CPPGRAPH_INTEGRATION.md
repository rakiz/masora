# cppgraph ⇄ Masora injection contract

Handoff document for implementing Masora fact injection inside **cppgraph**.
Written from the Masora side; everything cppgraph codes against is pinned
here. Status: the contract is final and implemented — `masora facts` ships
with Masora; the cppgraph side (registering the call, §8) is pending.

## 1. Context

Masora is a git-backed, append-only knowledge base of claims anchored to code
symbols: each claim lives as a small `.md` event file in a *base* (a separate
git repo), and a disposable per-checkout SQLite index recomputes each claim's
status (resolution, verification, flags) from anchor fingerprints. Masora
never touches the code repo. Every claim version also carries the git context
it was established against: the index stamps each version with its relation
to the asking checkout's HEAD, and the facts contract exposes those stamps so
cppgraph can render the context — **Masora evaluates, cppgraph renders**.
The integration contract (SPEC.md line 19,
quoted verbatim):

> Anchor providers must be pluggable with kinds `code`, `file` and `url`;
> cppgraph integration must be optional (without it, nothing changes for
> cppgraph): Masora exposes an index cppgraph can read to inject facts.

So: cppgraph MAY attach Masora facts to its responses when a Masora
installation covers the checkout it is looking at. Without Masora installed,
or with no matching base, cppgraph's behavior is unchanged — no output, no
error, no added latency beyond the budget of §5.

## 2. The integration surface

One command, spawned as a subprocess by cppgraph:

```
masora facts --repo <path> [--symbol <scip-string> [--symbol <scip-string> ...]]
```

- `--repo` — path to the code checkout being looked at (required; usually the
  repo root cppgraph was run on).
- `--symbol` — optional exact SCIP symbol string, REPEATABLE: one spawn may
  carry several flags to match N symbols in one document (multi-symbol
  responses pass them all, §6). Matching is OR-semantics: a lineage is
  returned when its effective version anchors on ANY of the passed
  identities (matched verbatim — the same rule Masora's provider uses); for
  lineages with `resolution: "none"` (every version refuted) matching uses
  the newest version, since the displayed version is null. The per-lineage
  `anchors_matched` accumulates every identity the query matched across all
  passed flags (deduplicated, in call order). Without the flag, all lineages
  of the matching base(s) are returned.

Output: a single JSON document on stdout (one line, but parse it as a
document, not as a line protocol). cppgraph should code against the shape of
§3 only — never against Masora's SQLite schema (§7).

How cppgraph detects Masora: the presence of the `masora` binary on `PATH`
(e.g. `shutil.which`) is the only detection signal; if it is absent, cppgraph
makes zero change (the §7 zero-change guarantee already covers this).

## 3. Output contract — version 3

```json
{
  "contract_version": 3,
  "repo_head": "1a1a8e1f4e5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c",
  "graph_commit": "0e5f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f",
  "stale_warning": false,
  "lineages_examined": 3,
  "lineages_matched": 3,
  "presence_hint": null,
  "facts": [
    {
      "lineage": "01J8Z3K0000000000000000000",
      "summary": "Resume token invalidated by a shard key change",
      "resolution": "current",
      "verification": "verified(llm)",
      "flags": "-",
      "source": "llm",
      "name": "glm-5p3-flash",
      "effort": "high",
      "anchors": [
        "scip-clang cxx . . mongo/ResumeTokenData#makeResumeToken()."
      ],
      "anchors_matched": [
        "scip-clang cxx . . mongo/ResumeTokenData#makeResumeToken()."
      ],
      "anchor_leaf": "makeResumeToken",
      "established_relation": "in_line",
      "established_commit": "1a1a8e1f4e5a",
      "off_version": false,
      "context_ordering": "exact"
    },
    {
      "lineage": "01J8ZP20000000000000000000",
      "summary": "Lock L must be held before calling commitShard",
      "resolution": "stale",
      "verification": "unverified",
      "flags": "suspect",
      "source": "human",
      "name": null,
      "effort": null,
      "anchors": [
        "scip-clang cxx . . mongo/Engine#commitShard()."
      ],
      "anchors_matched": [
        "scip-clang cxx . . mongo/Engine#commitShard()."
      ],
      "anchor_leaf": "commitShard",
      "established_relation": "out_of_line",
      "established_commit": "9f8e7d6c5b4a",
      "off_version": true,
      "context_ordering": "exact"
    },
    {
      "lineage": "01JB1R00000000000000000000",
      "summary": "changeStream re-opens on resumeToken == null",
      "resolution": "none",
      "verification": "unverified",
      "flags": "-",
      "source": "llm",
      "name": null,
      "effort": null,
      "anchors": ["scip-clang cxx . . mongo/Util#tick()."],
      "anchors_matched": ["scip-clang cxx . . mongo/Util#tick()."],
      "anchor_leaf": "tick",
      "established_relation": null,
      "established_commit": null,
      "off_version": false,
      "context_ordering": "exact"
    }
  ]
}
```

Field semantics (types, nullability, enums):

| Field | Type | Meaning |
|---|---|---|
| `contract_version` | integer | `3`; §3's shape IS version 3's shape — any field addition or change lands as a new major `contract_version`, and producers never enrich a shipped shape in place; a major-version change means an incompatible shape — cppgraph rejects unknown major versions and renders nothing; checked as a strict integer: a JSON boolean is invalid even where the language conflates bool and int (e.g. Python `True == 1`) |
| `repo_head` | string \| null | code repo HEAD the statuses were resolved against, or `null` (not a git checkout) |
| `graph_commit` | string \| null | cppgraph-indexed commit that served the code fingerprints, or `null` (no usable graph store) |
| `stale_warning` | bool \| null | `true` when the base or code state moved since the index was built, OR events were written after it (filesystem freshness — an uncommitted note moves no git HEAD; the build moment is compared against the base tree's newest event-file mtime with a ~2 s tolerance); `false` current; `null` when not comparable |
| `lineages_examined` | integer | the number of lineages the document pipeline walked (the population the matching loop iterates, BEFORE matching) — 0 on an empty base |
| `lineages_matched` | integer | how many of the examined lineages are present in `facts` (always `== len(facts)`); `0` when the filter matched nothing |
| `presence_hint` | string \| null | masora's capability line, rendered by cppgraph VERBATIM when zero facts render and zero lineages were examined (§6's zero-fact rule); masora owns the wording (including the tool names — cppgraph never hardcodes them); `null` whenever facts exist or lineages were examined (cppgraph then derives its own staleness line from the counters) |
| `facts` | array | zero or more facts, one per matching lineage; may be empty |
| `facts[].lineage` | string | lineage id — stable across versions; use it for dedup/caching |
| `facts[].summary` | string | one line, ≤ 120 chars — rendered verbatim |
| `facts[].resolution` | string | `current` \| `stale` \| `restored` \| `none` \| `unknown` (§6); `unknown` = provider unavailable, shadows the resolution |
| `facts[].verification` | string | `verified(<source>)` with source `human` \| `llm` \| `graph`, or `unverified` |
| `facts[].flags` | string | comma-joined subset of `suspect,doubted,pending,unknown,unanchored`, or `-` when none |
| `facts[].source` | string \| null | the effective version's provenance (`human` \| `llm` \| `graph` — the claim writer's nature), or `null` when unavailable |
| `facts[].name` | string \| null | the writer's self-signed name (git user.name for `human`, model name for `llm`), or `null` when absent |
| `facts[].effort` | string \| null | the declared LLM effort (`low` \| `medium` \| `high`), or `null` unless the version was written by an llm with an effort recorded |
| `facts[].anchors` | string[] | the effective version's FULL anchor-identity list (not only the ones matched by `--symbol`) — the anchor leg of the SPEC evidence envelope |
| `facts[].anchors_matched` | string[] | the effective version's anchor identities the query matched; for `resolution: "none"` they come from the newest version (displayed version is null); with a repeatable `--symbol`, the identities matched across ALL passed flags accumulate here (deduplicated, in call order); empty when no `--symbol` was passed |
| `facts[].anchor_leaf` | string \| null | the SHORT leaf of the FIRST matched anchor identity (in call order — a RENDERING INPUT consumed by §6's multi-symbol rule), derived by masora because masora owns the identity format: take the segment after the last `#` in the identity, up to but excluding the `(` disambiguation hash (when the identity has no `#`, the segment after the last `/` instead), then strip a trailing `.` — e.g. `…mongo/Engine#commitShard().` → `commitShard`; `null` when no `--symbol` was passed (single-symbol-era responses and full enumeration keep the response symbol-centered or unbound, so no leaf is needed) |
| `facts[].established_relation` | string \| null | Masora-EVALUATED relation of the **displayed** version's establishing commit against the asking checkout's HEAD: `in_line` (ancestor-or-equal of HEAD, HEAD-equal included) \| `ahead` (proper descendant of HEAD, below the branch's upstream ref as present locally — never fetched) \| `out_of_line` (provably neither) \| `unknown` (proven not in_line, but the ahead test could not finish); `null` when nothing displays (`resolution: "none"` — the summary then comes from the newest version) or the context was unprovable (shallow clone, missing object, probe budget). A qualification, never a validity input (§6) |
| `facts[].established_commit` | string \| null | the displayed version's establishing commit, SHORT (12 hex chars) — presentation-only: a pointer for the rendered context, never an input to any comparison (cppgraph cannot derive ancestry from it, by design); `null` when no version displays (`resolution: "none"`) or the displayed version is unstamped (no recorded commit); present even when context is unprovable (`established_relation` is null) |
| `facts[].off_version` | bool | `true` when the shown version is the no-match fallback whose anchors are definitively absent here (`not_found`) AND provably `out_of_line` — the claim is not applicable to THIS checkout; never silently read as current |
| `facts[].context_ordering` | string | `exact` \| `degraded` — `degraded` means some version's git context was unprovable and, if it became provable, what displays, the shadow decision or the restored decision could change; the served selection stays readable but its context is incomplete. Per LINEAGE (it qualifies the selection, not one version) |

The v3 shape is version 2's shape PLUS the three multi-symbol rendering
fields (`anchor_leaf`, the two counters, `presence_hint`) — nothing was
removed; the v2 fields are required in v3 (a fact missing one is a shape
violation, §7 fail-closed), and so are the v3 fields on the document.

## Beta release note — contract version 2 only, no dual-version window

Masora and cppgraph ship on the same release train under the same owner
(MASORA_DESIGN.md §12.16(p)): cppgraph learns contract version 2 with the
release that flips Masora to it, so there is no window in which one side
emits v1 while the other expects v2 — Masora produces ONLY the §3 shape, and
a consumer that knows nothing but version 1 renders nothing (the zero-change
guarantee of §7 covers it silently). No negotiation, no version preference
list: `contract_version` 2 or nothing.

## 4. Discovery: cppgraph passes `--repo`, nothing else

The command resolves the base(s) itself, from the user-side config
`~/.config/masora/config.toml` (written by `masora setup`): `[[mappings]]`
blocks match the code repo's normalized `origin` remote to base names, with a
`default_base` fallback. A repo matching no mapping and no default gets no
injection by design — cppgraph must not locate, clone or guess bases, must
not read `config.toml`, and must never point `--repo` anywhere but the actual
checkout. A relocated Masora home (`MASORA_HOME`) is the user's business; the
command handles it.

## 5. Exit codes and the two warning classes

- **0** — facts delivered, possibly empty. The two warning classes are
  in-band and are *never* errors:
  1. **stale index** → `stale_warning: true` (Masora's `W-IDX-STALE`: base
     HEAD, repo HEAD or the graph's indexed commit moved since the build, or
     events were written after it — filesystem freshness catches uncommitted
     notes that move no HEAD).
  2. **graph unavailable for fingerprints** → the affected lineages carry the
     `unknown` flag (Masora's `W-IDX-GRAPH` semantics: an anchor provider was
     unavailable, so `unknown` shadows the resolution instead of a guessed
     status). The shape does not change.
- **non-zero (1)** — hard failure: no base resolved, unreadable config, or a
  missing/unusable index (the command is read-only: it never builds the
  index — build it with `masora index <base-dir> --repo <path>`). stdout
  carries no contract document. **Any non-zero exit — including 127 (Masora
  not installed) — and any timeout mean: render nothing.**
- Budget: run with a wall-clock timeout of **2 s**; on timeout, kill and skip
  silently. The command is read-only and never blocks on git network access.

## 6. Rendering rules

- **Injection scope**: single-symbol responses (`explain`, `who_calls` /
  `what_it_calls`) spawn with the one symbol they center on; the
  multi-symbol responses `find` and `outline` inject too, with ONE batched
  spawn for all the response's result symbols (one `--symbol` flag per
  symbol, §2). On a multi-symbol response, each fact renders as
  `masora: <summary> [status] — <anchor_leaf>` when the fact's
  `anchor_leaf` is non-null — the leaf disambiguates WHICH queried symbol
  the fact answers for (a fact with a null `anchor_leaf` renders the plain
  single-symbol form); single-symbol responses are unchanged. The budget
  below is per RESPONSE, not per symbol: at most 2 facts and ≤ 60 tokens
  total across all symbols of the response — the `anchor_leaf` suffix and
  the presence hint count inside that envelope — and the
  visible-truncation rule is unchanged.
- Attach at most **2 facts** by default (the fact count is configurable — a
  `CPPGRAPH_MASORA_MAX_FACTS` value; higher is allowed), one terse line each,
  appended to the response of the symbol they anchor. Budget guidance: ≤ 60
  tokens total; when more facts match, the truncation must be visible (e.g.
  `… +3 more — masora search`), never silent. The token budget always wins
  over the fact count: when rendering the configured count would exceed it,
  render fewer facts plus the visible truncation line; at least one fact
  renders whenever any matched.
- A fact's status must surface **as such** — statuses are evidence labels,
  not decoration, and negative knowledge is as valuable as positive:

  | Value | Render as / meaning |
  |---|---|
  | `current` | the displayed version's anchors all match this checkout's fingerprints |
  | `stale` | no version matches; the newest is shown — re-check before relying on it |
  | `restored` | current again because a newer version was refuted — re-verify |
  | `none` | every version refuted — **negative knowledge**: render `masora NOT: <summary> [refuted]`, never as advice |
  | `verified(human)` | an active verify's label — always renders, no interpretation token |
  | `verified(llm)` | an active verify's label — always renders; the ONLY case where an interpretive token is added: when the fact's `effort` is `low`, render `verified(llm), low-effort` (a low-effort LLM verification is the weakest trust state a verified label can carry); `effort: medium`/`high` render nothing extra |
  | `verified(graph)` | an active verify's label — renders bare, no interpretation token: the verify's currency is the resolution axis's job (`current`/`stale`/`suspect`), not the label's |
  | `unverified` | no active verify — renders as nothing: the absence of a verify is not evidence; `verified(<source>)` always renders |
  | `suspect` | the displayed version's or its 1-hop neighbours' edge-set hash changed since the recorded snapshot |
  | `doubted` | an active doubt targets that verify — disputed, not provably wrong |
  | `pending` | events not yet merged (traveling through the `masora/<author>` pending PR) |
  | `unknown` | a provider was unavailable — shadows the resolution; never a silent pass |
  | `unanchored` | explicitly unanchored claim; the flag is its validity signal |

  Trust-rendering matrix for the verification axis (state-form, pinned):

  | Verification | `effort` | Interpretive token |
  |---|---|---|
  | `verified(human)` | any / null | none — the label always renders as-is; the `low-effort` interpretive token NEVER renders under `verified(human)` whatever the writer's effort — a human verification answers for the content, the writer's effort is secondary |
  | `verified(llm)` | `low` | `low-effort` appended as a label |
  | `verified(llm)` | `medium` \| `high` \| null | none |
  | `verified(graph)` | any / null | none — the label renders bare |
  | `unverified` | always null | renders nothing (the absence of a verify is not evidence) |

  Example lines:
  - `masora: Resume token invalidated by a shard key change [current, verified(llm)]`
  - `masora: Bring-up order: start before stop [current, verified(llm), low-effort]` (a `verified(llm)` fact with `effort: "low"` — the one interpretive token)
  - `masora: Lock L must be held before calling commitShard [stale, suspect — re-check]`
  - `masora NOT: changeStream re-opens on resumeToken == null [refuted]`
- **Render the git context when it matters — the stamps are the trigger, and
  cppgraph never computes git state.** A fact's context label renders iff ANY
  of:
  - `off_version` is `true`;
  - `established_relation` is a non-null value other than `in_line` —
    `ahead`, `out_of_line`, `unknown`, or any value this reader does not
    know (forward compatibility, below);
  - `context_ordering` is `degraded`.

  ONE exception: a fact with `resolution: "none"` renders NO context label
  from a null `established_relation` — nothing displays, so there is no
  establishment to qualify; the `NOT:` envelope already carries the
  negative knowledge. (`off_version` is always false and `degraded` cannot
  fire on a `none` lineage, so such a fact carries no context label at
  all.)

  When none fires (`in_line` + `exact` + `off_version: false` — the common
  case on merge-commit repos), no context label renders and the fact's token
  cost is the v1 cost. When it fires, the label renders ONLY what the stamps
  say, in plain words: the relation (`ahead` → "established ahead of this
  checkout"; `out_of_line` → "established on another line"; `unknown`/`null`
  → "context unproven"; `degraded` → "selection ordering degraded"), the
  short `established_commit` beside it as a pointer, and `off_version: true`
  as "off-version" (the strongest of the qualifications: the claim is not
  applicable to this checkout). Never render a branch name — the contract
  carries none — and never present the stamps as validity.

  Forward compatibility: the `established_relation` enum may gain values in
  later Masora releases. A value this reader does not recognize is inert to
  the parser (the document is accepted), still TRIGGERS the label (it is not
  `in_line`), and renders VERBATIM in the neutral template
  `context: established relation <value>` — never mapped onto a pinned
  phrase, never guessed. Update cppgraph and re-render with the learned
  phrasing.

  Worked example — an `off_version` fact (the second fact of §3's document):

  ```json
  {
    "lineage": "01J8ZP20000000000000000000",
    "summary": "Lock L must be held before calling commitShard",
    "resolution": "stale",
    "verification": "unverified",
    "flags": "suspect",
    "established_relation": "out_of_line",
    "established_commit": "9f8e7d6c5b4a",
    "off_version": true,
    "context_ordering": "exact"
  }
  ```

  cppgraph renders (one line, the context clause appended):

  ```
  masora: Lock L must be held before calling commitShard [stale, suspect — re-check]
    context: off-version — established on another line (9f8e7d6c5b4a)
  ```

  On a SQUASH-merge repo most landed facts are `out_of_line`, so the context
  label renders on most facts there — accepted: the label is one short token
  cluster (MASORA_DESIGN.md §6.2). cppgraph NEVER computes git ancestry
  itself (it cannot: `established_commit` is deliberately 12 hex chars), and
  it NEVER treats the stamps as a validity judgment — a `stale` fact with
  `established_relation: "in_line"` stays stale.
- Never turn a fact into an instruction: label + summary + status only.
- **The zero-fact rendering is DIFFERENTIATED by the counters** — Masora is
  present (the binary found, the flag on, the root resolvable, the contract
  parsed) and ZERO facts rendered, in either flavor:
  - `lineages_examined == 0` → cppgraph renders `presence_hint` VERBATIM
    (budget-checked, §6's token envelope): the exact string Masora shipped —
    masora owns the wording (including the tool names, so a tool rename is a
    masora-side change, never a cppgraph literal drift):
    `masora: present for this checkout — the masora search / explain / list_stale MCP tools recall recorded knowledge.`
  - `lineages_examined > 0` → cppgraph renders the DERIVED staleness line
    `masora: <lineages_examined> lineage(s) examined, none matched — the base may predate this rebuild.`
    — cppgraph derives it from the counters; it names NO tools.
  Either line renders at most once per response, whatever the number of
  symbols queried; both are capability/absence notices, NEVER knowledge and
  NEVER code advice — no claim, no status, no context. The zero-change
  guarantee otherwise stands: without Masora installed, with the flag off,
  with the base unresolvable, or on any non-zero exit (nothing on stdout —
  §5), nothing renders — not even a hint.

## Input hygiene (cppgraph side)

- **Reject unknown parameters** — never ignore them: a typo'd parameter name
  silently returns UNFILTERED results (the whole graph answers where one
  symbol was asked about). An unknown parameter is an explicit error naming
  it.
- **An absent path/filter target is an explicit error**, never a silent
  whole-repo broadening: a filter that matches nothing says so; it never
  degrades to "no filter".
- Strict-argument tests are required on the cppgraph side: every tool's
  parameter set is pinned (unknown names refused) and every
  absent/unmatchable filter target errors loudly.

## Non-goals (what the stamps are NOT)

- **cppgraph does not compute relations.** No git invocation, no ancestry
  derivation, no second-guessing `established_relation`: Masora evaluated it
  at index build time against the same checkout, and the short
  `established_commit` is rendered, never analyzed.
- **cppgraph does not rank with the stamps.** Facts are selected by Masora's
  fold; the context fields never reorder, filter or drop a fact, and they
  never participate in the dedup/caching key (that stays `lineage`).
- **cppgraph does not guess validity from the stamps.** The validity surface
  is the status tuple (`resolution`/`verification`/`flags`) exactly as in v1;
  the context qualifies the reading, it never gates, upgrades or downgrades
  it.

## 7. Invariants for the cppgraph side

- **Read-only consumer**: never write into a base, the config, the indexes
  directory, or anywhere else Masora owns.
- **No SQLite parsing**: the index schema is internal, version-gated and may
  change in any Masora release; the JSON contract of §3 is the only surface.
- **No Masora state assumptions**: the index is disposable and rebuilt
  atomically; a response may race a rebuild — `stale_warning` + statuses are
  the truth of the moment, do not cache facts across repo HEAD changes.
- **Zero-change guarantee** (SPEC.md line 19): any failure mode — missing
  binary, non-zero exit, timeout, unparsable output, unknown
  `contract_version` — degrades to "no injection", never to an error surfaced
  to the user. ONE sanctioned exception, the contract-version
  `mismatch_advisory`: on a recognized major-version mismatch — a NEWER
  `contract_version` this reader does not support, or an OLDER one this
  reader has retired — cppgraph may emit one visible advisory line next to
  its empty injection, telling the user which side to update
  (`masora: [facts contract v3 unsupported — update cppgraph]` /
  `masora: [facts contract v1 — update masora]`); silence is still kept for
  unparsable JSON and for an absent or boolean version, where there is
  nothing to diagnose. The advisory states a VERSION mismatch only — it
  never diagnoses content, never injects facts.
- **Token discipline**: ≤ 60 tokens per response, at most 2 facts, cap
  reported (§6).
- **Malformed facts fail closed**: a document containing any shape violation
  (non-dict fact, non-string field) is treated as unparsable, no injection at
  all; partial delivery is deliberately wrong because silently dropping a
  malformed fact could hide negative knowledge.

## 8. cppgraph-side rollout checklist

An explicit opt-out env var, `CPPGRAPH_MASORA=0` (or `=off`), fully disables
injection; it is checked before any spawn. The injection ships feature-flagged
off until validated (item 1 below), so the opt-out is the user-facing off
switch once the feature flag is turned on.

1. Feature-flag the injection (default off until validated).
2. Register the call where responses are built: after a query touches symbol
   S, spawn `masora facts --repo <root> --symbol <S>` with the §5 budget.
   Injection scope covers `explain`, `who_calls`/`what_it_calls`
   (single-symbol responses) and `find`/`outline` (multi-symbol responses:
   ONE batched spawn, one `--symbol` flag per result symbol, §6). Extending
   it to the remaining symbol-bearing queries (`impact`, `references`,
   `path`) is a deliberate later decision, not part of the first
   integration.
3. Render per §6 (status labels AND the context rule); assert the
   ≤ 2-facts / ≤ 60-token budget in a test.
4. Test with (a) a repo with a configured base and a fresh index, (b) a repo
   with a stale index (`stale_warning: true`), (c) a repo with no Masora
   config (silent skip), (d) Masora absent from PATH (silent skip), (e) a
   killed/timed-out subprocess (silent skip), (f) an `off_version` fact (the
   §6 worked example's context clause renders).
5. Confirm the zero-change guarantee: without Masora, byte-identical cppgraph
   responses and timing within noise.
6. Report contract friction back to the Masora repo — shape changes land as a
   new major `contract_version`, never in place.

## The symbol identity format is versioned (store meta row `symbol_format`)

Anchor identities are load-bearing across repos and rebuilds: masora embeds
them verbatim into the base's event files (which persist for years), and
re-fingerprinting matches them verbatim against `symbols.symbol` in the graph
store. The exact shape of those strings (the decorated
`cxx . . $ mongo/...#method(hash).` form) is therefore a CONTRACT, not an
internal detail, and it is versioned exactly like the store schema:

- cppgraph writes an integer meta row `symbol_format` into the store at build
  time (monotone: every change to the symbol identity format bumps it).
- masora's reader gates on it exactly like the store `schema_version`:
  - **absent** → legacy store, accepted (it carries format 1 — every store
    predating the row reads as format 1, so existing graphs keep working);
  - **present and == masora's learned constant** (format 1) → accepted;
  - **present but unparsable, or any other value** → the store is refused
    with a reason naming the seen value, the expected format, the
    newer/older direction, and the re-index remedy; code anchors report
    `unknown` (the `W-IDX-GRAPH` path), nothing is guessed.

**Governance rule**: changing the symbol identity format without bumping
`symbol_format` in the SAME change is a cppgraph bug — the format version and
the format move together. A silent format drift would let reads succeed while
old anchors silently mismatch, which is exactly what the gate exists to
prevent.

## 9. cppgraph-side requirements — self-check inventory

The checklist of everything the cppgraph side must have implemented, written
to be DIFFED against its own code: each item names the requirement and how to
verify it (a behavior or a test shape). An unchecked item is missing work.

| # | Requirement | How to verify |
|---|---|---|
| 1 | Injection scope: `explain`/`who_calls`/`what_it_calls` only (the MCP `masora` field + the CLI printed lines) | A test per covered tool asserting the field/lines; a test per uncovered tool asserting their absence |
| 2 | Detection: the masora binary on PATH (`shutil.which`); absent = instant silent skip, no spawn attempted | Remove masora from PATH in a test; assert byte-identical output and no subprocess spawned |
| 3 | The flag: `CPPGRAPH_MASORA` — unset/`0`/`false` = OFF (the default until validated), `1`/`true` = ON; checked before any spawn | Parametrized flag tests (unset/`0`/`false`/`1`/`true`); a spawn-count assert on the OFF cases |
| 4 | The spawn: `masora facts --repo <root> --symbol <S>`; a 2 s wall-clock timeout; the child's stdin DETACHED (MCP stdio-transport protection); the process TREE killed on timeout; an stdout cap (overflow = unparsable); any failure = no injection, never an error | A timeout test with a hanging child (assert the tree is gone after); a >cap-output test (unparsable, skipped); every failure mode asserts "no injection, no error" |
| 5 | The parser: `contract_version` 2 as a strict integer (bool rejected); fail-closed per-fact shape validation (a wrong type rejects the WHOLE document); the v2 context fields (`established_relation`/`established_commit`/`off_version`/`context_ordering`) REQUIRED — a fact missing one is a shape violation; enum values per §3 with unknown values inert; `summary` ≤ 120 + printable | Table-driven parser tests: a bool `contract_version`, one wrong-typed field in an otherwise-good document (whole-document rejection), a fact missing `established_relation` (rejected), an unknown `established_relation`/`effort`/`source` (inert), a 121-char summary |
| 6 | Rendering: ≤ 2 facts, ≤ 60 tokens (CJK-aware estimate); the visible truncation line; at least one fact renders; statuses as labels (resolution, `verified(<source>)` bare, flags); the interpretive token ONLY for `verified(llm)` at `effort: low`; never under `verified(human)`/`verified(graph)`/`unverified`; the `NOT:` envelope for resolution `none`; the CONTEXT label iff `off_version` or `established_relation` ≠ `in_line` (incl. `unknown`/null) or `context_ordering: degraded` — rendered from the stamps only, never computed, never as validity; the stale-index note only alongside facts; duplicate lineage ids deduped; no caching across responses | The §6 trust-matrix tests (every row); the context-rule tests (fires per trigger: an `off_version` fact, an `ahead`/`out_of_line`/`unknown`/null relation, a `degraded` ordering; silent for `in_line`+`exact`+false); a >budget-facts test (truncation visible); a CJK-summary token estimate; a repeat-query test (no cached second render) |
| 7 | `repo_root`: the store's recorded project root; a recorded-but-missing root SKIPS injection (never facts for the wrong checkout); legacy no-root graphs fall back to the cwd | A test with a store whose recorded root is deleted (skip asserted); a legacy store without the root (cwd fallback asserted) |
| 8 | **PENDING ON THE CPPGRAPH SIDE (implement next — not yet evidenced there):** (a) INPUT HYGIENE — unknown parameters REJECTED, never silently ignored (the typo'd-param class silently returns unfiltered results); an absent path/filter target = an EXPLICIT error, never a silent whole-repo broadening; strict-argument tests proving both; (b) the CONFIGURABLE FACT COUNT — `CPPGRAPH_MASORA_MAX_FACTS` (default 2, higher allowed; the ≤ 60-token guidance stands; a cap reported visibly per the existing rule) | (a) a test per tool passing an unknown parameter (error, not unfiltered output) and an unmatchable filter (explicit error); (b) a test rendering with `CPPGRAPH_MASORA_MAX_FACTS=3` (three facts within the token budget; the cap visible when more match) |
| 9 | The read-only invariants: never parse Masora's SQLite, never write anywhere Masora owns, never locate bases (only `--repo`) | A code-review item + a test asserting no file writes under `~/.local/share/masora` / `~/.config/masora` during an injection |
| 10 | Multi-symbol spawn: `find`/`outline` inject with ONE batched `masora facts` spawn carrying all result symbols (`--symbol` repeated); OR-matching per §2; `anchors_matched` per lineage; the ≤ 2-fact / ≤ 60-token budget is per RESPONSE and the truncation line stays visible | A test per covered tool asserting a single subprocess for a multi-symbol response (spawn-count assert) and that facts from different lineages of the batched symbols all render; a test that two symbols anchoring the SAME lineage render one fact once; a >budget-facts test showing the visible truncation |
| 11 | The presence hint: when Masora is present and ZERO facts rendered for the response, exactly one capability line renders (§6 wording), at most once per response, never as knowledge or advice | A test asserting the hint renders once on a zero-fact response (masora present, flag on); a test per absent-mode (no binary, flag off, base unresolvable) asserting NO hint renders |
| 12 | The build writes `symbol_format` into the store meta (the symbol identity format is versioned like the schema — see the identity section above) | A freshly built store's meta carries the `symbol_format` row; a format change and its `symbol_format` bump land in the same commit |
| 13 | The v3 surface: `contract_version` emitted as strict integer `3`; the counters (`lineages_examined` / `lineages_matched`) present on the document and `lineages_matched == len(facts)`; `presence_hint` carried (non-null exactly when zero facts AND zero examined); per-fact `anchor_leaf` present, non-null only with `--symbol` passed, rendered as the `— <anchor_leaf>` suffix on multi-symbol responses (§6); the zero-fact rendering differentiated (hint verbatim at 0 examined, the derived no-tools staleness line above 0); the hint/leaf tokens inside the ≤ 2-facts / ≤ 60-token envelope | A parser test pinning `contract_version == 3` (bool rejected); a document test asserting both counters and `presence_hint is null` on a fact-bearing response, the exact hint string on an empty base, the derived line (no tool names) on a filtered no-match query; an `anchor_leaf` test per derivation case (`#` + hash, no `#`, trailing dot, first-of-several in call order, null without `--symbol`); a budget test with leaf suffixes and a hint inside 60 tokens |
