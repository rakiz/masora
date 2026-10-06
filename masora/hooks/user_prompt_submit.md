# user_prompt_submit.py — the shipped UserPromptSubmit hook script

Role: the executable Claude Code registers for the UserPromptSubmit event
(the settings.json command written by `masora hook install`). One canonical
packaged copy; installed verbatim (the shipped == installed invariant is
tested).

## Contract

- stdin: Claude Code's JSON payload (`prompt`, `cwd`, `session_id`);
  stdout text on exit 0 becomes agent context — here, the recalled claim
  lines from `masora.hook.user_prompt_submit` (see masora/hook.md).
- Garbage stdin (not JSON, not an object, missing fields) degrades to an
  empty prompt / cwd default — the hook still exits 0 silently.
- Per-session dedup: with a string `session_id` in the payload, the hint
  is injected on the session's first prompt and again only when its
  content changed; an identical hint on a later turn prints nothing. The
  state is a small per-session file (sha256 of the last injected hint,
  under `<MASORA_HOME or ~/.local/share>/masora/hook-state/`) and is
  BEST-EFFORT, FAIL-OPEN: any error reading or writing it defaults to
  injecting — the dedup never turns into silence, never fails the prompt.
  There is deliberately NO cleanup of stale session state files (they are
  cheap, sessions are finite); details in masora/hook.md.

## The re-exec bootstrap (`_reexec_if_needed`)

The registered interpreter may lack the masora package (a bare system
python3) or hold a stale copy (an old uv tool env): then the script re-execs
ONCE into an interpreter that has it — preferring the python behind the
`masora` CLI's shebang, then `~/.local/share/uv/tools/masora/bin/python` —
guarded by `MASORA_HOOK_REEXEC=1` against loops. No interpreter works (or
the import still fails, e.g. a stale copy without the hook symbol) → the
import is guarded and the hook degrades to a no-op: silent, exit 0 always.

## Pitfalls

- The bootstrap runs at MODULE level, before the masora import — keep it
  first; a missed import must never raise past `main` (ruff's E402 is not
  enabled here for that reason).
- The session_start script carries the SAME bootstrap (the same stale-
  interpreter failure mode applies to the freshness hook).
