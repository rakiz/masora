# Masora

Masora is a git-backed, append-only knowledge base of claims anchored to code
symbols, with a verification lifecycle and self-invalidation. Knowledge lives
in a Masora *base* — a git repository of small `.md` event files kept beside
the code, never inside it: code is never edited to attach knowledge. Each
claim carries anchors (SCIP symbol identities with fingerprints), provenance
(`human` | `llm` | `graph`) and either recorded proof or an
explicit `unverified`/`unanchored` status. Later events verify, doubt, refute
and un-refute it without any existing file ever being modified — a refuted
claim stays on disk as negative knowledge.

It is not a free-text scratchpad (MASORA_DESIGN.md §2): no claim without
anchor + provenance + proof or an explicitly declared `unanchored`.

## Why the name

The Masoretes were Jewish scribes (roughly 7th–10th c.) who transmitted the
Hebrew Bible across centuries of copies made by people who err. Their method
is Masora's design: notes anchored in the margin (knowledge attached to a
precise word — our symbol anchors), checksums before their time (counts and
middle letters — our fingerprints), and never editing the text: a divergent
reading was written in the margin. Masora writes events beside the code and
leaves the code untouched.

## Event lifecycle

1. **Write** event `.md` files locally in the base, following FORMAT.md §5
   (`claim`, `verify`, `doubt`, `undoubt`, `refute`, `unrefute`) — append-only,
   never edited after creation.
2. **`masora check <base-dir>`** — validates the whole tree against
   FORMAT.md §7: per-kind schemas, YAML canonicalization, cross-file
   references, cycles, tombstones, and the fold that computes each claim's
   status envelope. Exit 0 clean, 1 errors, 2 warnings only.
3. **`masora sync`** — publication gate: re-runs the check, diffs the pending
   set against `origin/main` by event id (append-only enforcement), validates
   the merged result, then commits it on the `masora/pending` branch, pushes
   and opens or updates the single PR.
4. **Merge** — a human reviews the PR (the recorded evidence is in the diff)
   and merges into `main`.
5. **Recall** — later sessions query the base: `masora mcp` serves the write
   and recall tools (`note`, `verify`, `doubt`, `undoubt`, `refute`, `search`,
   `list_stale`) over MCP stdio, and `masora search <base-dir> <query>` reads
   the index from the CLI.

## Quick start

Requires Python ≥ 3.13.

```sh
uv tool install .        # or: pip install .
masora setup --base <url>[#<path>]  # clone a base + write ~/.config/masora/config.toml from its base.toml
masora check <base-dir>  # validate a base (exit 0/1/2)
masora sync              # publish pending events: one branch + one PR
masora mcp               # run the MCP stdio server — register it in your MCP client's config
```

`sync` variants:

- `masora sync --push` — solo base: push the merged result directly to
  `origin/main` instead of a pending branch and PR.
- `masora sync --drop` — discard the pending set: close the PR (if `gh` is
  available), delete the `masora/pending` branch locally and remotely; the
  local `.md` files of dropped events are left in place for you to remove.

A base is a git repo whose `main` branch holds event files laid out per
FORMAT.md §1, plus a `base.toml` (`name` + the `code_remotes` it serves) at
its root; `masora setup --base <url>[#<path>]` clones it into
`~/.local/share/masora/bases/` and writes the local config — the base URL
travels through the team's onboarding docs, nothing ever lives in the code
repo.

## Diagnostics

- `E-*` codes are errors: `check`/`sync`/`gc` fail (exit 1) and nothing is
  published or deleted.
- `W-*` codes are warnings: never blocking, exit 2. They mark tolerated
  shapes — dangling targets across PRs (`W-DANGLING`), clock skew
  (`W-SKEW`), a version missing its founder (`W-FOUNDER`), proof replay not
  wired in standalone check (`W-REPLAY`), deleting a still-active lineage
  (`W-GC-ACTIVE`).
- `E-CANON-*` are the YAML canonicalization rules (FORMAT.md §4);
  `E-REWRITE`, `E-FOUNDER`, `E-GC-UNAVAILABLE`, `E-TOMBSTONE-SHRINK`,
  `E-GIT`, `E-NO-ORIGIN`, `E-MERGE-BASE` only appear in `sync`; the
  `E-SETUP-*` codes only appear in `setup`; `E-GC-ULID`, `E-GC-UNKNOWN` and
  `E-GC-CHECK` only appear in `gc`.

Every code, with likely cause and remedy, is in
[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md). The table is kept in
sync with `masora/diagnostics.py` by `tests/test_docs.py`.

## Documentation

- [FORMAT.md](FORMAT.md) — the canonical event-file contract; `masora check`
  implements exactly this.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how the code maps onto the
  contract (canonicalization, fold, checker, sync).
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) — diagnostic codes.
- [SPEC.md](SPEC.md) — stable requirements (goals, non-goals, constraints).
- [MASORA_DESIGN.md](MASORA_DESIGN.md) — design rationale and settled
  decisions.
- [TODO.md](TODO.md) — roadmap (what is built, what comes next).
- [AGENTS.md](AGENTS.md) — read-order and invariants for AI sessions working
  in this repository.
