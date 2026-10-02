"""`masora status`: one readable screen — tool versions, configured bases,
index drift and the cached release check (MASORA_DESIGN.md §9).

Status never fails hard: an offline or failed release check is a quiet
one-liner, a missing clone or an unreadable config is reported as-is, and the
exit code is always 0. The release check hits the GitHub releases API with a
2 s timeout, caches the result in `$MASORA_HOME/update-check.json` for 24
hours and compares the semver triplet numerically; `--force` refetches now.
The fetcher is an injectable module-level callable so tests stay hermetic.
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import tomllib
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from importlib import metadata
from pathlib import Path
from urllib.parse import quote

from . import config
from .facts import CONTRACT_VERSION
from .index import SCHEMA_VERSION, _stored_meta, index_dir_for, index_stale_reason
from .schema import SUPPORTED_FORMAT_VERSION
from .sync import git_env
from .write import base_dir_for_name

RELEASES_URL = "https://api.github.com/repos/rakiz/masora/releases/latest"
INSTALL_HINT = "uv tool install --force git+https://github.com/rakiz/masora"
UPDATE_TTL = timedelta(hours=24)


def installed_version() -> str:
    try:
        return metadata.version("masora")
    except metadata.PackageNotFoundError:
        return "unknown"


def fetch_latest_release() -> dict | None:
    """The latest GitHub release document, or None when unreachable/malformed."""
    try:
        request = urllib.request.Request(
            RELEASES_URL,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "masora"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            document = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict) or not isinstance(document.get("tag_name"), str):
        return None
    return document


def run(force: bool = False, fetcher: Callable[[], dict | None] | None = None) -> int:
    print("masora status")
    _print_tool()
    _print_bases()
    _print_update_check(force, fetch_latest_release if fetcher is None else fetcher)
    return 0


def _print_tool() -> None:
    print("tool:")
    print(f"  version: {installed_version()}")
    print(f"  format_version: {SUPPORTED_FORMAT_VERSION}")
    print(f"  facts contract_version: {CONTRACT_VERSION}")
    print(f"  index schema_version: {SCHEMA_VERSION}")


def _print_bases() -> None:
    path = config.config_path()
    if not path.is_file():
        print("bases: none configured — masora setup --base <url>")
        return
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as exc:
        print(f"bases: the config is unreadable ({exc}) — fix or remove {path}")
        return
    bases = data.get("bases")
    if not isinstance(bases, dict) or not bases:
        print("bases: none configured — masora setup --base <url>")
        return
    print(f"bases: {len(bases)} configured")
    for name in sorted(bases):
        entry = bases[name]
        if isinstance(entry, dict):
            _print_base(name, entry, data)
        else:
            print(f"  {name}: unreadable entry")


def _print_base(name: str, entry: dict, data: dict) -> None:
    clone = config.bases_root() / config.slug(name)
    base_dir = base_dir_for_name(data, name) or clone
    print(f"  {name}")
    print(f"    clone: {clone} ({'exists' if clone.is_dir() else 'missing'})")
    print(f"    remote: {_origin(clone) or _entry_remote(entry)}")
    if clone.is_dir() and base_dir.is_dir():
        events = sum(1 for p in base_dir.rglob("*.md") if ".git" not in p.parts)
        tombstones = _tombstone_blocks(base_dir)
        if tombstones is None:
            print(f"    events: {events} file(s), tombstones: unreadable")
        else:
            print(f"    events: {events} file(s), tombstones: {tombstones} block(s)")
    _print_indexes(base_dir)


def _origin(clone: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(clone), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _entry_remote(entry: dict) -> str:
    remote = entry.get("remote")
    return remote if isinstance(remote, str) and remote else "unknown"


def _tombstone_blocks(base_dir: Path) -> int | None:
    path = base_dir / "deleted.toml"
    if not path.is_file():
        return 0
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError):
        return None
    blocks = 0
    for table in ("deleted", "deleted_events"):
        value = data.get(table, [])
        if isinstance(value, list):
            blocks += len(value)
    return blocks


def _print_indexes(base_dir: Path) -> None:
    index_dir = index_dir_for(base_dir)
    databases = sorted(index_dir.glob("*.db")) if index_dir.is_dir() else []
    if not databases:
        print("    indexes: no index")
        return
    print("    indexes:")
    for db in databases:
        meta = _stored_meta(db)
        if not meta:
            print(f"      {db.name}: unreadable")
            continue
        repo_path = meta.get("repo_path") or "unknown"
        repo = Path(repo_path) if meta.get("repo_path") else None
        if base_dir.is_dir():
            reason = index_stale_reason(db, base_dir, repo)
            state = reason if reason else "fresh"
        else:
            state = "the clone is missing — rebuild the index after re-running masora setup"
        print(f"      {db.name}: repo {repo_path} — {state}")
        degraded = _degraded_lineages(db)
        if degraded:
            print(
                f"        context ordering: degraded in {degraded} lineage(s) — rebuild the"
                " index from a full clone (W-CTX-DEGRADED)"
            )


def _degraded_lineages(db: Path) -> int:
    """The count of `context_ordering: degraded` lineage rows; 0 when the index
    predates the column or is unreadable (the index is a derived cache)."""
    try:
        conn = sqlite3.connect(f"file:{quote(str(db))}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT count(*) FROM lineages WHERE context_ordering = 'degraded'"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return 0
    return row[0] if row else 0


def _print_update_check(force: bool, fetch: Callable[[], dict | None]) -> None:
    print("update check:")
    cache = _read_cache(config.update_check_path())
    if not force and cache is not None and _cache_fresh(cache):
        _print_release(cache["tag"], cache["url"])
        return
    release = fetch()
    if release is None:
        print("  update check unavailable (offline)")
        return
    _write_cache(config.update_check_path(), release)
    _print_release(release.get("tag_name") or "", release.get("html_url") or RELEASES_URL)


def _print_release(tag: str, url: str) -> None:
    latest = _triplet(tag)
    installed = _triplet(installed_version())
    if latest is None or installed is None:
        print(f"  latest release: {tag} — {url} (installed version: {installed_version()})")
    elif latest > installed:
        print(f"  update available: {tag} — {url}")
        print(f"  install: {INSTALL_HINT}")
    else:
        print("  up to date")


def _triplet(version: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", version)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _read_cache(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    tag, url = data.get("tag"), data.get("url")
    if not isinstance(tag, str) or not isinstance(url, str):
        return None
    try:
        moment = datetime.fromisoformat(data.get("checked_at"))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return {"checked_at": moment, "tag": tag, "url": url}


def _cache_fresh(cache: dict) -> bool:
    return datetime.now(UTC) - cache["checked_at"] < UPDATE_TTL


def _write_cache(path: Path, release: dict) -> None:
    document = {
        "checked_at": datetime.now(UTC).isoformat(),
        "tag": release.get("tag_name") or "",
        "url": release.get("html_url") or RELEASES_URL,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding="utf-8")
    except OSError:
        pass
