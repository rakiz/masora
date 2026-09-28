"""`masora setup`: onboarding — clone a base, read its base.toml, write the local config (MASORA_DESIGN.md §9)."""

from __future__ import annotations

import json
import math
import re
import subprocess
import tomllib
from pathlib import Path, PurePosixPath

from .config import bases_root, config_path, normalize_remote
from .diagnostics import (
    E_SETUP_ARG,
    E_SETUP_CLONE,
    E_SETUP_CONFIG,
    E_SETUP_DUPLICATE,
    E_SETUP_NO_TOML,
    E_SETUP_SCHEMA,
    E_SETUP_WRITE,
    Diag,
)
from .sync import git_env

_SLUG_RE = re.compile(r"[^a-z0-9_-]+")
_BARE_KEY_RE = re.compile(r"[A-Za-z0-9_-]+")


class SetupError(Exception):
    def __init__(self, diag: Diag):
        super().__init__(diag.message)
        self.diag = diag


def run(base_spec: str) -> int:
    print(f"masora setup {base_spec}")
    try:
        _setup(base_spec)
    except SetupError as exc:
        print(f"  {exc.diag.render()}")
        print("FAILED: 1 error(s)")
        return 1
    return 0


def _setup(base_spec: str) -> None:
    remote, path = _parse_spec(base_spec)
    slug = _slug(remote)
    if not slug:
        raise SetupError(
            Diag("error", E_SETUP_ARG, f"cannot derive a base name from the remote {remote!r}")
        )
    config = _load_config()
    _refuse_duplicate(config, slug, remote)
    dest = bases_root() / slug
    _clone(remote, dest, path)
    base_dir = dest.joinpath(*PurePosixPath(path).parts) if path else dest
    name, code_remotes = _read_base_toml(base_dir)
    branch = _head_branch(dest)
    added, updated = _update_config(config, slug, remote, path, branch, code_remotes)
    _write_config(config)
    where = f" (sparse: {path})" if path else ""
    print(f"base {dest} ({name}){where}")
    print(f"branch: {branch}")
    print(f"mappings: {added} added, {updated} updated")
    print(f"config written: {config_path()}")


def _parse_spec(base_spec: str) -> tuple[str, str | None]:
    text = base_spec.strip()
    remote, sep, fragment = text.partition("#")
    remote = remote.strip()
    path = fragment.strip() if sep else None
    if not remote or (sep and not path):
        raise SetupError(
            Diag(
                "error",
                E_SETUP_ARG,
                "--base must be <git-url> or <git-url>#<sub-directory> (MASORA_DESIGN.md §9)",
            )
        )
    if path:
        pure = PurePosixPath(path)
        parts = pure.parts
        if pure.is_absolute() or ".." in parts or "." in parts or not parts:
            raise SetupError(
                Diag(
                    "error",
                    E_SETUP_ARG,
                    "the #<path> fragment must be a relative sub-directory inside the base "
                    f"repo: {path!r}",
                )
            )
        path = pure.as_posix()
    return remote, path


def _slug(remote: str) -> str:
    text = remote.rstrip("/")
    name = text.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    name = re.sub(r"\.git$", "", name, flags=re.IGNORECASE)
    return _SLUG_RE.sub("-", name.lower()).strip("-")


def _git(args: list[str], what: str) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, check=False, env=git_env())
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or proc.stdout.strip()
        raise SetupError(Diag("error", E_SETUP_CLONE, f"{what} failed: {stderr}"))
    return proc.stdout.strip()


def _clone(remote: str, dest: Path, path: str | None) -> None:
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SetupError(
            Diag("error", E_SETUP_CLONE, f"cannot create the bases directory {dest.parent}: {exc}")
        ) from exc
    if dest.exists() and not (dest.is_dir() and not any(dest.iterdir())):
        _reuse_or_fail(remote, dest)
    else:
        _git(
            ["git", "clone", "--filter=blob:none", "--sparse", remote, str(dest)],
            f"git clone {remote}",
        )
    if path:
        _git(
            ["git", "-C", str(dest), "sparse-checkout", "set", path],
            f"git sparse-checkout set {path}",
        )
    else:
        _git(
            ["git", "-C", str(dest), "sparse-checkout", "disable"],
            "git sparse-checkout disable",
        )


def _reuse_or_fail(remote: str, dest: Path) -> None:
    if not (dest / ".git").is_dir():
        raise SetupError(
            Diag("error", E_SETUP_CLONE, f"clone destination {dest} exists and is not a git clone")
        )
    origin = _git(["git", "-C", str(dest), "remote", "get-url", "origin"], "git remote get-url")
    if normalize_remote(origin) != normalize_remote(remote):
        raise SetupError(
            Diag(
                "error",
                E_SETUP_DUPLICATE,
                f"clone destination {dest} already holds {origin!r}, not {remote!r}",
            )
        )


def _read_base_toml(base_dir: Path) -> tuple[str, list[str]]:
    path = base_dir / "base.toml"
    if not path.is_file():
        raise SetupError(
            Diag(
                "error",
                E_SETUP_NO_TOML,
                f"base.toml not found at {base_dir} — a base declares itself with base.toml at "
                "its root (MASORA_DESIGN.md §9)",
                "base.toml",
            )
        )
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as exc:
        raise SetupError(
            Diag("error", E_SETUP_SCHEMA, f"base.toml is not readable TOML: {exc}", "base.toml")
        ) from exc
    if not isinstance(data, dict) or set(data) != {"name", "code_remotes"}:
        raise SetupError(
            Diag(
                "error",
                E_SETUP_SCHEMA,
                "base.toml must hold exactly the keys name and code_remotes, got "
                f"{sorted(data) if isinstance(data, dict) else type(data).__name__}",
                "base.toml",
            )
        )
    name = data["name"]
    if not isinstance(name, str) or not name.strip():
        raise SetupError(
            Diag("error", E_SETUP_SCHEMA, "base.toml: name must be a non-empty string", "base.toml")
        )
    remotes = data["code_remotes"]
    if not isinstance(remotes, list) or any(
        not isinstance(item, str) or not item.strip() for item in remotes
    ):
        raise SetupError(
            Diag(
                "error",
                E_SETUP_SCHEMA,
                "base.toml: code_remotes must be a list of non-empty git remote strings",
                "base.toml",
            )
        )
    if any(not normalize_remote(item) for item in remotes):
        raise SetupError(
            Diag(
                "error",
                E_SETUP_SCHEMA,
                "base.toml: a code_remotes entry does not look like a git remote",
                "base.toml",
            )
        )
    return name, remotes


def _head_branch(dest: Path) -> str:
    branch = _git(["git", "-C", str(dest), "rev-parse", "--abbrev-ref", "HEAD"], "git rev-parse")
    if not branch:
        raise SetupError(Diag("error", E_SETUP_CLONE, "could not detect the clone's HEAD branch"))
    return branch


def _load_config() -> dict:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as exc:
        raise SetupError(
            Diag(
                "error",
                E_SETUP_CONFIG,
                f"the existing config.toml cannot be read: {exc} — fix or remove {path}",
                "config.toml",
            )
        ) from exc
    if not isinstance(data, dict):
        raise SetupError(
            Diag("error", E_SETUP_CONFIG, "the existing config.toml is not a table", "config.toml")
        )
    return data


def _refuse_duplicate(config: dict, slug: str, remote: str) -> None:
    bases = config.get("bases")
    if not isinstance(bases, dict) or slug not in bases:
        return
    entry = bases[slug]
    existing = entry.get("remote") if isinstance(entry, dict) else None
    if not isinstance(existing, str) or normalize_remote(existing) != normalize_remote(remote):
        raise SetupError(
            Diag(
                "error",
                E_SETUP_DUPLICATE,
                f"base '{slug}' is already configured"
                + (f" with the different remote {existing!r}" if existing else "")
                + f" — masora setup refuses to overwrite a different base; remove the "
                f"[bases.{slug}] entry by hand or fix the URL",
            )
        )


def _update_config(
    config: dict, slug: str, remote: str, path: str | None, branch: str, code_remotes: list[str]
) -> tuple[int, int]:
    bases = config.setdefault("bases", {})
    if not isinstance(bases, dict):
        raise SetupError(
            Diag("error", E_SETUP_CONFIG, "the existing [bases] is not a table", "config.toml")
        )
    entry: dict = {"remote": remote}
    if path:
        entry["path"] = path
    entry["branch"] = branch
    bases[slug] = entry
    mappings = config.get("mappings", [])
    if not isinstance(mappings, list) or any(not isinstance(item, dict) for item in mappings):
        raise SetupError(
            Diag(
                "error",
                E_SETUP_CONFIG,
                "the existing [[mappings]] is not an array of tables",
                "config.toml",
            )
        )
    added = 0
    updated = 0
    seen: set[str] = set()
    for item in code_remotes:
        normalized = normalize_remote(item)
        if normalized in seen:
            continue
        seen.add(normalized)
        existing = next(
            (
                mapping
                for mapping in mappings
                if isinstance(mapping.get("code_remote"), str)
                and normalize_remote(mapping["code_remote"]) == normalized
            ),
            None,
        )
        if existing is None:
            mappings.append({"code_remote": normalized, "bases": [slug]})
            added += 1
            continue
        bases_list = existing.setdefault("bases", [])
        if not isinstance(bases_list, list):
            raise SetupError(
                Diag(
                    "error",
                    E_SETUP_CONFIG,
                    f"the existing mapping {normalized!r} has a non-list bases",
                    "config.toml",
                )
            )
        if slug not in bases_list:
            bases_list.append(slug)
            updated += 1
    config["mappings"] = mappings
    return added, updated


def _write_config(config: dict) -> None:
    path = config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_emit_toml(config), encoding="utf-8")
    except OSError as exc:
        raise SetupError(
            Diag("error", E_SETUP_WRITE, f"cannot write {path}: {exc}", "config.toml")
        ) from exc


def _emit_toml(data: dict) -> str:
    lines: list[str] = []
    _emit_table(data, "", lines)
    return "\n".join(lines) + "\n" if lines else ""


def _emit_table(data: dict, prefix: str, lines: list[str]) -> None:
    tables: list[tuple[str, dict]] = []
    arrays: list[tuple[str, list[dict]]] = []
    for key, value in data.items():
        if isinstance(value, dict):
            tables.append((key, value))
        elif isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            arrays.append((key, value))
        else:
            lines.append(f"{_toml_key(key)} = {_toml_value(key, value)}")
    for key, value in tables:
        name = f"{prefix}{_toml_key(key)}"
        if value and all(isinstance(item, dict) for item in value.values()):
            _emit_table(value, f"{name}.", lines)
        else:
            _header(lines, f"[{name}]")
            _emit_table(value, f"{name}.", lines)
    for key, value in arrays:
        name = f"{prefix}{_toml_key(key)}"
        for element in value:
            _header(lines, f"[[{name}]]")
            _emit_table(element, f"{name}.", lines)


def _toml_key(key: str) -> str:
    if _BARE_KEY_RE.fullmatch(key):
        return key
    return json.dumps(key, ensure_ascii=False)


def _header(lines: list[str], text: str) -> None:
    if lines:
        lines.append("")
    lines.append(text)


def _toml_value(key: str, value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _unserializable(key, value)
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list) and all(isinstance(item, (str, int, float, bool)) for item in value):
        return "[" + ", ".join(_toml_value(key, item) for item in value) + "]"
    raise _unserializable(key, value)


def _unserializable(key: str, value: object) -> SetupError:
    return SetupError(
        Diag(
            "error",
            E_SETUP_CONFIG,
            f"cannot serialize the existing config.toml: unsupported value at {key!r} "
            f"({type(value).__name__}) — fix or remove the entry",
            "config.toml",
        )
    )
