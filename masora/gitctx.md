# gitctx.py — the git relation adapter

Role: computes the per-version git context B(v) (MASORA_DESIGN.md §6.2) at
index build time and hands it to the fold through
`resolve_lineage(contexts=…)`. It is the ONLY component that runs git
ancestry probes; `fold.py` stays pure and `check`/the format know nothing of
git. It also owns the counterfactual `context_ordering` decision
(`exact` | `degraded`) for a lineage.

## Interface

- `asking_line(repo) -> AskingLine` — resolves, with three local git reads
  and NO fetch: the asking `head`, the current `branch`, the branch's
  `upstream` commit as present locally (`git rev-parse --verify
  <branch>@{upstream}`) and the `shallow` flag. Detached HEAD → no branch, no
  upstream.
- `RelationProber(repo, line, budget=PROBE_BUDGET)` — memoized, budgeted
  `git merge-base --is-ancestor` probes (`Answer`: YES / NO / FAILED /
  BLOCKED). ONE prober per index build: the memo and the budget are shared
  across lineages. `probe_count` exposes the git spawns (memoization
  evidence).
- `RelationProber.lineage_contexts(establishing)` — the per-version context
  of ONE lineage; `establishing` maps version ULID → the claim's
  `recorded_at.commit` (None = unprovable). Tier-1 versions additionally get
  the `ancestors` maxima input, computed from pairwise probes among the
  lineage's own tier-1 candidates.
- `context_ordering(lineage, events, activity, eligible, outcomes, contexts)`
  — the counterfactual `degraded` test over the pure fold.

## The relation decision table (exact)

Let C be the version's establishing commit, H the asking HEAD, U the
upstream commit. Probes are `is_ancestor(a, b)`.

| Condition | Relation |
|---|---|
| C missing / H missing / repo shallow | `None` (unprovable) |
| `is_ancestor(C, H)` BLOCKED or FAILED | `None` (unprovable — nothing proven) |
| `is_ancestor(C, H)` YES | `in_line` (HEAD-equal included) |
| upstream missing (detached HEAD / no branch / no upstream) | `out_of_line` (structural: no ahead is provable — not a probe failure) |
| `is_ancestor(H, C)` BLOCKED | `None` (the budget blocked it) |
| `is_ancestor(H, C)` FAILED | `relation_unknown` (probes ran; not-in_line is proven; descent open) |
| `is_ancestor(H, C)` NO | `out_of_line` (not a proper descendant) |
| `is_ancestor(C, U)` BLOCKED | `None` (the budget blocked it) |
| `is_ancestor(C, U)` FAILED | `relation_unknown` (not-in_line + proper descent proven; ahead open) |
| `is_ancestor(C, U)` YES | `ahead` |
| `is_ancestor(C, U)` NO | `out_of_line` |

`ahead` requires a PROPER descendant of H: when `is_ancestor(C, H)` answered
NO, C ≠ H is implied, so `is_ancestor(H, C)` YES means proper descent.
A shallow clone makes every negative answer untrustworthy (the ancestry path
can be cut off at the shallow boundary), so nothing is probed there: every
version is unprovable and the lineage shows up `degraded` when it matters.

## The degraded decision procedure

`degraded` iff some version's context is unprovable (`relation == None`;
`relation_unknown` does NOT count — its not-in_line knowledge is proven) AND
hypothetically setting that version's relation to `in_line`, `ahead` or
`out_of_line` (no ancestry edges — the strongest hypothesis: a tier-1
maximum) changes the fold's observable result `(displayed, restored,
resolution)`. `off-version` is out of scope (its guard needs a PROVABLE
relation); the `out_of_line` hypothetical is observable-neutral in the
current fold (tier 2 is ranked by ULID regardless of the exact tier-2 label)
and is kept so the test stays correct if the fold ever distinguishes tier-2
kinds.

## Invariants

- NO implicit fetch, no network — the local object store only.
- Probes are memoized per ORDERED sha pair; a repeated question spawns git
  once per build.
- ONE shared budget per build (`PROBE_BUDGET`, 1024 spawns); lineages are
  processed in ascending lineage-id (ULID) order, versions in ascending ULID
  order, ancestry pairs in sorted order — the budget is deterministic, and
  adding an unrelated lineage never changes an earlier lineage's result
  within the budget.
- Exhausted budget ⇒ the remaining versions are `unprovable` (their contexts
  become None); a blocked or failed PAIRWISE probe among tier-1 candidates is
  INCOMPARABLE (no ancestry edge — it never demotes a proven relation).
- Failed probes are memoized as FAILED for the build (fail-closed; a fresh
  build retries).

## Pitfalls

- The establishing commit is the claim event's `recorded_at.commit` — a
  code-repo SHA. Probes must run against the CODE checkout (`--repo`), not
  the base directory: the base is a different git repo and never contains
  the code objects.
- `Answer.FAILED` (git exit ∉ {0, 1}) is NOT a "no": reading it as one would
  fabricate `out_of_line` from a missing object.
- `relation_unknown` vs `None`: both rank tier 2 in the fold, but only `None`
  feeds the degraded counterfactual. Do not merge them.
- The context ordering of `explain` (fresh budget, live re-resolution) is a
  later stage — the index stores the build-time verdict only.
