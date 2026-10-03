"""Tests for `masora union` (conflicted deleted.toml row-union rescue)."""

from __future__ import annotations

from pathlib import Path

from masora.cli import main
from masora.union import _union
from masora.union import run as union_run

L1 = "01J8Z3K0000000000000000001"
L2 = "01J8Z3K0000000000000000002"
L3 = "01J8Z3K0000000000000000003"
E1 = "01J8Z3K0000000000000000101"
E2 = "01J8Z3K0000000000000000102"


def base_with_deleted(tmp_path: Path, content: str) -> Path:
    base = tmp_path / "base"
    base.mkdir()
    (base / "base.toml").write_text('name = "test-base"\n', encoding="utf-8")
    (base / "deleted.toml").write_text(content, encoding="utf-8")
    return base


def conflict(ours: str, theirs: str) -> str:
    return f"<<<<<<< HEAD\n{ours}=======\n{theirs}>>>>>>> origin/main\n"


def test_union_merges_both_sides_deduplicating_on_lineage():
    text = (
        "# rows common to both sides survive verbatim\n"
        + conflict(
            f'[[deleted]]\nlineage = "{L1}"\nulids = ["{L1}"]\n',
            f'[[deleted]]\nlineage = "{L1}"\nulids = ["{L1}", "{L2}"]\n',
        )
        + "# trailing common row\n"
    )
    merged, counts = _union(text)
    assert counts == {"deleted": 1, "deleted_events": 0}
    assert merged.count("[[deleted]]") == 1
    assert f'ulids = ["{L1}", "{L2}"]' in merged


def test_union_preserves_ours_order_then_theirs_new_rows():
    text = conflict(
        f'[[deleted]]\nlineage = "{L2}"\nulids = ["{L2}"]\n[[deleted]]\nlineage = "{L1}"\nulids = ["{L1}"]\n',
        f'[[deleted]]\nlineage = "{L3}"\nulids = ["{L3}"]\n[[deleted]]\nlineage = "{L1}"\nulids = ["{L1}"]\n',
    )
    merged, _counts = _union(text)
    assert merged.index(f'"{L2}"') < merged.index(f'"{L1}"') < merged.index(f'"{L3}"')


def test_union_unions_deleted_events_by_event_ulid():
    text = conflict(
        f'[[deleted_events]]\nlineage = "{L1}"\nulids = ["{E1}"]\n',
        f'[[deleted_events]]\nlineage = "{L1}"\nulids = ["{E1}", "{E2}"]\n',
    )
    merged, counts = _union(text)
    assert counts == {"deleted": 0, "deleted_events": 1}
    assert f'ulids = ["{E1}", "{E2}"]' in merged


def test_union_keeps_both_tables_in_canonical_order():
    text = conflict(
        f'[[deleted_events]]\nlineage = "{L1}"\nulids = ["{E1}"]\n',
        f'[[deleted]]\nlineage = "{L2}"\nulids = ["{L2}"]\n',
    )
    merged, counts = _union(text)
    assert counts == {"deleted": 1, "deleted_events": 1}
    assert merged.index("[[deleted]]") < merged.index("[[deleted_events]]")


def test_union_refuses_a_file_without_conflict_markers(tmp_path, capsys):
    base = base_with_deleted(tmp_path, f'[[deleted]]\nlineage = "{L1}"\nulids = ["{L1}"]\n')
    original = (base / "deleted.toml").read_text(encoding="utf-8")

    assert union_run(base) == 1

    captured = capsys.readouterr()
    assert "E-UNION-NO-MARKERS" in captured.out + captured.err
    assert (base / "deleted.toml").read_text(encoding="utf-8") == original


def test_union_refuses_a_malformed_row_and_drops_nothing(tmp_path, capsys):
    # The conflict cut a row in half: the ours side has a block missing ulids.
    text = conflict(
        f'[[deleted]]\nlineage = "{L1}"\n', f'[[deleted]]\nlineage = "{L1}"\nulids = ["{L1}"]\n'
    )
    base = base_with_deleted(tmp_path, text)
    original = (base / "deleted.toml").read_text(encoding="utf-8")

    assert union_run(base) == 1

    captured = capsys.readouterr()
    assert "E-UNION-ROW" in captured.err + captured.out
    assert (base / "deleted.toml").read_text(encoding="utf-8") == original


def test_union_refuses_invalid_toml_on_theirs_side(tmp_path, capsys):
    text = conflict(
        f'[[deleted]]\nlineage = "{L1}"\nulids = ["{L1}"]\n',
        "[[deleted]]\nlineage = \n",  # not valid TOML
    )
    base = base_with_deleted(tmp_path, text)
    original = (base / "deleted.toml").read_text(encoding="utf-8")

    assert union_run(base) == 1

    assert "E-UNION-ROW" in capsys.readouterr().out
    assert (base / "deleted.toml").read_text(encoding="utf-8") == original


def test_union_cli_replaces_the_file_and_reports_counts(tmp_path, capsys):
    text = conflict(
        f'[[deleted]]\nlineage = "{L1}"\nulids = ["{L1}"]\n',
        f'[[deleted]]\nlineage = "{L2}"\nulids = ["{L2}"]\n',
    )
    base = base_with_deleted(tmp_path, text)

    assert main(["union", str(base)]) == 0

    out = capsys.readouterr().out
    assert "[[deleted]] 2 row(s), [[deleted_events]] 0 row(s)" in out
    merged = (base / "deleted.toml").read_text(encoding="utf-8")
    assert "<<<<<<<" not in merged
    assert f'"{L1}"' in merged and f'"{L2}"' in merged
    assert "post-union check" in out


def test_union_cli_leaves_the_file_when_the_check_fails(tmp_path, capsys):
    # An event file that check refuses (broken frontmatter) fails the
    # post-union check for reasons the union cannot fix — fail-closed.
    text = conflict(
        f'[[deleted]]\nlineage = "{L1}"\nulids = ["{L1}"]\n',
        f'[[deleted]]\nlineage = "{L2}"\nulids = ["{L2}"]\n',
    )
    base = base_with_deleted(tmp_path, text)
    event = base / "2026-09" / "x"
    event.mkdir(parents=True)
    (event / "01J8Z3K0000000000000000009.claim.md").write_text(
        "---\n^ invalid: [\n---\n", encoding="utf-8"
    )
    original = (base / "deleted.toml").read_text(encoding="utf-8")

    assert main(["union", str(base)]) == 1

    out = capsys.readouterr().out
    assert "E-UNION-CHECK" in out
    assert (base / "deleted.toml").read_text(encoding="utf-8") == original


def test_union_never_invokes_git(tmp_path, capsys, monkeypatch):
    """The rescue is file-surgery only: any git spawn is a test failure — the
    caller reviews and commits."""
    text = conflict(
        f'[[deleted]]\nlineage = "{L1}"\nulids = ["{L1}"]\n',
        f'[[deleted]]\nlineage = "{L2}"\nulids = ["{L2}"]\n',
    )
    base = base_with_deleted(tmp_path, text)

    def boom(*args, **kwargs):
        raise AssertionError("masora union must never run git")

    monkeypatch.setattr("masora.union.shutil.which", boom)
    monkeypatch.setattr("subprocess.run", boom)
    assert union_run(base) == 0
