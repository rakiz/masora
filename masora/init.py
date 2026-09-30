"""`masora init`: base bootstrap — create a new Masora base locally (MASORA_DESIGN.md §9)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .checker import check_base
from .config import normalize_remote
from .diagnostics import (
    E_INIT_ARG,
    E_INIT_CHECK,
    E_INIT_GIT,
    E_INIT_TARGET,
    E_INIT_WRITE,
    Diag,
)
from .sync import git_env

COMMIT_MESSAGE = "masora init: base {name}"


class InitError(Exception):
    def __init__(self, diag: Diag):
        super().__init__(diag.message)
        self.diag = diag


def run(
    base_dir: Path | None,
    name: str | None,
    code_remotes: list[str] | None = None,
    here: bool = False,
    force: bool = False,
) -> int:
    try:
        target = _resolve_target(base_dir, here)
    except InitError as exc:
        print(f"  {exc.diag.render()}")
        print("FAILED: 1 error(s)")
        return 1
    print(f"masora init {target}")
    try:
        _create(target, name or "", code_remotes or [], force)
    except InitError as exc:
        print(f"  {exc.diag.render()}")
        print("FAILED: 1 error(s)")
        return 1
    return 0


def _resolve_target(base_dir: Path | None, here: bool) -> Path:
    if base_dir is not None and here:
        raise InitError(Diag("error", E_INIT_ARG, "pass a base directory or --here, not both"))
    if base_dir is None and not here:
        raise InitError(Diag("error", E_INIT_ARG, "pass a base directory, or --here"))
    return base_dir if base_dir is not None else Path.cwd()


def _create(target: Path, name: str, code_remotes: list[str], force: bool) -> None:
    if not name.strip():
        raise InitError(
            Diag("error", E_INIT_ARG, "--name must be a non-empty display name for base.toml")
        )
    remotes = _clean_remotes(code_remotes)
    _refuse_target(target, force)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise InitError(Diag("error", E_INIT_TARGET, f"cannot create {target}: {exc}")) from exc
    _write_base_toml(target, name, remotes)
    if remotes:
        print(f"code_remotes: {', '.join(remotes)}")
    _check_tree(target)
    _git_init(target, name)
    _finish(target, name)


def _clean_remotes(code_remotes: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in code_remotes:
        normalized = normalize_remote(item)
        if not normalized:
            raise InitError(
                Diag("error", E_INIT_ARG, f"--code-remote {item!r} does not look like a git remote")
            )
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _refuse_target(target: Path, force: bool) -> None:
    if target.exists() and not target.is_dir():
        raise InitError(Diag("error", E_INIT_TARGET, f"{target} exists and is not a directory"))
    if (target / "base.toml").is_file():
        raise InitError(
            Diag(
                "error",
                E_INIT_TARGET,
                f"{target} is already a Masora base (base.toml exists) — "
                "init never overwrites a base",
            )
        )
    if target.is_dir() and any(target.iterdir()) and not force:
        raise InitError(
            Diag(
                "error",
                E_INIT_TARGET,
                f"{target} is not empty — pass --force to create the base inside it anyway",
            )
        )


def _write_base_toml(target: Path, name: str, code_remotes: list[str]) -> None:
    remotes = ", ".join(json.dumps(item, ensure_ascii=False) for item in code_remotes)
    text = f"name = {json.dumps(name, ensure_ascii=False)}\ncode_remotes = [{remotes}]\n"
    try:
        (target / "base.toml").write_text(text, encoding="utf-8")
    except OSError as exc:
        raise InitError(
            Diag("error", E_INIT_WRITE, f"cannot write {target / 'base.toml'}: {exc}", "base.toml")
        ) from exc


def _check_tree(target: Path) -> None:
    result = check_base(target)
    for diag in result.diags:
        print(f"  {diag.render()}")
    if result.errors:
        raise InitError(
            Diag(
                "error",
                E_INIT_CHECK,
                f"the created tree failed masora check: {len(result.errors)} error(s) — a "
                "--force directory must not hold event files or a deleted.toml",
            )
        )


def _git(args: list[str], what: str) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, check=False, env=git_env())
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or proc.stdout.strip()
        raise InitError(Diag("error", E_INIT_GIT, f"{what} failed: {stderr}"))
    return proc.stdout.strip()


def _git_init(target: Path, name: str) -> None:
    _git(["git", "-C", str(target), "init", "-b", "main"], "git init")
    _git(["git", "-C", str(target), "add", "base.toml"], "git add")
    _git(
        ["git", "-C", str(target), "commit", "-m", COMMIT_MESSAGE.format(name=name)],
        "git commit",
    )


def _finish(target: Path, name: str) -> None:
    shown = target if target.is_absolute() else Path.cwd() / target
    print(f"base {shown} ({name})")
    print(f"next: masora setup --base {shown}")
    print(
        "init works locally — publishing to a shared repo is your git work: push it, "
        "then hand out the URL for masora setup"
    )
    print(
        "after setup, install the agent skill: docs/skills/masora/SKILL.md in the masora checkout"
    )
