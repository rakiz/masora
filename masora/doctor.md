# doctor.py — the report-only health checks

Role: one readable `masora doctor` screen answering "why is masora not
working on this machine?" — every check printed as OK / WARN / FAIL with a
concrete remedy, NOTHING ever mutated. Exit 0 when no FAIL, 1 when any FAIL;
WARNs never fail.

## Checks (in run order)

1. **Tool environment** — installed version, supported `format_version`,
   index `schema_version`; the user config found (WARN + `masora setup`
   remedy when absent) and parseable (FAIL when unreadable).
2. **Git identity** — `user.name` / `user.email` resolvable through
   `git config` (FAIL each when missing: `masora init` and sync commits need
   them). The spawn is hermetic: `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM`
   environment overrides apply, so tests control it.
3. **Per configured base** (`[bases.<name>]`): the clone directory exists
   (FAIL + `masora setup` remedy when missing), `base.toml` readable
   (FAIL), the clone's `origin` remote matching the configured remote after
   `config.normalize_remote` (FAIL on mismatch or missing remote), and a
   read-only `git fetch origin` succeeding — the doctor's ONLY network
   operation, FAIL with the git exit message on failure.
4. **gh CLI** — present and authenticated via `gh auth status`
   (report-only): missing or unauthenticated is a WARN, never a FAIL — gh
   is optional, publication falls back to the compare URL.
5. **Per (base, repo) index** — the repos come from the stored index metas
   (`repo_path`) under `index_dir_for(base)`: the SQLite index exists
   (a base with NO index at all is a WARN naming the build command), it is
   readable, and its staleness is reported through the SAME four-axis
   `index_stale_reason` strings `W-IDX-STALE` uses — fresh is OK, stale is
   a WARN with the `masora index` remedy.
6. **Graph store** — for each known code repo, `<repo>/.cppgraph` and a
   readable graph.db, with the graph's `source_commit` compared to the repo
   HEAD (report-only; cppgraph is a separate tool — absence, unreadability
   or a behind-HEAD graph is a WARN, never a FAIL).

## Injection seams

- `_fetch_origin(clone)` — the fetch, monkeypatch-able module function (the
  autouse seam for CLI-level tests), or passed as `fetcher=` to `run()`.
- `gh_checker` — a `() -> (present, authenticated, detail)` callable passed
  to `run()` (the same idiom as `status.fetch_latest_release`); the default
  `_gh_status` spawns `gh auth status` through `sync.run_git` with the M4
  timeouts.

## Invariants

- Every spawn goes through `sync.run_git`/`sync.git_env` (mandatory
  timeouts, no credential prompts, no inherited `GIT_*` repo-location vars).
- Read-only: no command in `sync`, `index`, the MCP server or any hook may
  ever invoke doctor logic to ACT on its findings — remedies are printed for
  the human, never executed.
