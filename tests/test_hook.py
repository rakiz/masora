"""Tests for `masora hook` (SessionStart freshness hook: install + behavior)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from importlib.resources import files as resources_files
from pathlib import Path

import pytest
from helpers import (
    OMIT,
    ULID_D1A,
    ULID_L1,
    ULID_L2,
    ULID_R1A,
    ULID_U1A,
    ULID_V1A,
    make_claim,
    make_doubt,
    make_verify,
    write_event,
)

from masora.cli import main
from masora.config import bases_root
from masora.hook import (
    PROMPT_USAGE_LINE,
    SESSION_USAGE_LINE,
    prompt_script_text,
    script_text,
    session_start,
    user_prompt_submit,
)
from masora.hook import run as hook_run
from masora.index import build_index, index_stale


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """EVERY test here runs against a throwaway MASORA_HOME — the hook must
    never touch the real ~/.local/share/masora or the real config."""
    home = tmp_path / "home-root" / "home"
    home.mkdir(parents=True)
    monkeypatch.setenv("MASORA_HOME", str(home))
    yield home
    monkeypatch.delenv("MASORA_HOME", raising=False)


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout.strip()


def make_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir(parents=True)
    return home


def write_config(home: Path, **bases: dict) -> None:
    lines = []
    for name, entry in bases.items():
        lines.append(f"[bases.{name}]")
        for key, value in entry.items():
            lines.append(f'{key} = "{value}"')
    (home / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_base(home: Path, origin: Path, name: str = "test") -> Path:
    base = home / "bases" / name
    subprocess.run(["git", "clone", str(origin), str(base)], capture_output=True, check=True)
    git(base, "config", "user.name", "Masora Test")
    git(base, "config", "user.email", "masora@example.invalid")
    return base


def make_origin(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True)
    return origin


def push_seed(base: Path, message: str = "seed") -> None:
    git(base, "add", "-A")
    git(base, "commit", "-m", message)
    git(base, "push", "origin", "main")


# --- install ---


def test_install_writes_script_and_claude_settings(tmp_path):
    home = make_home(tmp_path)
    (home / ".claude").mkdir()

    assert hook_run(None, home=home) == 0

    script = home / ".claude/hooks/masora_session_start.py"
    assert script.is_file()
    assert script.read_text(encoding="utf-8") == script_text()
    prompt_script = home / ".claude/hooks/masora_user_prompt_submit.py"
    assert prompt_script.is_file()
    assert prompt_script.read_text(encoding="utf-8") == prompt_script_text()
    settings = json.loads((home / ".claude/settings.json").read_text(encoding="utf-8"))
    entries = settings["hooks"]["SessionStart"]
    assert len(entries) == 1
    assert "masora_session_start.py" in entries[0]["hooks"][0]["command"]
    prompt_entries = settings["hooks"]["UserPromptSubmit"]
    assert len(prompt_entries) == 1
    assert "masora_user_prompt_submit.py" in prompt_entries[0]["hooks"][0]["command"]


def test_install_is_idempotent(tmp_path, capsys):
    home = make_home(tmp_path)
    (home / ".claude").mkdir()

    assert hook_run(None, home=home) == 0
    assert hook_run(None, home=home) == 0

    out = capsys.readouterr().out
    assert out.count("installed: ") == 3  # two scripts + settings, first run
    # Second run: two scripts + BOTH hook entries reported as already
    # registered (one "updated" line per registration).
    assert out.count("updated: ") == 4
    settings = json.loads((home / ".claude/settings.json").read_text(encoding="utf-8"))
    assert len(settings["hooks"]["SessionStart"]) == 1
    assert len(settings["hooks"]["UserPromptSubmit"]) == 1


def test_install_preserves_foreign_settings_keys(tmp_path):
    home = make_home(tmp_path)
    (home / ".claude").mkdir()
    settings = home / ".claude/settings.json"
    settings.write_text(json.dumps({"model": "opus", "hooks": {}}), encoding="utf-8")

    assert hook_run("claude", home=home) == 0

    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["model"] == "opus"
    assert len(data["hooks"]["SessionStart"]) == 1
    assert len(data["hooks"]["UserPromptSubmit"]) == 1


def test_install_unwritable_settings_prints_snippet(tmp_path, capsys):
    home = make_home(tmp_path)
    (home / ".claude").mkdir()
    (home / ".claude/settings.json").write_text("not json at all", encoding="utf-8")

    assert hook_run("claude", home=home) == 0

    out = capsys.readouterr().out
    # The script is installed, the registration degrades to the snippet —
    # never a traceback, never a broken settings file.
    assert (home / ".claude/hooks/masora_session_start.py").is_file()
    assert "manual snippet" in out
    assert "SessionStart" in out
    assert "not json at all" == (home / ".claude/settings.json").read_text(encoding="utf-8")


def test_install_opencode_prints_the_manual_snippet(tmp_path, capsys):
    home = make_home(tmp_path)
    (home / ".config" / "opencode").mkdir(parents=True)

    assert hook_run(None, home=home) == 0

    out = capsys.readouterr().out
    assert (home / ".config/opencode/hooks/masora_session_start.py").is_file()
    assert (home / ".config/opencode/hooks/masora_session_start.py").read_text(
        encoding="utf-8"
    ) == script_text()
    assert "manual step" in out
    assert "SessionStart" in out


def test_install_without_homes_says_so(tmp_path, capsys):
    home = make_home(tmp_path)

    assert hook_run(None, home=home) == 0

    out = capsys.readouterr().out
    assert "no agent-framework directory found" in out
    assert not (home / ".claude").exists()


def test_install_explicit_target_creates_it(tmp_path, capsys):
    home = make_home(tmp_path)

    assert hook_run("claude", home=home) == 0

    assert (home / ".claude/hooks/masora_session_start.py").is_file()


def test_cli_hook_unknown_target_is_refused(capsys):
    try:
        main(["hook", "install", "--target", "carrier"])
    except SystemExit as exc:
        assert exc.code != 0
    assert "masora_session_start" not in capsys.readouterr().out


# --- behavior (the shipped script's session_start) ---


def base_scenario(tmp_path: Path):
    """A configured home (the autouse fixture's MASORA_HOME) with one base
    clone + one code repo, the base pushed to its origin with one
    file-anchored claim, and a built index."""
    home = Path(os.environ["MASORA_HOME"])
    origin = make_origin(tmp_path)
    code = tmp_path / "code"
    code.mkdir()
    git(code, "init", "-b", "main")
    git(code, "config", "user.name", "Dev")
    git(code, "config", "user.email", "dev@example.invalid")
    (code / "a.txt").write_text("one\n", encoding="utf-8")
    git(code, "add", "-A")
    git(code, "commit", "-m", "one")
    (code / ".cppgraph").mkdir()

    base = make_base(home, origin)
    write_event(
        base,
        "2026-09/x/01J8Z3K0000000000000000000.claim.md",
        make_claim(ULID_L1),
    )
    push_seed(base)
    (base / "base.toml").write_text('name = "test"\n', encoding="utf-8")
    push_seed(base, "base.toml")

    write_config(home, test={"remote": str(origin)})
    build_index(base, code)
    return home, origin, base, code


def test_hook_fast_forwards_the_base(tmp_path):
    _home, origin, base, _code = base_scenario(tmp_path)
    # A second writer publishes a commit; the clone is behind.
    other = tmp_path / "other"
    subprocess.run(["git", "clone", str(origin), str(other)], capture_output=True, check=True)
    (other / "base.toml").write_text('name = "test"\n# touched\n', encoding="utf-8")
    git(other, "add", "-A")
    git(other, "commit", "-m", "upstream")
    git(other, "push", "origin", "main")
    behind = git(base, "rev-parse", "HEAD")

    assert session_start() == 0

    assert git(base, "rev-parse", "HEAD") != behind
    assert git(base, "rev-parse", "HEAD") == git(origin, "rev-parse", "refs/heads/main")


def test_hook_skips_a_diverged_base_silently(tmp_path, capsys):
    _home, _origin, base, _code = base_scenario(tmp_path)
    # Diverge the clone: a local commit origin never saw (a fetch + ff-only
    # merge cannot land it — and must never force or rebase).
    (base / "base.toml").write_text('name = "test"\n# local\n', encoding="utf-8")
    git(base, "add", "-A")
    git(base, "commit", "-m", "local")
    diverged = git(base, "rev-parse", "HEAD")

    assert session_start() == 0

    # The pull is skipped silently (no force, no rebase) — but the hook still
    # reports/rebuilds the clone's index staleness, in at most TWO lines.
    assert git(base, "rev-parse", "HEAD") == diverged
    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert len(lines) <= 2
    for line in lines:
        assert line.startswith("masora: ")


def test_hook_rebuilds_a_stale_index_and_prints_two_lines(tmp_path, capsys):
    _home, _origin, base, code = base_scenario(tmp_path)
    # Move the CODE repo: the index's code-HEAD axis goes stale, and the
    # anchored file changed, so the rebuilt index reports the lineage stale.
    (code / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
    git(code, "add", "-A")
    git(code, "commit", "-m", "two")
    assert index_stale(index_db(base, code), base, code) is True

    assert session_start() == 0

    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line]
    assert len(lines) == 2
    assert lines[0].startswith("masora: ")
    assert "stale lineage(s)" in lines[0]
    assert lines[1] == SESSION_USAGE_LINE
    assert index_stale(index_db(base, code), base, code) is False


def index_db(base: Path, code: Path) -> Path:
    from masora.index import index_db_path

    return index_db_path(base, code)


def test_hook_fresh_prints_only_the_standing_usage_line(tmp_path, capsys):
    base_scenario(tmp_path)

    assert session_start() == 0
    # Everything fresh: no stale summary, but the STANDING usage rule still
    # ships (the one line the prompt hook deliberately never nags with).
    assert capsys.readouterr().out == f"{SESSION_USAGE_LINE}\n"


def test_session_start_usage_lines_are_pinned():
    """The usage lines are part of the WITH condition (docs/EVALUATION.md
    amendment 2026-10-04) — the wording is pinned, not tweaked locally."""
    assert SESSION_USAGE_LINE == (
        "masora: recall recorded knowledge with the masora search / explain MCP"
        ' tools before investigating "what happens when X" questions.'
    )
    assert SESSION_USAGE_LINE.count("\n") == 0
    assert PROMPT_USAGE_LINE == (
        "masora: recalled knowledge for this prompt — search/explain go deeper"
        " (the masora MCP tools); cppgraph owns code structure."
    )
    assert PROMPT_USAGE_LINE.count("\n") == 0


def test_hook_silent_failure_garbage_config(tmp_path, capsys):
    home = make_home(tmp_path)
    (home / "config.toml").write_text("not [valid toml", encoding="utf-8")

    assert session_start() == 0
    assert capsys.readouterr().out == ""


def test_hook_exception_in_one_base_never_fails_the_run(tmp_path, capsys, monkeypatch):
    import masora.hook as hook_mod

    base_scenario(tmp_path)
    # The FIRST base explodes; the hook still completes and exits 0.
    monkeypatch.setattr(
        hook_mod, "_fast_forward", lambda base_dir: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert session_start() == 0
    assert "boom" not in capsys.readouterr().out


def test_shipped_script_runs_standalone(tmp_path, capsys):
    """End-to-end: the INSTALLED script, executed by a bare python, behaves —
    here against an empty home (nothing configured): exit 0, no output."""
    home = make_home(tmp_path)
    script = tmp_path / "installed.py"
    script.write_text(script_text(), encoding="utf-8")
    import os

    env = dict(os.environ, MASORA_HOME=str(home))
    proc = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, env=env, check=False
    )
    assert proc.returncode == 0
    assert proc.stdout == ""
    assert proc.stderr == ""


def test_shipped_script_carries_the_section_10_1_caps_pointer():
    text = script_text()
    assert "§10.1" in text


def test_hook_module_carries_the_named_caps():
    import masora.hook as hook_mod

    assert hook_mod.REBUILD_BUDGET_S > 0
    assert hook_mod.HOOK_GIT_TIMEOUT_S > 0
    source = Path(hook_mod.__file__).read_text(encoding="utf-8")
    assert "§10.1" in source


# --- behavior (the UserPromptSubmit recall hook) ---


def unanchored_claim(uid: str, summary: str, lineage: str | None = None, **overrides) -> dict:
    return make_claim(
        uid,
        lineage,
        summary=summary,
        anchors=OMIT,
        unanchored=True,
        unanchored_reason="No stable symbol applies",
        **overrides,
    )


def prompt_scenario(tmp_path: Path, *events: dict, fillers: int = 8) -> Path:
    """A configured home (the autouse fixture's MASORA_HOME, `default_base`)
    with one base holding the given events, a code repo, and a BUILT index.
    Filler lineages pad the corpus: the bm25 floor (PROMPT_RANK_FLOOR) is
    calibrated for a REAL base — with a two-claim corpus every idf collapses
    and no match could ever clear the floor. Returns the code repo — the
    hook's cwd."""
    home = Path(os.environ["MASORA_HOME"])
    origin = make_origin(tmp_path)
    code = tmp_path / "code"
    code.mkdir()
    git(code, "init", "-b", "main")
    git(code, "config", "user.name", "Dev")
    git(code, "config", "user.email", "dev@example.invalid")
    (code / "a.txt").write_text("one\n", encoding="utf-8")
    git(code, "add", "-A")
    git(code, "commit", "-m", "one")

    base = make_base(home, origin)
    for event in events:
        write_event(base, f"2026-09/x/{event['id']}.{event['kind']}.md", event)
    for i in range(fillers):
        uid = f"01J8Z3K{'0' * 17}{i + 10:02d}"
        write_event(
            base,
            f"2026-08/x/{uid}.claim.md",
            unanchored_claim(uid, f"Filler knowledge item {i} for corpus padding purposes"),
        )
    push_seed(base)
    (base / "base.toml").write_text('name = "test"\n', encoding="utf-8")
    push_seed(base, "base.toml")

    # default_base BEFORE the table header — a top-level key, not a
    # [bases.test] key (auto_base resolves through it, §9)
    (home / "config.toml").write_text(
        f'default_base = "test"\n\n[bases.test]\nremote = "{origin}"\n', encoding="utf-8"
    )
    build_index(base, code)
    return code


PROMPT = "How does the shard key routing decide which shard owns a document?"

LONG_A = "The shard key routing table is cached per mongos process"
LONG_B = "Resharding a collection blocks writes at the final commit phase"


def test_prompt_hook_selects_matching_claims_with_labels(tmp_path):
    from helpers import ULID_L2

    code = prompt_scenario(
        tmp_path,
        unanchored_claim(ULID_L1, LONG_A),
        unanchored_claim(ULID_L2, LONG_B),
    )

    text = user_prompt_submit(PROMPT, code)

    assert text is not None
    lines = text.splitlines()
    assert len(lines) == 3
    # The WITH-condition usage line prefixes the claims (the amendment's
    # instruction ships WITH the recalled knowledge); the claims follow,
    # one per lineage.
    assert lines[0] == PROMPT_USAGE_LINE
    assert all(line.startswith("masora: ") for line in lines[1:])
    # statuses are LABELS: unverified renders silently (its absence is not
    # evidence), the unanchored flag is a plain label
    assert f"masora: {LONG_A} [current, unanchored]" in lines
    assert f"masora: {LONG_B} [current, unanchored]" in lines


def test_prompt_hook_no_match_prints_nothing_including_no_usage_line(tmp_path):
    """Nothing matched (or the hook skipped) → NOTHING prints: the prompt
    hook never nags — the standing usage rule belongs to SessionStart."""
    code = prompt_scenario(tmp_path, unanchored_claim(ULID_L1, LONG_A))

    assert user_prompt_submit("zorblax quuxel frobnicated wibblesnaps overgremlined?", code) is None
    assert user_prompt_submit("continue", code) is None


def test_prompt_shipped_script_delivers_usage_line_and_claims_on_stdout(tmp_path):
    """Delivery regression pin (eval 2026-10-03): the hook's delivery channel
    is STDOUT ON EXIT 0 — the exact channel proven to reach the model (the
    injected text lands in the UserPromptSubmit hook_response, and claude
    hands it to the agent; the runner-side defect was transcript visibility,
    fixed by --include-hook-events, not delivery). The INSTALLED script, fed
    the real stdin payload against a built index, emits the usage line plus
    the claims on stdout and nothing on stderr, exit 0."""
    code = prompt_scenario(
        tmp_path,
        unanchored_claim(ULID_L1, LONG_A),
        unanchored_claim(ULID_L2, LONG_B),
    )
    script = tmp_path / "installed.py"
    script.write_text(prompt_script_text(), encoding="utf-8")
    home = Path(os.environ["MASORA_HOME"])
    env = dict(os.environ, MASORA_HOME=str(home))
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps({"prompt": PROMPT, "cwd": str(code)}),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stderr == ""
    lines = proc.stdout.splitlines()
    assert len(lines) == 3
    assert lines[0] == PROMPT_USAGE_LINE
    assert f"masora: {LONG_A} [current, unanchored]" in lines
    assert f"masora: {LONG_B} [current, unanchored]" in lines


def test_prompt_hook_verified_label_renders_the_source(tmp_path):
    code = prompt_scenario(
        tmp_path,
        unanchored_claim(ULID_L1, LONG_A),
        # an unanchored claim carries no anchors — the verify's snapshots
        # must mirror that (an EMPTY snapshot map: the field is required,
        # its keys must equal the anchor-identity set)
        make_verify(ULID_V1A, ULID_L1, ULID_L1, source="human", snapshots={}),
    )

    text = user_prompt_submit(PROMPT, code)

    assert text == f"{PROMPT_USAGE_LINE}\nmasora: {LONG_A} [current, unanchored, verified(human)]"


def test_prompt_hook_dedups_by_lineage(tmp_path):
    code = prompt_scenario(
        tmp_path,
        unanchored_claim(ULID_L1, LONG_A),
        # a second VERSION of the same lineage — one line maximum (a v2+
        # claim carries a reason: what changed since the first version)
        unanchored_claim(ULID_V1A, LONG_B, lineage=ULID_L1, reason="correction"),
    )

    text = user_prompt_submit(PROMPT, code)

    assert text is not None
    assert text.startswith(PROMPT_USAGE_LINE)
    assert len(text.splitlines()) == 2


def test_prompt_hook_short_prompt_is_skipped(tmp_path):
    code = prompt_scenario(tmp_path, unanchored_claim(ULID_L1, LONG_A))

    assert user_prompt_submit("continue", code) is None
    assert user_prompt_submit("a b c d", code) is None  # 4 words, under 25 chars
    assert user_prompt_submit("thanks a lot, that resolved it", code) is None  # 25+ chars, <4 words


def test_prompt_hook_no_match_prints_nothing(tmp_path):
    code = prompt_scenario(tmp_path, unanchored_claim(ULID_L1, LONG_A))

    # no shared vocabulary at all — the lexical false-positive case is the
    # floor's job, not this test's
    assert user_prompt_submit("zorblax quuxel frobnicated wibblesnaps overgremlined?", code) is None


def test_prompt_hook_refuted_renders_the_not_line(tmp_path):
    code = prompt_scenario(
        tmp_path,
        unanchored_claim(ULID_L1, LONG_A),
        make_doubt(ULID_R1A, ULID_L1, ULID_L1, kind="refute", reason="Wrong."),
    )

    text = user_prompt_submit(PROMPT, code)

    assert text == f"{PROMPT_USAGE_LINE}\nmasora NOT: {LONG_A} [refuted]"


def test_prompt_hook_caps_at_three_lines_and_names_the_caps(tmp_path):
    import masora.hook as hook_mod

    assert hook_mod.PROMPT_MAX_CLAIMS == 3
    assert hook_mod.PROMPT_TOKEN_BUDGET > 0
    assert hook_mod.PROMPT_BUDGET_S > 0
    assert hook_mod.PROMPT_MIN_CHARS > 0
    assert hook_mod.PROMPT_MIN_WORDS > 0

    code = prompt_scenario(
        tmp_path,
        unanchored_claim(ULID_L1, LONG_A),
        unanchored_claim(ULID_L2, LONG_B),
        unanchored_claim(ULID_D1A, "The shard key index build is background throttled"),
        unanchored_claim(ULID_U1A, "A shard key must start with the hashed field"),
        unanchored_claim(ULID_V1A, "Shard key patterns cannot change without resharding"),
    )

    text = user_prompt_submit(PROMPT, code)

    assert text is not None
    lines = text.splitlines()
    # usage line + at most PROMPT_MAX_CLAIMS claim lines
    assert len(lines) <= 1 + hook_mod.PROMPT_MAX_CLAIMS
    assert lines[0] == PROMPT_USAGE_LINE


def test_prompt_hook_silent_failure_on_missing_index(tmp_path):
    home = Path(os.environ["MASORA_HOME"])
    origin = make_origin(tmp_path)
    base = make_base(home, origin)
    (base / "base.toml").write_text('name = "test"\n', encoding="utf-8")
    (home / "config.toml").write_text(
        f'default_base = "test"\n\n[bases.test]\nremote = "{origin}"\n', encoding="utf-8"
    )
    code = tmp_path / "code"
    code.mkdir()

    assert user_prompt_submit(PROMPT, code) is None


def test_prompt_hook_silent_failure_on_corrupt_index(tmp_path):
    from masora.index import index_dir_for

    code = prompt_scenario(tmp_path, unanchored_claim(ULID_L1, LONG_A))
    for db in index_dir_for(bases_root() / "test").glob("*.db"):
        db.write_text("this is not a sqlite database", encoding="utf-8")

    assert user_prompt_submit(PROMPT, code) is None


def test_prompt_hook_never_builds_the_index(tmp_path):
    from masora.index import index_dir_for

    home = Path(os.environ["MASORA_HOME"])
    origin = make_origin(tmp_path)
    base = make_base(home, origin)
    (base / "base.toml").write_text('name = "test"\n', encoding="utf-8")
    (home / "config.toml").write_text(
        f'default_base = "test"\n\n[bases.test]\nremote = "{origin}"\n', encoding="utf-8"
    )
    code = tmp_path / "code"
    code.mkdir()

    assert user_prompt_submit(PROMPT, code) is None
    assert not index_dir_for(base).is_dir() or not list(index_dir_for(base).glob("*.db"))


def test_prompt_hook_silent_failure_on_broken_config(tmp_path, monkeypatch):
    import masora.hook as hook_mod

    home = make_home(tmp_path)
    (home / "config.toml").write_text("not [valid toml", encoding="utf-8")
    code = tmp_path / "code"
    code.mkdir()

    assert user_prompt_submit(PROMPT, code) is None

    # and an exception from anywhere under the hook is swallowed too
    def boom(*args):
        raise RuntimeError("boom")

    monkeypatch.setattr(hook_mod, "auto_base", boom)
    assert user_prompt_submit(PROMPT, code) is None


def test_prompt_shipped_script_runs_standalone_on_empty_home(tmp_path):
    """End-to-end: the INSTALLED prompt script, fed the Claude Code stdin
    payload, behaves against an empty home — exit 0, no output."""
    home = make_home(tmp_path)
    script = tmp_path / "installed.py"
    script.write_text(prompt_script_text(), encoding="utf-8")
    env = dict(os.environ, MASORA_HOME=str(home))
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps({"prompt": PROMPT, "cwd": str(tmp_path)}),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout == ""
    assert proc.stderr == ""


def test_prompt_shipped_script_survives_garbage_stdin(tmp_path):
    script = tmp_path / "installed.py"
    script.write_text(prompt_script_text(), encoding="utf-8")
    env = dict(os.environ, MASORA_HOME=str(make_home(tmp_path)))
    for payload in ("not json", '"a bare string"', "42", ""):
        proc = subprocess.run(
            [sys.executable, str(script)],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert proc.returncode == 0
        assert proc.stdout == ""


def test_prompt_shipped_script_matches_the_packaged_copy():
    from masora.hook import prompt_script_text as packaged

    assert (resources_files("masora") / "hooks/user_prompt_submit.py").read_text(
        encoding="utf-8"
    ) == packaged()
