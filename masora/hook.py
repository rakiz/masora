"""`masora hook`: the SessionStart freshness hook (MASORA_DESIGN.md §10.1).

The hook exists for AUDIT.md's operational risk 1 ("silent recall decay"): a
base that quietly stops being pulled stops being trusted without anyone
noticing. At agent session start, the hook — IN THE BACKGROUND, with SILENT
FAILURE (every exception swallowed, exit 0 always, never blocking the
session):

1. fast-forwards each configured base clone's local `main` from `origin`
   (fetch + `merge --ff-only` — NEVER force, NEVER rebase; a diverged clone
   is skipped silently, reporting it is `masora doctor`'s job),
2. rebuilds the indexes whose four-axis staleness says stale, bounded by a
   hard wall-clock budget (the caps below),
3. prints ONE line — the stale-lineage summary (count + the worst staleness
   reason class) — or nothing at all when everything is fresh.

Installation (`masora hook install`) reuses the skill-install pattern: the
hook script ships inside the package
(`masora/hooks/session_start.py`, one canonical copy) and is written into
every detected agent home. Claude Code also gets the SessionStart entry
merged into `~/.claude/settings.json`; for opencode the registration cannot
be written safely from here (its plugin format is JavaScript), so the manual
config snippet is printed instead — silent best-effort, never a hard failure.
Re-running install overwrites — that IS the update path.
"""

from __future__ import annotations

import json
import sqlite3
import time
import tomllib
from importlib import resources
from pathlib import Path
from urllib.parse import quote

from . import config, index
from .sync import (
    FETCH_TIMEOUT_S,
    MAIN_BRANCH,
    REMOTE,
    git_env,
    run_git,
)

# Hook caps (MASORA_DESIGN.md §10.1): the hook borrows the session's machine,
# never its attention — one line of output maximum, a hard wall-clock budget
# on index rebuilds, short git timeouts, silent failure everywhere. Raising
# these is a §10.1 decision, not a local tweak.
REBUILD_BUDGET_S = 20.0
HOOK_GIT_TIMEOUT_S = 30

SCRIPT_REL = ".claude/hooks/masora_session_start.py"
OPENCODE_SCRIPT_REL = ".config/opencode/hooks/masora_session_start.py"
SETTINGS_REL = ".claude/settings.json"
HOOK_MARKER = "masora_session_start.py"

# The worst-first ranking of the four staleness axes (index.py's reason
# texts) for the one-line summary; a graph re-index outranks HEAD moves,
# which outrank uncommitted-write noise.
REASON_CLASSES = (
    ("the graph store was re-indexed", "graph re-indexed"),
    ("code HEAD changed", "code HEAD moved"),
    ("base HEAD changed", "base HEAD moved"),
    ("events written", "uncommitted writes"),
)
_REASON_RANK = {label: rank for rank, (_needle, label) in enumerate(REASON_CLASSES)}


class HookError(Exception):
    pass


def script_text() -> str:
    """The packaged hook script — the single canonical copy."""
    return (resources.files("masora") / "hooks/session_start.py").read_text(encoding="utf-8")


def run(target: str | None = None, home: Path | None = None) -> int:
    home = Path.home() if home is None else home
    if target is not None and target not in ("claude", "opencode"):
        print(
            f"unknown hook target {target!r} — known targets: claude, opencode"
            " (omit --target to install into every detected agent home)"
        )
        return 1
    wanted = (target,) if target else ("claude", "opencode")
    installed = 0
    for name in wanted:
        marker = ".claude" if name == "claude" else ".config/opencode"
        if target is None and not (home / marker).is_dir():
            continue
        installed += _install_home(name, home)
    if not installed and target is None:
        print(
            "no agent-framework directory found in the home (looking for ~/.claude or"
            " ~/.config/opencode) — pass --target claude|opencode to force one"
        )
    return 0


def _install_home(name: str, home: Path) -> int:
    """Write the script (and, for claude, register the hook); print one
    installed/updated line per artifact, idempotently."""
    text = script_text()
    script_rel = SCRIPT_REL if name == "claude" else OPENCODE_SCRIPT_REL
    target = home / script_rel
    existed = target.is_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"{'updated' if existed else 'installed'}: {target}")
    if name == "claude":
        _register_claude(home / SETTINGS_REL, f"python3 {target}")
    else:
        # opencode's hook surface is a JavaScript plugin file, not a JSON
        # setting — writing one from here would guess at its format. The
        # script is installed; the registration is the user's one-liner.
        print(
            "manual step (opencode has no JSON hook config — its plugin format is JS):"
            " create ~/.config/opencode/plugin/masora.js exporting a SessionStart"
            f" handler that spawns: python3 {target}"
        )
    return 1


def _register_claude(settings_path: Path, command: str) -> None:
    """Merge the SessionStart hook entry into Claude Code's settings.json.

    Best-effort and idempotent: an entry whose command names our script is
    never duplicated; an unreadable/unwritable settings file degrades to the
    printed manual snippet — the hook install never breaks the agent's own
    configuration.
    """
    entry = {"matcher": "", "hooks": [{"type": "command", "command": command}]}
    data: dict = {}
    existed = settings_path.is_file()
    if existed:
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("settings.json is not a JSON object")  # noqa: TRY004
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"could not edit {settings_path} ({exc}) — manual snippet:")
            print(json.dumps({"hooks": {"SessionStart": [entry]}}, indent=2))
            return
    hooks = data.setdefault("hooks", {})
    sessions = hooks.setdefault("SessionStart", [])
    if not isinstance(sessions, list):
        print(
            f"could not edit {settings_path} (hooks.SessionStart is not a list) — manual snippet:"
        )
        print(json.dumps({"hooks": {"SessionStart": [entry]}}, indent=2))
        return
    for existing in sessions:
        if isinstance(existing, dict) and HOOK_MARKER in json.dumps(existing):
            print(f"updated: {settings_path} (SessionStart entry already registered)")
            return
    sessions.append(entry)
    try:
        tmp = settings_path.parent / f".settings.json.masora-{id(entry)}"
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp.replace(settings_path)
    except OSError as exc:
        print(f"could not write {settings_path} ({exc}) — manual snippet:")
        print(json.dumps({"hooks": {"SessionStart": [entry]}}, indent=2))
        return
    print(f"{'updated' if existed else 'installed'}: {settings_path} (SessionStart)")


# --- The hook's background work (session_start and its helpers) ---


def session_start() -> int:
    """The hook entry point: NEVER raises, ALWAYS exits 0, at most one line
    on stdout. Every per-base failure is swallowed — a broken base must cost
    the session nothing (the hook is best-effort by §10.1)."""
    try:
        _summary = _run_quiet()
    except Exception:  # noqa: BLE001 — the hook must never fail a session start
        return 0
    if _summary is not None:
        try:
            print(_summary)
        except Exception:  # noqa: BLE001, S110 — even a broken stdout is silent
            pass
    return 0


def _run_quiet() -> str | None:
    bases = _configured_bases()
    if not bases:
        return None
    deadline = time.monotonic() + REBUILD_BUDGET_S
    stale_total = 0
    worst: str | None = None
    for base in bases:
        try:
            _fast_forward(base)
        except Exception:  # noqa: BLE001, S112 — a broken base costs the session nothing
            continue
        for db, repo in _index_jobs(base):
            try:
                reason = index.index_stale_reason(db, base, repo)
                if reason is not None:
                    label = _reason_class(reason)
                    if worst is None or _REASON_RANK.get(label, 0) > _REASON_RANK.get(worst, 0):
                        worst = label
                    if time.monotonic() < deadline:
                        index.build_index(base, repo)
                # Counted AFTER the (optional) rebuild: the summary describes
                # the indexes as they will be read this session.
                stale_total += _stale_lineages(db)
            except Exception:  # noqa: BLE001, S112 — same silence per index job
                continue
    if stale_total == 0 and worst is None:
        return None
    return f"masora: {stale_total} stale lineage(s)" + (f", worst reason: {worst}" if worst else "")


def _configured_bases() -> list[Path]:
    path = config.config_path()
    if not path.is_file():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError):
        return []
    bases = data.get("bases")
    if not isinstance(bases, dict):
        return []
    dirs = []
    for name in sorted(bases):
        entry = bases[name]
        if not isinstance(entry, dict):
            continue
        base_dir = config.bases_root() / config.slug(name)
        sub = entry.get("path")
        if isinstance(sub, str) and sub:
            base_dir = base_dir / sub
        if base_dir.is_dir():
            dirs.append(base_dir)
    return dirs


def _fast_forward(base_dir: Path) -> None:
    """fetch + `merge --ff-only` — never force, never rebase. Any failure
    (network, divergence, dirty tree) raises and the caller skips the base
    silently; `masora doctor` is the surface that reports clone health."""
    run_git(
        ["git", "-C", str(base_dir), "fetch", REMOTE, "--prune"],
        capture_output=True,
        timeout=FETCH_TIMEOUT_S,
        env=git_env(),
    )
    run_git(
        ["git", "-C", str(base_dir), "merge", "--ff-only", f"{REMOTE}/{MAIN_BRANCH}"],
        capture_output=True,
        timeout=HOOK_GIT_TIMEOUT_S,
        env=git_env(),
    )


def _index_jobs(base_dir: Path) -> list[tuple[Path, Path]]:
    """The (index db, code repo) pairs known for this base — from the stored
    index metas (the same source doctor uses)."""
    jobs: list[tuple[Path, Path]] = []
    index_dir = index.index_dir_for(base_dir)
    if not index_dir.is_dir():
        return jobs
    for db in sorted(index_dir.glob("*.db")):
        repo_path = index._stored_meta(db).get("repo_path") or ""
        if repo_path:
            jobs.append((db, Path(repo_path)))
    return jobs


def _stale_lineages(db: Path) -> int:
    """The count of stale-resolution lineages in one index; an unreadable
    index counts as nothing (silent failure)."""
    try:
        conn = sqlite3.connect(f"file:{quote(str(db))}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM lineages WHERE resolution = 'stale'"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return 0
    return int(row[0]) if row else 0


def _reason_class(reason: str) -> str:
    for needle, label in REASON_CLASSES:
        if needle in reason:
            return label
    return "other drift"
