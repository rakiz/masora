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
   set against `origin/main` by event id (append-only enforcement) and
   validates the merged result; without `--yes` it stops there and prints the
   pending set (plan, exit 3), with `--yes` it commits the pending set on the
   `masora/<author>` branch (the author slug derives from the base clone's git `user.name`), pushes and opens or updates that author's single PR.
4. **Merge** — a human reviews the PR (the recorded evidence is in the diff)
   and merges into `main`.
5. **Recall** — later sessions query the base: `masora mcp` serves the write
   and recall tools (`note`, `verify`, `doubt`, `undoubt`, `refute`, `search`,
   `explain`, `list_stale`) over MCP stdio, and `masora search [<base-dir>]
   <query>` reads the index from the CLI — matching summaries, statements
   and each claim's `questions`/`keywords` (the matched lines are shown on
   the hit, and every hit group ends with the `masora explain` pointer);
   the `'*'` query enumerates every indexed lineage. Without cppgraph,
   `--symbol <name>` (CLI) / the search tool's `symbol` field (MCP) finds the
   claims anchored to a symbol by its recorded anchor identity (the SCIP
   symbol string for code anchors) — exact match first, substring fallback.

## Quick start

Requires Python ≥ 3.13.

```sh
uv tool install .        # or: pip install .
masora init <base-dir> --name "<team>" [--code-remote <url>]...  # create a NEW base locally: git repo + base.toml + first commit
masora setup --base <url>[#<path>]  # clone a base + write ~/.config/masora/config.toml from its base.toml
masora check <base-dir>  # validate a base (exit 0/1/2) — in a checkout registered with `masora setup`, the base directory may be omitted (every base-taking command resolves it from the configuration)
masora compact <base-dir>  # drop pure history per lineage, fold-verified; --rehome migrates old directory layouts (plan exits 3; --yes executes)
masora sync              # plan the publication of pending events (exit 3); add --yes to publish: one branch + one PR
masora explain <base-dir> <lineage-ulid>  # the complete story of ONE lineage, statuses included
masora mcp               # run the MCP stdio server — register it in your MCP client's config
masora skill install     # install the agent rules into your skills mechanism (Claude Code, opencode)
masora hook install      # install the SessionStart freshness hook (background pull + re-index, silent failure)
masora status            # one screen: tool versions, your bases, index drift, update check
```

Team-life extras: each writer publishes on its own `masora/<author>` pending
branch; a conflicted `deleted.toml` after concurrent gc PRs is rescued with
`masora union <base-dir>` (row-union merge — review and commit yourself); and
the base repo gets CI with `masora ci print` copied into its
`.github/workflows/`.

`sync` is plan-then-confirm: without `--yes` it runs the full gate pipeline
(local check, diff vs `origin/main`, stacked audit, merged-result validation),
prints the pending set and exits 3 — nothing is written.

- `masora sync --yes` — publish the pending set: one branch + one PR.
- `masora sync --push --yes` — solo base: push the merged result directly to
  `origin/main` instead of a pending branch and PR (`--push` alone only
  plans the push).
- `masora sync --only <ulid> [<ulid>…]` / `masora sync --exclude <ulid> [<ulid>…]` —
  publish a SUBSET of the pending events: full ULIDs or unique prefixes (an
  ambiguous or unmatched selector is refused with the candidates); `--only` and
  `--exclude` are mutually exclusive; deletions already decided by gc
  (tombstones + removed files) are not filterable and always ride the sync.
- `masora sync --drop --yes` — discard the pending set: close the PR (if
  `gh` is available), delete the `masora/<author>` branch locally and
  remotely; the local `.md` files of dropped events are left in place for
  you to remove (`--drop` without `--yes` only plans the discard).

## Status

`masora status [--force]` prints one readable screen and always exits 0 — it
never fails hard: an offline release check is a quiet one-liner, a missing
clone or unreadable config is reported as-is. It shows the installed tool
version (with the supported `format_version`, the facts `contract_version`
and the index `schema_version`), every configured base from your config
(clone path with exists/missing, the clone's `origin` remote, event and
tombstone counts, and per index database the repo it was built for plus the
staleness reason, or `no index`), and the update check: the latest release
from the GitHub API compared numerically against the installed version —
`up to date` or `update available: vX.Y.Z` with the install hint. The check
is cached in `~/.local/share/masora/update-check.json` (or
`$MASORA_HOME/update-check.json`) for 24 hours; `--force` refetches now.
`masora --version` prints just the version.

A base is a git repo whose `main` branch holds event files laid out per
FORMAT.md §1, plus a `base.toml` (`name` + the `code_remotes` it serves) at
its root; `masora setup --base <url>[#<path>]` clones it into
`~/.local/share/masora/bases/` and writes the local config — the base URL
travels through the team's onboarding docs, nothing ever lives in the code
repo.

To create a new base, run `masora init <base-dir> --name "<name>"` (add one
`--code-remote <url>` per code repo the base will serve): it makes the
directory a git repo on `main`, writes `base.toml` and commits it, then prints
the exact `masora setup --base <path>` command to register it locally.
Publishing the base to a shared repo is ordinary git work (`git push`); once
the URL exists, teammates onboard with `masora setup --base <url>`.

## Agent instructions

A base only changes agent behaviour if the agent consults it. Two routes,
same rules:

- **The installable skill** — the rules ship inside the package:
  `masora skill install` writes `SKILL.md` into every detected agent
  framework's skills dir (`~/.claude`, `~/.config/opencode`; other
  frameworks are skipped silently, re-running updates) and, for opencode,
  installs the `/masora` slash command into `~/.config/opencode/commands/`
  (Claude Code already surfaces the skill as a slash command, so it gets
  no command file); `masora skill print`
  pipes the content for any other mechanism. Its rules are conditional — the
  ritual tries `search` when the tools are available and continues normally
  when they are not.
- **The paste block** — [docs/AGENT_INSTRUCTIONS.md](docs/AGENT_INSTRUCTIONS.md)
  into that project's `AGENTS.md` (or rules file), for agents without a
  skills mechanism.

Both cover what the MCP tools are, when to `note`, how to `verify`, and
search before investigating. Instructions are the third injection channel
(MASORA_DESIGN.md §10.1) — useful but often forgotten, never the only
mechanism; the cppgraph injection and the agent hooks are the other two.

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
  `E-SETUP-*` codes only appear in `setup`; the `E-INIT-*` codes only appear
  in `init`; `E-GC-ULID`, `E-GC-UNKNOWN` and
  `E-GC-CHECK` only appear in `gc`; `E-COMPACT-DIVERGE` and `E-COMPACT-CHECK`
  only appear in `compact`.

Every code, with likely cause and remedy, is in
[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md). The table is kept in
sync with `masora/diagnostics.py` by `tests/test_docs.py`.

## Documentation

- [FORMAT.md](FORMAT.md) — the canonical event-file contract; `masora check`
  implements exactly this.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how the code maps onto the
  contract (canonicalization, fold, checker, sync).
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) — diagnostic codes.
- [docs/REFOUNDATION.md](docs/REFOUNDATION.md) — the runbook for accepting a
  remote history rewrite (`masora reset --from-origin`, explicit confirmation only).
- [docs/AGENT_INSTRUCTIONS.md](docs/AGENT_INSTRUCTIONS.md) — the rules an
  adopting project pastes into its AGENTS.md.
- [docs/EVALUATION.md](docs/EVALUATION.md) — the pre-registered protocol for
  judging whether Masora changes agent behaviour.
- [SPEC.md](SPEC.md) — stable requirements (goals, non-goals, constraints).
- [MASORA_DESIGN.md](MASORA_DESIGN.md) — design rationale and settled
  decisions.
- [TODO.md](TODO.md) — roadmap (what is built, what comes next).
- [AGENTS.md](AGENTS.md) — read-order and invariants for AI sessions working
  in this repository.
