#!/usr/bin/env python3
"""masora SessionStart freshness hook (MASORA_DESIGN.md §10.1).

Installed by `masora hook install`; registered as a Claude Code
SessionStart command (or spawned by an opencode plugin). Background and
best-effort: fetches + fast-forwards the configured base clones, rebuilds
stale indexes within the §10.1 wall-clock budget and prints at most TWO
lines — the stale-lineage summary plus the standing usage rule. Every
failure is silent, exit 0 always; the hook must never block or fail a
session start.
"""

import os
import shutil
import sys
from pathlib import Path


def _reexec_if_needed() -> None:
    """Plain `python3` (the settings.json registration) may lack the masora
    package — re-exec ONCE into an interpreter that has it, preferring the
    one behind the `masora` CLI (its shebang names the tool env). Still
    silent: no interpreter found means exit 0, never a traceback on the
    session start."""
    try:
        import masora  # noqa: F401
    except ModuleNotFoundError:
        pass
    else:
        return
    if os.environ.get("MASORA_HOOK_REEXEC") == "1":
        return
    candidates = []
    cli = shutil.which("masora")
    if cli:
        try:
            first = Path(cli).read_text(encoding="utf-8").splitlines()[0]
        except (OSError, IndexError):
            first = ""
        if first.startswith("#!") and "python" in first:
            candidates.append(first[2:].strip())
    candidates.append(Path.home() / ".local/share/uv/tools/masora/bin/python")
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file() and path != Path(sys.executable):
            env = dict(os.environ, MASORA_HOOK_REEXEC="1")
            os.execve(str(path), [str(path), __file__], env)


_reexec_if_needed()

try:
    from masora.hook import session_start
except Exception:  # noqa: BLE001 — a stale interpreter still stays silent, exit 0

    def session_start():
        return 0


if __name__ == "__main__":
    raise SystemExit(session_start())
