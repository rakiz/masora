"""Tests for `masora status` (hermetic: MASORA_HOME sandbox, injected fetcher, no network)."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from importlib import metadata
from pathlib import Path

import pytest
from helpers import ULID_L1, ULID_V2A, make_claim, write_event

from masora import status
from masora.cli import main
from masora.config import update_check_path
from masora.status import installed_version

CONFIG = (
    '[bases.team-query]\nremote = "git@github.internal:org/query-knowledge.git"\nbranch = "main"\n'
)
SUBDIR_CONFIG = (
    '[bases.employees]\nremote = "git@github.internal:org/employees.git"\npath = "masora_mdb"\n'
)
RELEASE = {
    "tag_name": "v99.0.0",
    "html_url": "https://github.com/rakiz/masora/releases/tag/v99.0.0",
}


@pytest.fixture
def masora_home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "masora-home"
    home.mkdir()
    monkeypatch.setenv("MASORA_HOME", str(home))
    return home


@pytest.fixture
def configured_base(masora_home) -> Path:
    (masora_home / "config.toml").write_text(CONFIG, encoding="utf-8")
    clone = masora_home / "bases" / "team-query"
    write_event(
        clone,
        "2026-09/x/01J8Z3K0000000000000000000.claim.md",
        make_claim(ULID_L1),
    )
    (clone / "base.toml").write_text('name = "test-base"\ncode_remotes = []\n', encoding="utf-8")
    (clone / "deleted.toml").write_text(
        '[[deleted]]\nlineage = "01J8Z3K0000000000000000007"\n'
        'ulids = ["01J8Z3K0000000000000000007"]\n',
        encoding="utf-8",
    )
    return clone


def test_status_prints_tool_versions_and_exits_zero(masora_home, capsys):
    code = status.run(fetcher=lambda: None)

    assert code == 0
    out = capsys.readouterr().out
    assert "masora status" in out
    assert "format_version: 1" in out
    assert "facts contract_version: 1" in out
    assert "index schema_version: 5" in out
    assert "update check unavailable (offline)" in out


def test_status_lists_configured_bases_with_counts(masora_home, configured_base, capsys):
    code = status.run(fetcher=lambda: None)

    assert code == 0
    out = capsys.readouterr().out
    assert "bases: 1 configured" in out
    assert "  team-query" in out
    assert f"clone: {configured_base} (exists)" in out
    assert "remote: git@github.internal:org/query-knowledge.git" in out
    assert "events: 1 file(s), tombstones: 1 block(s)" in out
    assert "indexes: no index" in out


def test_status_reports_missing_clone(masora_home, capsys):
    (masora_home / "config.toml").write_text(SUBDIR_CONFIG, encoding="utf-8")

    code = status.run(fetcher=lambda: None)

    assert code == 0
    out = capsys.readouterr().out
    clone = masora_home / "bases" / "employees"
    assert f"clone: {clone} (missing)" in out
    assert "no index" in out


def test_status_lists_subdir_base_indexes(masora_home, capsys):
    from masora.index import build_index, index_db_path

    clone = masora_home / "bases" / "employees"
    base_dir = clone / "masora_mdb"
    write_event(base_dir, "2026-09/x/01J8Z3K0000000000000000000.claim.md", make_claim(ULID_L1))
    (base_dir / "base.toml").write_text('name = "test-base"\ncode_remotes = []\n', encoding="utf-8")
    repo = masora_home / "code"
    repo.mkdir()
    db = index_db_path(base_dir, repo)
    build_index(base_dir, repo, no_cppgraph=True)
    (masora_home / "config.toml").write_text(SUBDIR_CONFIG, encoding="utf-8")

    code = status.run(fetcher=lambda: None)

    assert code == 0
    out = capsys.readouterr().out
    assert "no index" not in out
    assert f"{db.name}: repo {repo} — " in out
    assert "events: 1 file(s), tombstones: 0 block(s)" in out


def test_status_missing_clone_with_index_states_the_rebuild(masora_home, capsys):
    import shutil

    from masora.index import build_index, index_db_path

    clone = masora_home / "bases" / "employees"
    base_dir = clone / "masora_mdb"
    write_event(base_dir, "2026-09/x/01J8Z3K0000000000000000000.claim.md", make_claim(ULID_L1))
    (base_dir / "base.toml").write_text('name = "test-base"\ncode_remotes = []\n', encoding="utf-8")
    repo = masora_home / "code"
    repo.mkdir()
    db = index_db_path(base_dir, repo)
    build_index(base_dir, repo, no_cppgraph=True)
    (masora_home / "config.toml").write_text(SUBDIR_CONFIG, encoding="utf-8")
    shutil.rmtree(masora_home / "bases")

    code = status.run(fetcher=lambda: None)

    assert code == 0
    out = capsys.readouterr().out
    assert "(missing)" in out
    missing_state = (
        f"{db.name}: repo {repo} — the clone is missing — "
        "rebuild the index after re-running masora setup"
    )
    assert missing_state in out


def test_status_reports_index_staleness_reason(masora_home, configured_base, capsys):
    from masora.index import build_index, index_db_path

    repo = configured_base.parent.parent / "code-checkout"
    repo.mkdir()
    db = index_db_path(configured_base, repo)
    build_index(configured_base, repo, no_cppgraph=True)
    connection = sqlite3.connect(db)
    connection.execute("UPDATE meta SET value = '2000-01-01T00:00:00+00:00' WHERE key = 'built_at'")
    connection.commit()
    connection.close()

    code = status.run(fetcher=lambda: None)
    assert code == 0
    out = capsys.readouterr().out
    assert f"{db.name}: repo {repo} — events written since the index build" in out


def test_status_repeats_the_degraded_context_ordering(masora_home, configured_base, capsys):
    from masora.index import build_index, index_db_path

    repo = configured_base.parent.parent / "code-checkout"
    repo.mkdir()
    db = index_db_path(configured_base, repo)
    # a second version in the lineage: both establishing SHAs exist in no repo
    # (the helpers' constant against a non-git checkout) — the build degrades
    write_event(
        configured_base,
        "2026-09/x/01J8Z3K0000000000000000005.claim.md",
        make_claim(ULID_V2A, ULID_L1, reason="code changed", summary="Second version summary"),
    )
    build_index(configured_base, repo, no_cppgraph=True)

    code = status.run(fetcher=lambda: None)

    assert code == 0
    out = capsys.readouterr().out
    assert f"{db.name}: repo {repo}" in out
    assert "context ordering: degraded in 1 lineage(s)" in out
    assert "rebuild the index from a full clone" in out


def test_status_no_index_line(masora_home, configured_base, capsys):
    code = status.run(fetcher=lambda: None)

    assert code == 0
    assert "indexes: no index" in capsys.readouterr().out


def test_status_unreadable_config_is_a_note_not_an_error(masora_home, capsys):
    (masora_home / "config.toml").write_text("not toml at all [", encoding="utf-8")

    code = status.run(fetcher=lambda: None)

    assert code == 0
    out = capsys.readouterr().out
    assert "bases: the config is unreadable" in out
    assert "update check unavailable (offline)" in out


def test_update_check_available_line_and_cache_write(masora_home, capsys):
    calls = []

    def fetcher():
        calls.append(1)
        return dict(RELEASE)

    code = status.run(force=True, fetcher=fetcher)

    assert code == 0
    out = capsys.readouterr().out
    assert f"update available: {RELEASE['tag_name']} — {RELEASE['html_url']}" in out
    assert "install: uv tool install --force git+https://github.com/rakiz/masora" in out
    cache = json.loads(update_check_path().read_text(encoding="utf-8"))
    assert cache["tag"] == "v99.0.0"
    assert cache["url"] == RELEASE["html_url"]
    assert cache["checked_at"]
    assert calls == [1]


def test_update_check_uses_fresh_cache_without_refetch(masora_home, capsys):
    status.run(force=True, fetcher=lambda: dict(RELEASE))
    capsys.readouterr()

    def refusing():
        raise AssertionError("the fetcher must not run while the cache is fresh")

    code = status.run(fetcher=refusing)

    assert code == 0
    out = capsys.readouterr().out
    assert "update available: v99.0.0" in out
    assert "offline" not in out


def test_update_check_expired_cache_refetches(masora_home, capsys):
    path = update_check_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    stale = datetime.now(UTC) - timedelta(hours=25)
    path.write_text(
        json.dumps({"checked_at": stale.isoformat(), "tag": "v0.1.0", "url": "https://x"}),
        encoding="utf-8",
    )
    calls = []

    def fetcher():
        calls.append(1)
        return dict(RELEASE)

    code = status.run(fetcher=fetcher)

    assert code == 0
    assert calls == [1]
    assert "update available: v99.0.0" in capsys.readouterr().out


def test_update_check_offline_is_a_quiet_one_liner(masora_home, capsys):
    code = status.run(fetcher=lambda: None)

    assert code == 0
    out = capsys.readouterr().out
    assert "update check unavailable (offline)" in out
    assert "update available" not in out


def test_update_check_up_to_date_line(masora_home, monkeypatch, capsys):
    monkeypatch.setattr(status, "installed_version", lambda: "0.1.0")

    code = status.run(force=True, fetcher=lambda: {"tag_name": "v0.1.0", "html_url": "https://x"})

    assert code == 0
    assert "up to date" in capsys.readouterr().out


def test_update_check_unknown_installed_version_line(masora_home, monkeypatch, capsys):
    monkeypatch.setattr(status, "installed_version", lambda: "unknown")

    code = status.run(force=True, fetcher=lambda: dict(RELEASE))

    assert code == 0
    out = capsys.readouterr().out
    assert "latest release: v99.0.0 — https://github.com/rakiz/masora/releases/tag/v99.0.0" in out
    assert "installed version: unknown" in out


def test_installed_version_falls_back_to_unknown(monkeypatch):
    def missing(name):
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr("importlib.metadata.version", missing)

    assert installed_version() == "unknown"


def test_cli_version_flag_prints_and_exits_zero(masora_home, capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])

    assert excinfo.value.code == 0
    assert capsys.readouterr().out.startswith("masora ")
