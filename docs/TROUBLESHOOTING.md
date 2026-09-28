# Troubleshooting

Every diagnostic code exported by `masora/diagnostics.py`, in that file's
order. `masora check` reports codes from the standalone whole-tree validation
(FORMAT.md §7); codes marked *sync* appear only during `masora sync`
publication. This table is kept in sync with the code by
`tests/test_docs.py` — a new code must land here in the same change.

| Code | Meaning | Likely cause | Remedy |
|---|---|---|---|
| `E-FRONTMATTER` | Frontmatter block is missing, unterminated, empty, or not a mapping (FORMAT.md §2) | File starts with something else than `---`, or the closing `---` is absent | Wrap the YAML in `---` … `---`; keep it a non-empty mapping |
| `E-YAML` | Frontmatter is not valid YAML, or the file is not valid UTF-8 | Syntax error; encoding issue | Fix the YAML; re-save the file as UTF-8 |
| `E-CANON-FLOW` | Flow-style YAML (`{…}`, `[…]`) (FORMAT.md §4) | Hand-written compact YAML | Rewrite in block style |
| `E-CANON-DUPKEY` | Duplicate key in a mapping (FORMAT.md §4) | Same field written twice | Remove one occurrence |
| `E-CANON-ALIAS` | YAML anchors or aliases (`&x`, `*x`) (FORMAT.md §4) | Values reused via aliasing | Inline the value literally |
| `E-CANON-TAG` | Explicit, custom or merge tag (`!!t`, `<<:`) (FORMAT.md §4) | Tagged/merged YAML | Remove the tag; write values literally |
| `E-CANON-QUOTE` | An identity, hash, SHA or ULID value (or an identity key in `snapshots`/`neighbours`) is unquoted (FORMAT.md §4) | Bare scalar like `id: 01J8…` | Quote the value: `id: "01J8…"` |
| `E-CANON-KEY` | Mapping key is not a plain scalar field name (FORMAT.md §4) | Quoted field names (`"id": …`) or non-string keys | Write keys plain and unquoted (identity keys are the quoted exception) |
| `E-ULID` | A ULID field or filename ULID is malformed (FORMAT.md §3) | Not 26 uppercase Crockford-base32 chars, or first char > `7` | Use canonical uppercase 26-char ULIDs |
| `E-FILENAME` | Filename not `<ULID>.<kind>.md`, or frontmatter `id`/`kind` disagrees with the filename (FORMAT.md §7.1) | Renamed file; copy-pasted frontmatter | Align the filename ULID and kind with the frontmatter |
| `E-SCHEMA` | Frontmatter violates the per-kind schema (FORMAT.md §4) | Unknown, forbidden or missing field; wrong type; broken cross-field rule (e.g. `contradicts` without `reason`) | Compare against the per-kind table and templates (FORMAT.md §4–§5) |
| `E-VERSION` | `format_version` missing, non-integer, or unsupported (FORMAT.md §7.3) | Wrong or missing `format_version` | Set `format_version: 1` |
| `E-TIMESTAMP` | Timestamp is not `{commit, graph_commit}` with full 40-hex SHAs; `graph_commit` mandatory-but-null with code anchors/snapshots (FORMAT.md §4) | Truncated SHA; code anchor recorded without `graph_commit` | Record full 40-hex SHAs; include `graph_commit` when code anchors or snapshots are present |
| `E-ANCHOR` | Anchor/snapshot shape violation (FORMAT.md §4, §5.2) | Duplicate anchor identities; snapshot keys ≠ the target claim's anchor set; `unanchored`/`anchors` mismatch; bad hex; missing code snapshot | Fix per the templates; a verify's `snapshots` must cover exactly the target's anchor identities |
| `E-PROOFQUERY` | `proof_query` malformed (FORMAT.md §4) | `class: structural` without one (or semantic with one); unknown tool prefix; free-text `expect` | Use `{tool: cppgraph.<query>, args: …, expect: {op, value}, provider_version}` |
| `E-SUMMARY` | `summary` invalid (FORMAT.md §4) | Multi-line summary, control characters, or > 120 chars | One plain line, ≤ 120 characters |
| `E-DUP-ID` | The same event `id` exists in two files (FORMAT.md §7.11) | Copy-pasted an event file | Keep exactly one file per event id; delete the extra copy before it is ever synced |
| `E-TOMBSTONED` | Event `id` or `lineage` appears in `deleted.toml` (FORMAT.md §7.10) | Re-adding a deleted ULID | Never resurrect deleted ULIDs; start a fresh lineage if the knowledge is needed again |
| `E-TOMBSTONE-SHAPE` | `deleted.toml` is not the expected TOML shape (FORMAT.md §7.10) | Hand-edited tombstone | `[[deleted]]` blocks of `{lineage, ulids}` only; append entries, never edit |
| `E-CYCLE` | The reference graph over resolvable `targets` contains a cycle (FORMAT.md §7.5) | Events targeting each other circularly | Fix before first publication: discard the pending set (`masora sync --drop` discards it whole) and rewrite the events correctly |
| `E-TARGET-KIND` | An event targets a kind it may not target (FORMAT.md §7.5) | e.g. a `.doubt` targeting a claim | Allowed: verify→claim, doubt→verify, undoubt→doubt, refute→any, unrefute→refute; `contradicts`→claim |
| `E-LINEAGE` | `targets`/`contradicts` resolves to an event in another lineage (FORMAT.md §7.6) | Copy-pasted a target from another lineage | Reference only events of the same lineage |
| `E-REWRITE` *sync* | A known event id was modified or deleted (FORMAT.md §7.9) | Editing or deleting an existing event file (tampering) | Restore the original content (git checkout); corrections are new events, not edits |
| `E-GC-UNAVAILABLE` *sync* | A whole lineage was deleted but not tombstoned (FORMAT.md §7.9–§7.10) | Manual removal of a lineage directory without running `masora gc` | Whole-lineage deletion goes through `masora gc <base-dir> --lineage <ulid> --yes`, which tombstones the lineage; restore the files or run gc |
| `E-GC-ULID` *gc* | A `--lineage` value is not a well-formed ULID (FORMAT.md §3) | Typo'd or truncated ULID on the gc command line | Pass canonical uppercase 26-char Crockford-base32 ULIDs (first character ≤ `7`) |
| `E-GC-UNKNOWN` *gc* | The requested lineage has no events in the base and no tombstone | Wrong ULID; a version/event ULID passed instead of the lineage ULID; the lineage was already collected | Check the ULID (`masora check` lists every lineage); gc never suggests lineages |
| `E-GC-CHECK` *gc* | The tree failed `masora check` after gc's deletion (FORMAT.md §7.9) | Unexpected: gc only removes tombstoned whole lineages | Report it; restore the tree with `git restore` before retrying |
| `E-FOUNDER` *sync* | An added v2+ claim has no founding claim in `origin/main` or the pending diff (FORMAT.md §7.8) | Publishing a new version without v1 | Include the founding claim (`id == lineage`) in the same sync |
| `E-TOMBSTONE-SHRINK` *sync* | `deleted.toml` lost entries present at the merge-base (FORMAT.md §7.10) | Tombstone edited down | Tombstones are append-only by content; restore the missing entries |
| `E-GIT` *sync* | A git operation failed (fetch, push, plumbing) (FORMAT.md §7.9) | Broken/detached repo; push rejected; base is not the repository root | Fix the git error printed with the diagnostic; `sync` requires the base directory to be the repo root |
| `E-NO-ORIGIN` *sync* | No `origin` remote, or `origin/main` does not exist | Missing remote; remote has no `main` branch | Add an `origin` remote pointing at the shared base with a `main` branch |
| `E-MERGE-BASE` *sync* | merge-base(HEAD, `origin/main`) cannot be computed | Empty or unrelated history | Ensure the local base repo shares history with `origin/main` |
| `E-SETUP-ARG` *setup* | The `--base` value is malformed | Empty URL, empty `#` fragment, or a fragment path that is absolute or escapes the clone (`..`) | Pass `<git-url>` or `<git-url>#<sub-directory>`; the sub-directory must be relative and inside the base repo |
| `E-SETUP-CLONE` *setup* | A git operation of `masora setup` failed (clone, sparse-checkout, branch detection) | Unreachable remote, missing network/credentials, unusable clone destination | Fix the git error printed with the diagnostic; the remote must be reachable with your credentials |
| `E-SETUP-NO-TOML` *setup* | `base.toml` is missing from the cloned base directory | The URL or `#<path>` does not point at a Masora base | Check the URL and the `#<path>` fragment; a base declares itself with `base.toml` at its root (MASORA_DESIGN.md §9) |
| `E-SETUP-SCHEMA` *setup* | `base.toml` is not valid TOML or violates its schema | Hand-edited base file: missing or mistyped `name`/`code_remotes`, unknown key | `base.toml` holds exactly `name` (non-empty string) and `code_remotes` (list of git remotes it serves) |
| `E-SETUP-CONFIG` *setup* | The existing `config.toml` cannot be read or re-serialized | Hand-edited config: invalid TOML, or a value the writer cannot round-trip (e.g. a TOML date) | Fix or remove the offending entry in `~/.config/masora/config.toml` |
| `E-SETUP-WRITE` *setup* | `config.toml` (or its directory) could not be written | Missing permissions, the path exists as a directory, read-only location | Check permissions on `~/.config/masora/` (the `MASORA_HOME` environment variable relocates it) |
| `E-SETUP-DUPLICATE` *setup* | The base name is already configured with a different remote | Two different bases derive the same name, or the base moved to another remote | Remove the stale `[bases.<name>]` entry by hand, then re-run `masora setup`; the same remote (after normalization) updates in place |
| `E-IDX-REPO` *index* | The `--repo` path is not an existing directory (MASORA_DESIGN.md §6.2) | Typo'd path; checkout not cloned yet | Pass the checkout the fingerprints are computed against (default: current directory) |
| `E-IDX-WRITE` *index* | The index location could not be written (MASORA_DESIGN.md §8) | Missing permissions, read-only `$MASORA_HOME`, path exists as a file | Check permissions on `~/.local/share/masora/indexes/` (the `MASORA_HOME` environment variable relocates it) |
| `E-IDX-CORRUPT` *index/search* | The index file is unreadable or was built by another schema version | Truncated/corrupted DB (the index is disposable); schema changed between versions | Rebuild with `masora index <base-dir> --repo <path>` — a full rebuild is always safe |
| `E-IDX-NOINDEX` *search* | No index exists at the expected location | `masora index` never ran for this base × repo pair, or the DB was deleted | Build the index first: `masora index <base-dir> --repo <path>` |
| `E-IDX-QUERY` *search* | The query is not valid FTS5 MATCH syntax | Unbalanced quotes/parens, empty query, FTS operators misused | Fix the query (FTS5 MATCH syntax); the query is an argument, nothing crashed |
| `W-DANGLING` | `targets`/`contradicts` does not resolve within the base (FORMAT.md §7.5) | Target not yet merged (cross-PR); typo'd ULID | Tolerated across PRs; check the ULID — a dangling event stays inactive in the fold |
| `W-SKEW` | `targets` ULID is lexically greater than the event's own `id` (FORMAT.md §7.5) | Clock skew between writers | Harmless; lexical ULID order is only the fold tie-break |
| `W-FOUNDER` | A v2+ version has no founding claim; excluded from resolution (FORMAT.md §7.8) | v1 missing locally in standalone check | Add the founding claim; `sync` enforces this as `E-FOUNDER` |
| `W-GC-ACTIVE` *gc* | The deleted lineage still has active (non-refuted) versions (SPEC.md: fully-refuted lineages are valuable negative knowledge) | Deleting live knowledge by explicit request | Expected only when intentionally discarding a live lineage; correcting a claim is usually a refute, not a deletion |
| `W-REPLAY` | Structural claims present but proof replay is not wired in standalone check (FORMAT.md §4) | Running `masora check` standalone (no anchor provider) | Informational: replay outcome is `unknown`, never assumed to pass |
| `W-IDX-CORRUPT` *index* | An existing index file was unreadable and was discarded before the rebuild (MASORA_DESIGN.md §8) | Truncated DB from a killed process; the index is disposable | Informational: `masora index` always rebuilds from scratch, the new DB replaced the corrupt one |
| `W-IDX-STALE` *search* | The base HEAD changed since the index was built (TODO: rebuild triggers) | New commits/pull on the base after `masora index` | Rebuild with `masora index <base-dir> --repo <path>`; results stay readable but statuses may be outdated |
