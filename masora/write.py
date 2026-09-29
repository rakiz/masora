"""Shared MCP write path: base resolution, canonical emission, atomic write + post-check.

One pipeline for all write tools (FORMAT.md §4-§6): resolve the base per
MASORA_DESIGN.md §8-§9 (mapping on the normalized code remote, else
`default_base`, else explicit), emit the event file in the canonical block
style of FORMAT.md §4, pre-validate with `schema.validate_event`, write, then
re-run `check_base` — a tool that returns success on an invalid tree is
forbidden, so a failed post-check unlinks the just-written file (FORMAT.md §6:
nothing is written).
"""

from __future__ import annotations

import json
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from . import config
from .checker import check_base
from .diagnostics import E_MCP_NO_BASE, CheckFailure, Diag
from .index import ParsedEvent, _parse_events
from .schema import validate_event
from .sync import git_env


class WriteError(Exception):
    """A refused tool operation carrying its diagnostics (the first code leads)."""

    def __init__(self, *diags: Diag):
        super().__init__(diags[0].message if diags else "write refused")
        self.diags = list(diags)

    @property
    def code(self) -> str | None:
        return self.diags[0].code if self.diags else None


def load_user_config() -> dict:
    path = config.config_path()
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as exc:
        raise WriteError(
            Diag("error", E_MCP_NO_BASE, f"config.toml cannot be read: {exc}", str(path))
        ) from exc
    return data if isinstance(data, dict) else {}


def origin_remote(repo: Path) -> str | None:
    """The code repo's `origin` URL, or None (git spawns sanitized by `git_env`)."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
    )
    value = proc.stdout.strip()
    return value if proc.returncode == 0 and value else None


def human_name(base_dir: Path) -> str | None:
    """The base repo's `git config user.name` — the human writer's self-signed name.

    Declarative provenance (MASORA_DESIGN.md §12.10): identity comes from the
    base-repo git config (the commits are the trust path); None when unset —
    the field is then simply absent from the event.
    """
    proc = subprocess.run(
        ["git", "-C", str(base_dir), "config", "user.name"],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
    )
    value = proc.stdout.strip()
    return value if proc.returncode == 0 and value else None


def base_dir_for_name(data: dict, name: str) -> Path | None:
    """`[bases.<name>]` entry → local checkout path (MASORA_DESIGN.md §9 layout)."""
    bases = data.get("bases")
    entry = bases.get(name) if isinstance(bases, dict) else None
    if not isinstance(entry, dict):
        return None
    path = config.bases_root() / name
    sub = entry.get("path")
    if isinstance(sub, str) and sub:
        path = path.joinpath(*PurePosixPath(sub).parts)
    return path


def auto_base(repo_root: Path | None) -> Path | None:
    """Mapping match on the code remote, then `default_base` (MASORA_DESIGN.md §9).

    None when nothing matches; WriteError when the config is unreadable or a
    MATCHED base's checkout is missing — matched-but-broken is never silently
    skipped. Shared by the MCP write tools and the read-only `masora facts`.
    """
    data = load_user_config()
    remote = origin_remote(repo_root) if repo_root is not None else None
    if remote is not None:
        mappings = data.get("mappings")
        if isinstance(mappings, list):
            for mapping in mappings:
                if not isinstance(mapping, dict):
                    continue
                code_remote = mapping.get("code_remote")
                if not isinstance(code_remote, str):
                    continue
                if config.normalize_remote(code_remote) != config.normalize_remote(remote):
                    continue
                bases = mapping.get("bases")
                name = (
                    bases[0]
                    if isinstance(bases, list) and bases and isinstance(bases[0], str)
                    else None
                )
                if name is None:
                    continue
                path = base_dir_for_name(data, name)
                if path is None or not path.is_dir():
                    raise WriteError(
                        Diag(
                            "error",
                            E_MCP_NO_BASE,
                            f"mapping {code_remote!r} resolves to base '{name}' but {path} does"
                            " not exist (MASORA_DESIGN.md §9)",
                            str(path or config.bases_root() / name),
                        )
                    )
                return path
    default = data.get("default_base")
    if isinstance(default, str) and default:
        path = base_dir_for_name(data, default)
        if path is not None and path.is_dir():
            return path
        raise WriteError(
            Diag(
                "error",
                E_MCP_NO_BASE,
                f"default_base '{default}' is not an existing base directory (MASORA_DESIGN.md §9)",
                str(path or config.bases_root() / default),
            )
        )
    return None


def resolve_base(repo_root: Path | None, base: str | None) -> Path:
    """Explicit base first, then `auto_base` (§8-§9).

    A caller-provided base always wins; an unmatched or missing base is never
    guessed: `E-MCP-NO-BASE` asks for an explicit base.
    """
    if base is not None:
        explicit = Path(base)
        if explicit.is_dir():
            return explicit
        named = base_dir_for_name(load_user_config(), base)
        if named is not None and named.is_dir():
            return named
        raise WriteError(
            Diag(
                "error",
                E_MCP_NO_BASE,
                f"base {base!r} is neither an existing directory nor a configured base",
            )
        )
    matched = auto_base(repo_root)
    if matched is not None:
        return matched
    raise WriteError(
        Diag(
            "error",
            E_MCP_NO_BASE,
            "no base resolved: the code repo matches no [[mappings]] entry and no default_base is"
            " configured — pass an explicit base (MASORA_DESIGN.md §9)",
        )
    )


def records(base_dir: Path) -> dict[str, ParsedEvent]:
    """Validated event records by id (unparsable files are skipped — `check` reports them)."""
    return {pe.record.id: pe for pe in _parse_events(base_dir, [])}


def envelopes(base_dir: Path) -> dict[str, dict]:
    """Fold envelopes by lineage; a base that already fails `check` is refused."""
    result = check_base(base_dir)
    if result.errors:
        raise WriteError(*result.errors)
    return {envelope["lineage"]: envelope for envelope in result.envelopes}


def _scalar(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def emit_event(data: dict, indent: int = 0, parent_key: str | None = None) -> str:
    """Canonical block-style YAML (FORMAT.md §4): plain keys, quoted values,
    quoted identity keys under `snapshots`/`neighbours`."""
    pad = "  " * indent
    identity_keys = parent_key in ("neighbours", "snapshots")
    lines = []
    for key, item in data.items():
        key_text = _scalar(key) if identity_keys else str(key)
        if isinstance(item, dict):
            if item:
                lines.append(f"{pad}{key_text}:")
                lines.append(emit_event(item, indent + 1, key))
            else:
                lines.append(f"{pad}{key_text}: {{}}")
        elif isinstance(item, list):
            if item:
                lines.append(f"{pad}{key_text}:")
                lines.append(_emit_list(item, indent + 1, key))
            else:
                lines.append(f"{pad}{key_text}: []")
        else:
            lines.append(f"{pad}{key_text}: {_scalar(item)}")
    return "\n".join(lines)


def _emit_list(items: list, indent: int, parent_key: str | None) -> str:
    pad = "  " * indent
    lines = []
    for item in items:
        if isinstance(item, dict):
            text = emit_event(item, indent + 1, parent_key)
            child_pad = "  " * (indent + 1)
            first, _sep, rest = text.partition("\n")
            lines.append(f"{pad}- {first[len(child_pad) :]}" + (f"\n{rest}" if rest else ""))
        else:
            lines.append(f"{pad}- {_scalar(item)}")
    return "\n".join(lines)


def render_event(data: dict) -> str:
    return f"---\n{emit_event(data)}\n---\n"


def event_relpath(data: dict) -> str:
    """`<YYYY-MM>/<lineage>/<id>.<kind>.md` under the base (FORMAT.md §1)."""
    month = datetime.now(UTC).strftime("%Y-%m")
    return f"{month}/{data['lineage']}/{data['id']}.{data['kind']}.md"


def precheck(base_dir: Path) -> None:
    """Refuse writing onto a base that already fails `check` (FORMAT.md §6)."""
    result = check_base(base_dir)
    if result.errors:
        raise WriteError(*result.errors)


def write_and_check(base_dir: Path, data: dict) -> tuple[str, list[Diag]]:
    """Pre-check, pre-validate, write, re-validate; unlink on post-check failure.

    Returns the base-relative path and the checker warnings (they ride along).
    """
    precheck(base_dir)
    rel = event_relpath(data)
    try:
        validate_event(data, data["kind"], rel)
    except CheckFailure as exc:
        raise WriteError(exc.diag) from exc
    path = base_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_event(data), encoding="utf-8")
    result = check_base(base_dir)
    if result.errors:
        path.unlink(missing_ok=True)
        raise WriteError(*result.errors)
    return rel, result.warnings
