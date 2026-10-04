#!/usr/bin/env python3
"""masora UserPromptSubmit recall hook (MASORA_DESIGN.md §10.1, channel 2).

Installed by `masora hook install`; registered as a Claude Code
UserPromptSubmit command. Claude Code hands the prompt to stdin as JSON
(`prompt`, `cwd`); stdout text on exit 0 becomes agent context. Read-only
and best-effort: it searches the ALREADY-BUILT index for the 2-3 most
relevant claims and prints them — prefixed by the one-line usage rule —
with their trust labels; nothing at all prints when nothing matches.
Never builds the
index (the SessionStart hook owns rebuilds), never writes anything, never
fails a prompt. Stateless v1: every prompt is searched on its own — no
memory between prompts. Every failure is silent, exit 0 always.
"""

import json
import os
import shutil
import sys
from pathlib import Path


def _reexec_if_needed() -> None:
    """Plain `python3` (the settings.json registration) may lack the masora
    package — re-exec ONCE into an interpreter that has it, preferring the
    one behind the `masora` CLI (its shebang names the tool env). Still
    silent: no interpreter found means exit 0, never a traceback on the
    agent's prompt."""
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
    from masora.hook import user_prompt_submit
except Exception:  # noqa: BLE001 — a stale interpreter still stays silent, exit 0

    def user_prompt_submit(*_args, **_kwargs):
        return None


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        prompt = payload.get("prompt") if isinstance(payload, dict) else None
        cwd = payload.get("cwd") if isinstance(payload, dict) else None
        text = user_prompt_submit(
            prompt if isinstance(prompt, str) else "",
            Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd(),
        )
        if text:
            print(text)
    except Exception:  # noqa: BLE001 — the hook must never fail a prompt
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
