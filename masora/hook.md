# hook.py — the SessionStart freshness hook

Role: `masora hook install [--target {claude,opencode}]` plus the hook's
background work `session_start()` — the §10.1 freshness automation that
exists for AUDIT.md operational risk 1 ("silent recall decay": a base that
quietly stops being pulled stops being trusted without anyone noticing).

## Install (the skill-install pattern)

- The hook script ships in the package (`masora/hooks/session_start.py`,
  one canonical copy) and is written VERBATIM into every detected agent
  home — the shipped == installed invariant is tested, like the skill's.
- Claude Code: the SessionStart entry is MERGED into
  `~/.claude/settings.json` (idempotent — an entry whose command names our
  script is never duplicated; foreign keys preserved; an unreadable file
  degrades to the printed manual snippet, never a broken settings file).
- opencode: its hook surface is a JavaScript plugin file, not a JSON
  setting — the script is installed but the registration is PRINTED as the
  manual snippet; writing a .js plugin from here would guess at a format.
- `--target` unknown is a clean refusal; re-running install IS the update
  path (overwrite, `installed:`/`updated:` lines).

## The hook's work (session_start) — silent by contract

1. Per configured base (`[bases.*]` from the user config): fetch + `merge
   --ff-only` — NEVER force, NEVER rebase; any failure (diverged clone,
   network, dirty tree) skips the base SILENTLY; `masora doctor` is the
   surface that reports clone health.
2. Per (base, repo) index job (repos from the stored index metas, the same
   source doctor uses): the four-axis `index_stale_reason` decides a
   rebuild, bounded by `REBUILD_BUDGET_S` — a hard wall-clock budget, one of
   the named §10.1 caps (the constants carry the §10.1 pointer).
3. Output: AT MOST one line — `masora: <n> stale lineage(s), worst reason:
   <class>` — or nothing when fresh. The count is read AFTER the (optional)
   rebuild; the worst reason class ranks the four staleness axes
   graph > code HEAD > base HEAD > uncommitted writes.

## Invariants

- SILENT FAILURE: `session_start()` never raises, always exits 0, every
  per-base/per-index exception swallowed; even the final print is guarded.
- The hook runs in the background at session start: it must never block a
  session, never prompt (all spawns through `sync.run_git`/`git_env` with
  timeouts), never print more than one line.
- The hook NEVER mutates git history: fetch + ff-only merge only — a
  diverged clone waits for a human (or `masora doctor`'s remedies).
