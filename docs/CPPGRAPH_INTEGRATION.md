# cppgraph ⇄ Masora injection contract

Handoff document for implementing Masora fact injection inside **cppgraph**.
Written from the Masora side; everything cppgraph codes against is pinned
here. Status: the contract is final, the Masora-side command
(`masora facts`) is **delivery pending** — tracked in Masora's TODO.md.

## 1. Context

Masora is a git-backed, append-only knowledge base of claims anchored to code
symbols: each claim lives as a small `.md` event file in a *base* (a separate
git repo), and a disposable per-checkout SQLite index recomputes each claim's
status (resolution, verification, flags) from anchor fingerprints. Masora
never touches the code repo. The integration contract (SPEC.md line 19,
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
masora facts --repo <path> [--symbol <scip-string>]
```

- `--repo` — path to the code checkout being looked at (required; usually the
  repo root cppgraph was run on).
- `--symbol` — optional exact SCIP symbol string. When given, only lineages
  whose displayed version anchors on that identity are returned (matched
  verbatim — the same rule Masora's provider uses); for lineages with
  `resolution: "none"` (every version refuted) matching uses the newest
  version, since the displayed version is null. Without it, all lineages
  of the matching base(s) are returned.

Output: a single JSON document on stdout (one line, but parse it as a
document, not as a line protocol). The command is Masora-side and **delivery
pending**; cppgraph should code against the shape of §3 only — never against
Masora's SQLite schema (§7).

## 3. Output contract — version 1

```json
{
  "contract_version": 1,
  "repo_head": "1a1a8e1f4e5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c",
  "graph_commit": "0e5f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f",
  "stale_warning": false,
  "facts": [
    {
      "lineage": "01J8Z3K0000000000000000000",
      "summary": "Resume token invalidated by a shard key change",
      "resolution": "current",
      "verification": "verified(llm)",
      "flags": "-",
      "anchors_matched": [
        "scip-clang cxx . . mongo/ResumeTokenData#makeResumeToken()."
      ]
    },
    {
      "lineage": "01J8ZP20000000000000000000",
      "summary": "Lock L must be held before calling commitShard",
      "resolution": "stale",
      "verification": "unverified",
      "flags": "suspect",
      "anchors_matched": [
        "scip-clang cxx . . mongo/Engine#commitShard()."
      ]
    },
    {
      "lineage": "01JB1R00000000000000000000",
      "summary": "changeStream re-opens on resumeToken == null",
      "resolution": "none",
      "verification": "unverified",
      "flags": "-",
      "anchors_matched": ["scip-clang cxx . . mongo/Util#tick()."]
    }
  ]
}
```

Field semantics:

| Field | Meaning |
|---|---|
| `contract_version` | integer `1`; bump = breaking change to this shape — cppgraph rejects unknown major versions and renders nothing |
| `repo_head` | code repo HEAD the statuses were resolved against, or `null` (not a git checkout) |
| `graph_commit` | cppgraph-indexed commit that served the code fingerprints, or `null` (no usable graph store) |
| `stale_warning` | `true` when the base or code state moved since the index was built (statuses may be outdated); `false` current; `null` when not comparable |
| `facts` | zero or more facts, one per matching lineage; may be empty |
| `facts[].lineage` | lineage id — stable across versions; use it for dedup/caching |
| `facts[].summary` | one line, ≤ 120 chars — rendered verbatim |
| `facts[].resolution` | `current` \| `stale` \| `restored` \| `none` \| `unknown` (§6); `unknown` = provider unavailable, shadows the resolution |
| `facts[].verification` | `verified(<actor>)` with actor `human` \| `llm`, or `unverified` |
| `facts[].flags` | comma-joined subset of `suspect,doubted,pending,unknown,unanchored`, or `-` when none |
| `facts[].anchors_matched` | the displayed version's anchor identities the query matched; for `resolution: "none"` they come from the newest version (displayed version is null); empty when no `--symbol` was passed |

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
     HEAD, repo HEAD or the graph's indexed commit moved since the build).
  2. **graph unavailable for fingerprints** → the affected lineages carry the
     `unknown` flag (Masora's `W-IDX-GRAPH` semantics: an anchor provider was
     unavailable, so `unknown` shadows the resolution instead of a guessed
     status). The shape does not change.
- **non-zero (1)** — hard failure: no base resolved, unreadable config, or an
  unusable index that could not be rebuilt. stdout carries no contract
  document. **Any non-zero exit — including 127 (Masora not installed) — and
  any timeout mean: render nothing.**
- Budget: run with a wall-clock timeout of **2 s**; on timeout, kill and skip
  silently. The command is read-only and never blocks on git network access.

## 6. Rendering rules

- Attach at most **2 facts**, one terse line each, appended to the response of
  the symbol they anchor. Suggested budget: ≤ 60 tokens total; when more
  facts match, the truncation must be visible (e.g. `… +3 more — masora
  search`), never silent.
- A fact's status must surface **as such** — statuses are evidence labels,
  not decoration, and negative knowledge is as valuable as positive:

  | Value | Render as / meaning |
  |---|---|
  | `current` | the displayed version's anchors all match this checkout's fingerprints |
  | `stale` | no version matches; the newest is shown — re-check before relying on it |
  | `restored` | current again because a newer version was refuted — re-verify |
  | `none` | every version refuted — **negative knowledge**: render `masora NOT: <summary> [refuted]`, never as advice |
  | `verified(<actor>)` | newest active verify's actor (`human`/`llm`) |
  | `unverified` | no active verify |
  | `suspect` | the displayed version's or its 1-hop neighbours' edge-set hash changed since the recorded snapshot |
  | `doubted` | an active doubt targets that verify — disputed, not provably wrong |
  | `pending` | events not yet merged (traveling through the `masora/pending` PR) |
  | `unknown` | a provider was unavailable — shadows the resolution; never a silent pass |
  | `unanchored` | explicitly unanchored claim; the flag is its validity signal |

  Example lines:
  - `masora: Resume token invalidated by a shard key change [current, verified(llm)]`
  - `masora: Lock L must be held before calling commitShard [stale, suspect — re-check]`
  - `masora NOT: changeStream re-opens on resumeToken == null [refuted]`
- Never turn a fact into an instruction: label + summary + status only.

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
  to the user.
- **Token discipline**: ≤ 60 tokens per response, at most 2 facts, cap
  reported (§6).

## 8. When `masora facts` ships — checklist

1. Feature-flag the injection (default off until validated).
2. Register the call where responses are built: after a query touches symbol
   S, spawn `masora facts --repo <root> --symbol <S>` with the §5 budget.
3. Render per §6; assert the ≤ 2-facts / ≤ 60-token budget in a test.
4. Test with (a) a repo with a configured base and a fresh index, (b) a repo
   with a stale index (`stale_warning: true`), (c) a repo with no Masora
   config (silent skip), (d) Masora absent from PATH (silent skip), (e) a
   killed/timed-out subprocess (silent skip).
5. Confirm the zero-change guarantee: without Masora, byte-identical cppgraph
   responses and timing within noise.
6. Report contract friction back to the Masora repo — the shape bumps via
   `contract_version`, never in place.
