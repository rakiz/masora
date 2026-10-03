# reset.py — the refoundation acceptance move

Role: `masora reset <base-dir> --from-origin [--yes]` — the ONLY tool path
that accepts an out-of-band remote history rewrite by resetting local
`main` to `origin/main` (hard reset). Runbook: docs/REFOUNDATION.md.

## The invariants (AUDIT.md operational risk 3)

- **NEVER automatic.** Nothing in `sync`, `index`, the MCP server or any
  hook may call this module; it exists only as an explicit, human-confirmed
  move. There is deliberately no code path into it from anywhere else.
- **Tamper evidence stays intact.** The command does NOT judge whether the
  remote rewrite was a refoundation or an attack — it says so in its own
  output. The sync-time `E-REWRITE` refusal is unchanged; reset is the
  explicit acceptance move AFTER a human verified the rewrite out-of-band.

## Flow (plan-then-confirm, exactly like gc/compact)

1. **Dirty-tree refusal** (`E-RESET-DIRTY`, exit 1): `git status
   --porcelain` must be empty up front — a hard reset would silently
   destroy uncommitted work; the caller commits or discards first.
2. **Fetch** `origin` (through `sync.run_git`/`git_env` with the M4 fetch
   timeout); failure is `E-RESET-FETCH` (exit 1).
3. **Verify `origin/main` exists** after the fetch; otherwise
   `E-RESET-NO-MAIN` (exit 1).
4. **Plan**: the target commit, the count of local-only commits
   (`rev-list origin/main..main`) WITH their subjects — the informed part
   of the confirmation — and the neutrality note. Exit 3 without `--yes`,
   nothing written.
5. **Execute** with `--yes`: when `main` is the current branch, `git reset
   --hard origin/main`; otherwise (detached HEAD, another branch) only
   `update-ref refs/heads/main` — the confirmation is about main's history,
   never the work tree. Prints the follow-ups: rebuild indexes
   (`masora index`), re-run `masora check`.

## Diagnostics

- `E-RESET-DIRTY` — dirty working tree.
- `E-RESET-FETCH` — fetch or reset git failure.
- `E-RESET-NO-MAIN` — `origin/main` missing after the fetch.

All three live in `masora/diagnostics.py` and docs/TROUBLESHOOTING.md
(two-way guarded by tests/test_docs.py); the `E-REWRITE` remedy strings in
`masora/sync.py` point at docs/REFOUNDATION.md.
