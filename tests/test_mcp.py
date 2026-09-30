"""Tests for `masora mcp` (subprocess-driven stdio server, hermetic MASORA_HOME)."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import pytest
from helpers import SHA, make_claim, write_event, write_graph_db

from masora.checker import check_base
from masora.frontmatter import load_frontmatter
from masora.index import build_index, index_db_path, normalize_source
from masora.sync import git_env
from masora.ulid import new_ulid
from masora.write import WriteError, write_and_check

REPO_ROOT = Path(__file__).resolve().parents[1]
PIN = "2025-06-18"
SERVER_CODE = "import sys; from masora.cli import main; sys.exit(main(['mcp']))"

SYM_A = "scip-clang cxx . . mongo/Engine#start()."
SYM_B = "scip-clang cxx . . mongo/Engine#stop()."
SYM_C = "scip-clang cxx . . mongo/Util#tick()."
SOURCE = """namespace mongo {
void Engine::start() {
    stop();
    tick();
}
void Engine::stop() {
}
void Util::tick() {
}
}
"""


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout.strip()


class Server:
    def __init__(self, env: dict):
        self.proc = subprocess.Popen(
            [sys.executable, "-c", SERVER_CODE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )

    def send(self, line: str) -> None:
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def recv(self) -> dict:
        line = self.proc.stdout.readline()
        assert line, "server closed the stream"
        return json.loads(line)

    def request(self, method: str, params: dict | None = None, id: int = 1) -> dict:
        message: dict = {"jsonrpc": "2.0", "id": id, "method": method}
        if params is not None:
            message["params"] = params
        self.send(json.dumps(message))
        return self.recv()

    def notify(self, method: str, params: dict | None = None) -> None:
        message: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self.send(json.dumps(message))

    def call(self, name: str, arguments: dict, id: int = 1) -> dict:
        return self.request("tools/call", {"name": name, "arguments": arguments}, id=id)

    def ready(self) -> None:
        response = self.request("initialize", {"protocolVersion": PIN})
        assert response["result"]["protocolVersion"] == PIN
        self.notify("notifications/initialized")

    def tool(self, name: str, arguments: dict) -> tuple[str, bool]:
        response = self.call(name, arguments)
        assert "result" in response, response
        return response["result"]["content"][0]["text"], response["result"].get("isError", False)

    def finish(self) -> tuple[int, str]:
        self.proc.stdin.close()
        self.proc.wait(timeout=15)
        return self.proc.returncode, self.proc.stderr.read()


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def env(home: Path, monkeypatch) -> dict:
    value = dict(os.environ)
    value["MASORA_HOME"] = str(home)
    value["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + value.get("PYTHONPATH", "")
    monkeypatch.setenv("MASORA_HOME", str(home))
    return value


@pytest.fixture
def server(env):
    proc = Server(env)
    yield proc
    if proc.proc.poll() is None:
        proc.proc.stdin.close()
        proc.proc.wait(timeout=15)


@pytest.fixture
def code_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "mongo").mkdir(parents=True)
    (repo / "mongo" / "engine.cpp").write_text(SOURCE, encoding="utf-8")
    repo.joinpath(".cppgraph").mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Masora Test")
    git(repo, "config", "user.email", "masora@example.invalid")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "src")
    head = git(repo, "rev-parse", "HEAD")
    write_graph_db(
        repo / ".cppgraph" / "repo.graph.db",
        commit=head,
        symbols={
            SYM_A: ("mongo/engine.cpp", 1, 4),
            SYM_B: ("mongo/engine.cpp", 5, 6),
            SYM_C: ("mongo/engine.cpp", 7, 8),
        },
        calls=[(SYM_A, SYM_B), (SYM_A, SYM_C)],
    )
    return repo, head


@pytest.fixture
def base(tmp_path: Path) -> Path:
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    git(base_dir, "init", "-b", "main")
    git(base_dir, "config", "user.name", "Masora Test")
    git(base_dir, "config", "user.email", "masora@example.invalid")
    (base_dir / "base.toml").write_text('name = "test-base"\n', encoding="utf-8")
    git(base_dir, "add", "-A")
    git(base_dir, "commit", "-m", "init")
    return base_dir


def note_args(repo: Path, base_dir: Path | None, **overrides) -> dict:
    args = {
        "statement": "start() must run before stop() in bring-up.",
        "summary": "Bring-up order: start before stop",
        "repo_root": str(repo),
        "base": str(base_dir) if base_dir is not None else None,
        "anchors": [SYM_A, "tick"],
    }
    args.update(overrides)
    return args


def later_ulid(uid: str) -> str:
    candidate = new_ulid()
    while candidate <= uid:
        candidate = new_ulid()
    return candidate


def write_v2(base_dir: Path, v1_rel: str, v2_id: str) -> str:
    month, lineage = v1_rel.split("/")[:2]
    v1 = load_frontmatter((base_dir / v1_rel).read_text(encoding="utf-8"), v1_rel)
    v2_rel = f"{month}/{lineage}/{v2_id}.claim.md"
    write_event(
        base_dir,
        v2_rel,
        make_claim(
            v2_id,
            lineage=v1["lineage"],
            reason="v2: the code changed",
            anchors=v1["anchors"],
            summary="Second version",
        ),
    )
    return v2_rel


def test_handshake_tools_list_shape(server):
    response = server.request("initialize", {"protocolVersion": PIN})
    assert response["result"]["protocolVersion"] == PIN
    assert response["result"]["serverInfo"]["name"] == "masora"
    assert response["result"]["capabilities"] == {"tools": {}}
    server.notify("notifications/initialized")
    listing = server.request("tools/list")
    assert [tool["name"] for tool in listing["result"]["tools"]] == [
        "note",
        "verify",
        "doubt",
        "undoubt",
        "refute",
        "search",
        "list_stale",
    ]
    schemas = {tool["name"]: tool["inputSchema"] for tool in listing["result"]["tools"]}
    assert schemas["note"]["required"] == ["statement", "summary", "repo_root"]
    assert schemas["verify"]["required"] == ["id", "evidence", "repo_root"]
    assert schemas["doubt"]["required"] == ["id", "reason", "repo_root"]
    assert schemas["undoubt"]["required"] == ["id", "reason", "repo_root"]
    assert schemas["refute"]["required"] == ["id", "reason", "repo_root"]
    assert schemas["search"]["required"] == ["query"]
    assert schemas["list_stale"]["required"] == []
    assert all(schema["additionalProperties"] is False for schema in schemas.values())


def test_initialize_negotiates_other_version(server):
    response = server.request("initialize", {"protocolVersion": "1999-01-01"})
    assert response["result"]["protocolVersion"] == PIN
    assert response["result"]["serverInfo"]["name"] == "masora"
    assert server.request("tools/list", id=2)["id"] == 2


def test_initialize_malformed_params_refused(server):
    assert server.request("initialize", {})["error"]["code"] == -32602
    assert server.request("initialize", {"protocolVersion": 42})["error"]["code"] == -32602
    assert (
        server.request("initialize", {"protocolVersion": PIN})["result"]["protocolVersion"] == PIN
    )


def test_unknown_method_and_notification_shapes(server):
    server.notify("notifications/initialized")
    assert server.request("resources/list")["error"]["code"] == -32601
    server.notify("some/unknownNotification")
    assert server.request("tools/list", id="x")["id"] == "x"


def test_malformed_json_survives_and_reports(server):
    server.send('{"jsonrpc": "2.0", "oops')
    response = server.recv()
    assert response["error"]["code"] == -32700
    assert response["id"] is None
    assert server.request("tools/list", id=2)["id"] == 2
    code, stderr = server.finish()
    assert code == 0
    assert "W-MCP-PROTO" in stderr


def test_non_object_line_is_invalid_request(server):
    server.send("42")
    assert server.recv()["error"]["code"] == -32600
    server.send('{"jsonrpc": "2.0", "id": 3}')
    assert server.recv()["error"]["code"] == -32600


def test_unknown_tool_is_invalid_params(server):
    response = server.call("nope", {})
    assert response["error"]["code"] == -32602
    assert "nope" in response["error"]["message"]


def test_note_happy_path_writes_canonical_event(server, code_repo, base):
    repo, head = code_repo
    server.ready()
    text, is_error = server.tool("note", note_args(repo, base))
    assert is_error is False
    lines = text.splitlines()
    assert lines[0].startswith("wrote 2026-")
    uid = next(line for line in lines if line.startswith("id ")).split()[1]
    lineage = next(line for line in lines if line.startswith("lineage ")).split()[1]
    assert uid == lineage
    rel = lines[0].removeprefix("wrote ")
    assert rel == (
        f"{datetime.now(UTC).strftime('%Y-%m')}/bring-up-order-start-{uid}/{uid}.claim.md"
    )
    path = base / rel
    assert path.is_file()
    raw = path.read_text(encoding="utf-8")
    assert raw.startswith("---\n") and raw.endswith("---\n")
    assert f'id: "{uid}"' in raw and 'kind: "claim"' in raw
    data = load_frontmatter(raw, rel)
    assert data["class"] == "semantic" and data["source"] == "llm"
    assert data["summary"] == "Bring-up order: start before stop"
    assert data["recorded_at"] == {"commit": head, "graph_commit": head}
    assert data["unanchored"] is False
    assert [anchor["identity"] for anchor in data["anchors"]] == [SYM_A, SYM_C]
    first = data["anchors"][0]
    assert first["fingerprint"] == digest(normalize_source("\n".join(SOURCE.splitlines()[1:5])))
    assert first["snapshot"]["edges"] == digest("\n".join(sorted([SYM_B, SYM_C])))
    assert first["snapshot"]["neighbours"] == {
        SYM_B: digest(""),
        SYM_C: digest(""),
    }
    assert check_base(base).errors == []


def test_note_human_name_from_base_git_config(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    text, is_error = server.tool("note", note_args(repo, base, source="human"))
    assert is_error is False
    rel = text.splitlines()[0].removeprefix("wrote ")
    data = load_frontmatter((base / rel).read_text(encoding="utf-8"), rel)
    assert data["source"] == "human"
    assert data["name"] == "Masora Test"
    assert "effort" not in data


def test_note_human_name_absent_when_git_config_unset(code_repo, env, tmp_path):
    repo, _head = code_repo
    bare = tmp_path / "bare-base"
    bare.mkdir()
    git(bare, "init", "-b", "main")
    git(bare, "add", "-A")
    # one-off identity for the commit only: the repo config stays without user.name
    git(
        bare,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "init",
    )
    hermetic = dict(env)
    hermetic["GIT_CONFIG_GLOBAL"] = "/dev/null"
    hermetic["GIT_CONFIG_SYSTEM"] = "/dev/null"
    server_env = Server(hermetic)
    try:
        server_env.ready()
        text, is_error = server_env.tool("note", note_args(repo, bare, source="human"))
        assert is_error is False
        rel = text.splitlines()[0].removeprefix("wrote ")
        data = load_frontmatter((bare / rel).read_text(encoding="utf-8"), rel)
        assert data["source"] == "human"
        assert "name" not in data
    finally:
        server_env.proc.stdin.close()
        server_env.proc.wait(timeout=15)


def test_note_llm_name_and_effort_from_tool_params(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    text, is_error = server.tool("note", note_args(repo, base, name="glm-5p3-flash", effort="high"))
    assert is_error is False
    rel = text.splitlines()[0].removeprefix("wrote ")
    data = load_frontmatter((base / rel).read_text(encoding="utf-8"), rel)
    assert data["source"] == "llm"
    assert data["name"] == "glm-5p3-flash"
    assert data["effort"] == "high"


def test_note_effort_on_human_source_refused(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    text, is_error = server.tool("note", note_args(repo, base, source="human", effort="high"))
    assert is_error is True
    assert "E-PROVENANCE" in text and "effort" in text
    assert not list(base.rglob("*.md"))


def test_verify_effort_on_human_source_refused(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    note_text, _ = server.tool("note", note_args(repo, base))
    uid = note_text.splitlines()[1].split()[1]
    text, is_error = server.tool(
        "verify",
        {
            "id": uid,
            "evidence": ["x"],
            "repo_root": str(repo),
            "base": str(base),
            "source": "human",
            "effort": "low",
        },
    )
    assert is_error is True
    assert "E-PROVENANCE" in text
    assert not list(base.rglob("*.verify.md"))


def test_verify_graph_source_not_writable_via_mcp(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    note_text, _ = server.tool("note", note_args(repo, base))
    uid = note_text.splitlines()[1].split()[1]
    text, is_error = server.tool(
        "verify",
        {
            "id": uid,
            "evidence": ["x"],
            "repo_root": str(repo),
            "base": str(base),
            "source": "graph",
        },
    )
    assert is_error is True
    assert "E-MCP-ARGS" in text and "source" in text
    assert not list(base.rglob("*.verify.md"))


def test_verify_human_uses_git_config_name_and_renders_verified_human(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    note_text, _ = server.tool("note", note_args(repo, base))
    uid = note_text.splitlines()[1].split()[1]
    text, is_error = server.tool(
        "verify",
        {
            "id": uid,
            "evidence": ["I read the code"],
            "repo_root": str(repo),
            "base": str(base),
            "source": "human",
        },
    )
    assert is_error is False
    rel = text.splitlines()[0].removeprefix("wrote ")
    data = load_frontmatter((base / rel).read_text(encoding="utf-8"), rel)
    assert data["source"] == "human" and data["name"] == "Masora Test"
    (status,) = build_index(base, repo).statuses
    assert status.verification == "verified(human)"


def test_verify_llm_effort_recorded_and_rendered(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    note_text, _ = server.tool("note", note_args(repo, base))
    uid = note_text.splitlines()[1].split()[1]
    text, is_error = server.tool(
        "verify",
        {
            "id": uid,
            "evidence": ["replay: 2 edges, expected 2"],
            "repo_root": str(repo),
            "base": str(base),
            "name": "glm-5p3-flash",
            "effort": "medium",
        },
    )
    assert is_error is False
    rel = text.splitlines()[0].removeprefix("wrote ")
    data = load_frontmatter((base / rel).read_text(encoding="utf-8"), rel)
    assert data["source"] == "llm" and data["name"] == "glm-5p3-flash"
    assert data["effort"] == "medium"
    (status,) = build_index(base, repo).statuses
    assert status.verification == "verified(llm)"


def test_note_behind_head_graph_refuses_and_writes_nothing(server, code_repo, base):
    repo, _head = code_repo
    behind = write_graph_db(
        repo / ".cppgraph" / "behind.graph.db",
        commit=SHA,
        symbols={SYM_A: ("mongo/engine.cpp", 1, 4)},
        calls=[],
    )
    os.utime(behind, (2_000_000_000, 2_000_000_000))
    server.ready()
    text, is_error = server.tool("note", note_args(repo, base))
    assert is_error is True
    assert "E-MCP-GRAPH" in text and "re-index" in text
    assert not list(base.rglob("*.md"))


def test_note_without_graph_refuses_anchors_but_writes_unanchored(server, tmp_path, base):
    repo = tmp_path / "nograph"
    (repo / "mongo").mkdir(parents=True)
    (repo / "mongo" / "engine.cpp").write_text(SOURCE, encoding="utf-8")
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Masora Test")
    git(repo, "config", "user.email", "masora@example.invalid")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "src")
    head = git(repo, "rev-parse", "HEAD")
    server.ready()
    text, is_error = server.tool("note", note_args(repo, base))
    assert is_error is True
    assert "E-MCP-GRAPH" in text and "re-index" in text
    anchored_path = list(base.rglob("*.md"))
    assert anchored_path == []
    text, is_error = server.tool(
        "note",
        note_args(repo, base, anchors=None, unanchored=True, unanchored_reason="no anchor applies"),
    )
    assert is_error is False
    (rel_line,) = [line for line in text.splitlines() if line.startswith("wrote ")]
    data = load_frontmatter(
        (base / rel_line.removeprefix("wrote ")).read_text(encoding="utf-8"), "x"
    )
    assert data["unanchored"] is True
    assert data["anchors"] == []
    assert data["unanchored_reason"] == "no anchor applies"
    assert data["recorded_at"]["commit"] == head
    assert data["recorded_at"]["graph_commit"] is None
    assert check_base(base).errors == []


def test_note_ambiguous_anchor_lists_candidates_and_writes_nothing(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    text, is_error = server.tool("note", note_args(repo, base, anchors=["Engine"]))
    assert is_error is True
    assert "E-MCP-ANCHOR" in text
    assert SYM_A in text and SYM_B in text
    assert not list(base.rglob("*.md"))


def test_note_unknown_anchor_refused(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    text, is_error = server.tool("note", note_args(repo, base, anchors=["no-such-symbol"]))
    assert is_error is True
    assert "E-MCP-ANCHOR" in text and "not found" in text
    assert not list(base.rglob("*.md"))


def test_note_requires_anchors_or_explicit_unanchored(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    text, is_error = server.tool("note", note_args(repo, base, anchors=None))
    assert is_error is True
    assert "E-MCP-ARGS" in text
    text, is_error = server.tool("note", note_args(repo, base, anchors=None, unanchored=True))
    assert is_error is True
    assert "E-MCP-ARGS" in text


def test_note_without_git_head_refused(server, tmp_path, base):
    plain = tmp_path / "plain"
    plain.mkdir()
    server.ready()
    text, is_error = server.tool(
        "note", note_args(plain, base, anchors=None, unanchored=True, unanchored_reason="r")
    )
    assert is_error is True
    assert "E-MCP-ARGS" in text and "HEAD" in text


def test_base_resolution_matrix(server, code_repo, tmp_path, home, base):
    repo, _head = code_repo
    git(repo, "remote", "add", "origin", "git@github.internal:org/proj.git")
    server.ready()
    mapped = home / "bases" / "team"
    mapped.mkdir(parents=True)
    (home / "config.toml").write_text(
        "[[mappings]]\n"
        'code_remote = "https://GitHub.internal/org/proj.git"\n'
        'bases = ["team"]\n\n'
        "[bases.team]\n"
        'remote = "git@github.internal:org/knowledge.git"\n',
        encoding="utf-8",
    )
    text, is_error = server.tool("note", note_args(repo, base))
    assert is_error is False
    rel = text.splitlines()[0].removeprefix("wrote ")
    assert (base / rel).is_file()
    assert not (mapped / rel).exists()
    text, is_error = server.tool("note", note_args(repo, None))
    assert is_error is False
    rel = text.splitlines()[0].removeprefix("wrote ")
    assert (mapped / rel).is_file()
    assert not (base / rel).exists()

    solo = home / "bases" / "solo"
    solo.mkdir(parents=True)
    (home / "config.toml").write_text(
        'default_base = "solo"\n\n[bases.solo]\nremote = "git@github.internal:org/solo.git"\n',
        encoding="utf-8",
    )
    text, is_error = server.tool("note", note_args(repo, None))
    assert is_error is False
    rel = text.splitlines()[0].removeprefix("wrote ")
    assert (solo / rel).is_file()


def test_base_refusal_asks_for_explicit_base_then_accepts_it(server, code_repo, home, base):
    repo, _head = code_repo
    server.ready()
    text, is_error = server.tool("note", note_args(repo, None))
    assert is_error is True
    assert "E-MCP-NO-BASE" in text and "explicit base" in text
    text, is_error = server.tool("note", note_args(repo, base))
    assert is_error is False


def test_base_refusal_for_unknown_explicit_base(server, code_repo, home, base):
    repo, _head = code_repo
    server.ready()
    text, is_error = server.tool("note", note_args(repo, str(home / "missing")))
    assert is_error is True
    assert "E-MCP-NO-BASE" in text
    assert not list(base.rglob("*.md"))


def test_verify_round_trip_moves_index_status(server, code_repo, base):
    repo, head = code_repo
    server.ready()
    note_text, _ = server.tool("note", note_args(repo, base))
    uid = note_text.splitlines()[1].split()[1]
    text, is_error = server.tool(
        "verify",
        {
            "id": uid,
            "evidence": ["replay: 2 edges, expected 2"],
            "repo_root": str(repo),
            "base": str(base),
        },
    )
    assert is_error is False
    lines = text.splitlines()
    verify_id = lines[1].split()[1]
    rel = lines[0].removeprefix("wrote ")
    assert rel.endswith(f"{verify_id}.verify.md")
    assert (
        rel.rsplit("/", 1)[0] == note_text.splitlines()[0].removeprefix("wrote ").rsplit("/", 1)[0]
    )
    data = load_frontmatter((base / rel).read_text(encoding="utf-8"), rel)
    assert data["targets"] == uid
    assert data["source"] == "llm"
    assert data["verified_at"] == {"commit": head, "graph_commit": head}
    assert sorted(data["snapshots"]) == sorted([SYM_A, SYM_C])
    assert data["snapshots"][SYM_A]["edges"] == digest("\n".join(sorted([SYM_B, SYM_C])))
    result = build_index(base, repo)
    assert result.errors == []
    (status,) = result.statuses
    assert status.resolution == "current"
    assert status.verification == "verified(llm)"
    assert status.displayed == uid


def test_verify_by_lineage_targets_displayed_version(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    note_text, _ = server.tool("note", note_args(repo, base))
    uid = note_text.splitlines()[1].split()[1]
    text, is_error = server.tool(
        "verify", {"id": uid, "evidence": ["ok"], "repo_root": str(repo), "base": str(base)}
    )
    assert is_error is False
    lineage = text.splitlines()[2].split()[1]
    assert lineage == uid
    text, is_error = server.tool(
        "verify",
        {"id": lineage, "evidence": ["re-verified"], "repo_root": str(repo), "base": str(base)},
    )
    assert is_error is False
    rel = text.splitlines()[0].removeprefix("wrote ")
    data = load_frontmatter((base / rel).read_text(encoding="utf-8"), rel)
    assert data["targets"] == uid


def test_verify_unknown_id(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    text, is_error = server.tool(
        "verify",
        {
            "id": "01J8Z3K0000000000000000009",
            "evidence": ["x"],
            "repo_root": str(repo),
            "base": str(base),
        },
    )
    assert is_error is True
    assert "E-MCP-UNKNOWN-ID" in text


def test_verify_wrong_target_kind_is_arg_error(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    note_text, _ = server.tool("note", note_args(repo, base))
    uid = note_text.splitlines()[1].split()[1]
    text, is_error = server.tool(
        "verify",
        {
            "id": uid,
            "evidence": ["x"],
            "repo_root": str(repo),
            "base": str(base),
            "source": "human",
        },
    )
    assert is_error is False
    verify_id = text.splitlines()[1].split()[1]
    text, is_error = server.tool(
        "verify", {"id": verify_id, "evidence": ["x"], "repo_root": str(repo), "base": str(base)}
    )
    assert is_error is True
    assert "E-MCP-ARGS" in text and "claim" in text


def test_verify_refuses_changed_fingerprints(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    note_text, _ = server.tool("note", note_args(repo, base))
    uid = note_text.splitlines()[1].split()[1]
    (repo / "mongo" / "engine.cpp").write_text(
        SOURCE.replace("    stop();", "    halt();"), encoding="utf-8"
    )
    text, is_error = server.tool(
        "verify", {"id": uid, "evidence": ["x"], "repo_root": str(repo), "base": str(base)}
    )
    assert is_error is True
    assert "E-MCP-DRIFT" in text and "new claim version" in text
    assert not list(base.rglob("*.verify.md"))


def test_doubt_round_trip_through_index(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    note_text, _ = server.tool("note", note_args(repo, base))
    uid = note_text.splitlines()[1].split()[1]
    verify_text, _ = server.tool(
        "verify", {"id": uid, "evidence": ["ok"], "repo_root": str(repo), "base": str(base)}
    )
    verify_id = verify_text.splitlines()[1].split()[1]
    text, is_error = server.tool(
        "doubt",
        {
            "id": verify_id,
            "reason": "I ran the case; the summary overstates it.",
            "repo_root": str(repo),
            "base": str(base),
            "source": "human",
        },
    )
    assert is_error is False
    doubt_id = text.splitlines()[1].split()[1]
    rel = text.splitlines()[0].removeprefix("wrote ")
    data = load_frontmatter((base / rel).read_text(encoding="utf-8"), rel)
    assert data["kind"] == "doubt" and data["targets"] == verify_id and data["source"] == "human"
    (status,) = build_index(base, repo).statuses
    assert status.doubted is True
    text, is_error = server.tool(
        "undoubt",
        {"id": doubt_id, "reason": "Re-ran: it holds.", "repo_root": str(repo), "base": str(base)},
    )
    assert is_error is False
    (status,) = build_index(base, repo).statuses
    assert status.doubted is False
    assert status.verification == "verified(llm)"


def test_doubt_by_lineage_resolves_active_verify(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    note_text, _ = server.tool("note", note_args(repo, base))
    uid = note_text.splitlines()[1].split()[1]
    server.tool(
        "verify", {"id": uid, "evidence": ["ok"], "repo_root": str(repo), "base": str(base)}
    )
    text, is_error = server.tool(
        "doubt", {"id": uid, "reason": "Doubtful.", "repo_root": str(repo), "base": str(base)}
    )
    assert is_error is False
    rel = text.splitlines()[0].removeprefix("wrote ")
    data = load_frontmatter((base / rel).read_text(encoding="utf-8"), rel)
    assert data["kind"] == "doubt"
    assert data["targets"] != uid


def test_doubt_without_active_verify_refused(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    note_text, _ = server.tool("note", note_args(repo, base))
    uid = note_text.splitlines()[1].split()[1]
    text, is_error = server.tool(
        "doubt", {"id": uid, "reason": "Doubtful.", "repo_root": str(repo), "base": str(base)}
    )
    assert is_error is True
    assert "E-MCP-UNKNOWN-ID" in text and "no active verify" in text
    assert not list(base.rglob("*.doubt.md"))


def test_undoubt_requires_doubt_id(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    note_text, _ = server.tool("note", note_args(repo, base))
    uid = note_text.splitlines()[1].split()[1]
    server.tool(
        "verify", {"id": uid, "evidence": ["ok"], "repo_root": str(repo), "base": str(base)}
    )
    text, is_error = server.tool(
        "undoubt", {"id": uid, "reason": "x", "repo_root": str(repo), "base": str(base)}
    )
    assert is_error is True
    assert "E-MCP-ARGS" in text and "doubt" in text


def test_refute_round_trip_through_index(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    note_text, _ = server.tool("note", note_args(repo, base))
    uid = note_text.splitlines()[1].split()[1]
    text, is_error = server.tool(
        "refute",
        {
            "id": uid,
            "reason": "Contradicted by replay: the callee list changed.",
            "repo_root": str(repo),
            "base": str(base),
            "evidence": ["cppgraph .calls replay: 0 of 2 edges"],
        },
    )
    assert is_error is False
    rel = text.splitlines()[0].removeprefix("wrote ")
    data = load_frontmatter((base / rel).read_text(encoding="utf-8"), rel)
    assert data["kind"] == "refute" and data["targets"] == uid
    (status,) = build_index(base, repo).statuses
    assert status.resolution == "none"


def test_refute_by_lineage_targets_displayed(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    note_text, _ = server.tool("note", note_args(repo, base))
    uid = note_text.splitlines()[1].split()[1]
    text, is_error = server.tool(
        "refute", {"id": uid, "reason": "Wrong.", "repo_root": str(repo), "base": str(base)}
    )
    assert is_error is False
    rel = text.splitlines()[0].removeprefix("wrote ")
    data = load_frontmatter((base / rel).read_text(encoding="utf-8"), rel)
    assert data["targets"] == uid


def test_search_auto_builds_and_renders_statuses(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    server.tool("note", note_args(repo, base))
    text, is_error = server.tool(
        "search", {"query": "bring", "repo_root": str(repo), "base": str(base)}
    )
    assert is_error is False
    assert text.splitlines()[0] == "1 match(es) in 1 lineage(s)"
    assert "[current unverified flags: -]" in text.splitlines()[1]
    assert index_db_path(base, repo).is_file()


def test_search_surfaces_staleness_without_rebuilding(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    server.tool("note", note_args(repo, base))
    server.tool("search", {"query": "bring", "repo_root": str(repo), "base": str(base)})
    db = index_db_path(base, repo)
    before = db.stat().st_mtime_ns
    git(base, "add", "-A")
    git(base, "commit", "-m", "pending")
    text, is_error = server.tool(
        "search", {"query": "bring", "repo_root": str(repo), "base": str(base)}
    )
    assert is_error is False
    assert "W-IDX-STALE" in text.splitlines()[0]
    assert db.stat().st_mtime_ns == before


def test_search_freshness_axis_catches_uncommitted_note(server, code_repo, base):
    """The live-rollout freeze, end-to-end: note after index build → W-IDX-STALE names it."""
    repo, _head = code_repo
    server.ready()
    server.tool("note", note_args(repo, base))
    first, is_error = server.tool(
        "search", {"query": "bring", "repo_root": str(repo), "base": str(base)}
    )
    assert is_error is False
    assert "W-IDX-STALE" not in first  # the build postdates the note

    server.tool("note", note_args(repo, base, summary="Second note about bring-up"))
    # deterministic freshness: push the new note's mtime past built_at + tolerance
    # (the real gap is milliseconds — the axis fires only ~2 s after the build)
    db = index_db_path(base, repo)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        (raw,) = conn.execute("SELECT value FROM meta WHERE key = 'built_at'").fetchone()
    finally:
        conn.close()
    built = datetime.fromisoformat(raw).timestamp()
    for path in base.rglob("*.claim.md"):
        os.utime(path, (built + 5, built + 5))
    text, is_error = server.tool(
        "search", {"query": "bring", "repo_root": str(repo), "base": str(base)}
    )
    assert is_error is False
    assert "W-IDX-STALE" in text.splitlines()[0]
    assert "events written since the index build" in text.splitlines()[0]


def test_search_invalid_query_is_tool_error(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    text, is_error = server.tool(
        "search", {"query": "a AND (", "repo_root": str(repo), "base": str(base)}
    )
    assert is_error is True
    assert "E-IDX-QUERY" in text


def test_list_stale_lists_non_current_lineages(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    server.tool("note", note_args(repo, base))
    (repo / "mongo" / "engine.cpp").write_text(
        SOURCE.replace("    stop();", "    halt();"), encoding="utf-8"
    )
    text, is_error = server.tool("list_stale", {"repo_root": str(repo), "base": str(base)})
    assert is_error is False
    lines = text.splitlines()
    assert lines[0] == "1 stale lineage(s)"
    assert "[stale unverified flags: -]" in lines[1]
    assert "Bring-up order" in lines[1]


def test_list_stale_empty_base(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    text, is_error = server.tool("list_stale", {"repo_root": str(repo), "base": str(base)})
    assert is_error is False
    assert text == "no stale lineages"


def test_write_tools_require_repo_root(server, code_repo, base):
    _repo, _head = code_repo
    server.ready()
    text, is_error = server.tool(
        "note",
        {
            "statement": "s",
            "summary": "s",
            "base": str(base),
        },
    )
    assert is_error is True
    assert "E-MCP-ARGS" in text and "repo_root" in text


def test_verify_by_lineage_targets_displayed_version_at_v2(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    note_text, _ = server.tool("note", note_args(repo, base))
    uid = note_text.splitlines()[1].split()[1]
    v1_rel = note_text.splitlines()[0].removeprefix("wrote ")
    v2_id = later_ulid(uid)
    write_v2(base, v1_rel, v2_id)
    text, is_error = server.tool(
        "verify",
        {"id": uid, "evidence": ["re-checked v2"], "repo_root": str(repo), "base": str(base)},
    )
    assert is_error is False
    rel = text.splitlines()[0].removeprefix("wrote ")
    data = load_frontmatter((base / rel).read_text(encoding="utf-8"), rel)
    assert data["targets"] == v2_id
    assert data["targets"] != uid


def test_refute_by_lineage_targets_displayed_version_at_v2(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    note_text, _ = server.tool("note", note_args(repo, base))
    uid = note_text.splitlines()[1].split()[1]
    v1_rel = note_text.splitlines()[0].removeprefix("wrote ")
    v2_id = later_ulid(uid)
    write_v2(base, v1_rel, v2_id)
    text, is_error = server.tool(
        "refute",
        {
            "id": uid,
            "reason": "Displayed version is wrong.",
            "repo_root": str(repo),
            "base": str(base),
        },
    )
    assert is_error is False
    assert "doubt" not in text
    rel = text.splitlines()[0].removeprefix("wrote ")
    data = load_frontmatter((base / rel).read_text(encoding="utf-8"), rel)
    assert data["targets"] == v2_id
    assert data["targets"] != uid


def test_note_statement_round_trips_control_characters(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    statement = 'line one\n---\nline "three"\ttab'
    text, is_error = server.tool(
        "note", note_args(repo, base, statement=statement, anchors=[SYM_A])
    )
    assert is_error is False
    rel = text.splitlines()[0].removeprefix("wrote ")
    raw = (base / rel).read_text(encoding="utf-8")
    assert raw.count("---\n") == 2
    data = load_frontmatter(raw, rel)
    assert data["statement"] == statement
    assert data["summary"] == "Bring-up order: start before stop"
    assert check_base(base).errors == []


def test_rapid_consecutive_notes_monotonic_ulids(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    ids = []
    for _ in range(5):
        text, is_error = server.tool("note", note_args(repo, base))
        assert is_error is False
        ids.append(text.splitlines()[1].split()[1])
    assert len(set(ids)) == len(ids)
    assert all(a < b for a, b in pairwise(ids))
    assert check_base(base).errors == []


def test_server_exit_code_zero_on_eof(server):
    server.ready()
    code, _stderr = server.finish()
    assert code == 0


# --- credential guard in the shared write path (E-WRITE-SECRET) ---

UNANCHORED = {"anchors": None, "unanchored": True, "unanchored_reason": "no anchor applies"}

PEM_BLOCK = (
    "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA7nHzOFytcqT0\n-----END RSA PRIVATE KEY-----"
)

SECRET_STATEMENTS = {
    "pem": PEM_BLOCK,
    "aws": "the client id is AKIAI44QH8DHBEXAMPLE in staging",
    "ghp": "the leaked token was ghp_Az09BcdEfGhIjKlMnOpQrStUvWxz",
    "github_pat": "token github_pat_Az09BcdEfGhIjKlMnOpQrStUvWx123",
    "sk": "key sk-az3BcDeFgHiJkLmNoPqRsTuVwXy012345",
    "xoxb": "bot token xoxb-123456789012-ABCDEFabcdef",
    "assigned": "the config had password=Ht7#kLm2Qx9Zr4Vb8Nc1 written in it",
}


@pytest.mark.parametrize("family", sorted(SECRET_STATEMENTS))
def test_note_refuses_credential_shapes_per_family(server, code_repo, base, family):
    repo, _head = code_repo
    server.ready()
    text, is_error = server.tool(
        "note", note_args(repo, base, statement=SECRET_STATEMENTS[family], **UNANCHORED)
    )
    assert is_error is True, family
    assert "E-WRITE-SECRET" in text, family
    assert "nothing is written" in text, family
    assert not list(base.rglob("*.md")), family


def test_verify_refuses_secret_in_evidence(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    note_text, _ = server.tool("note", note_args(repo, base, **UNANCHORED))
    uid = note_text.splitlines()[1].split()[1]
    text, is_error = server.tool(
        "verify",
        {
            "id": uid,
            "evidence": ["reviewed the auth flow", SECRET_STATEMENTS["ghp"]],
            "repo_root": str(repo),
            "base": str(base),
        },
    )
    assert is_error is True
    assert "E-WRITE-SECRET" in text and "evidence" in text
    assert not list(base.rglob("*.verify.md"))


def test_doubt_refuses_secret_in_reason(server, code_repo, base):
    repo, _head = code_repo
    server.ready()
    note_text, _ = server.tool("note", note_args(repo, base, **UNANCHORED))
    uid = note_text.splitlines()[1].split()[1]
    server.tool(
        "verify", {"id": uid, "evidence": ["ok"], "repo_root": str(repo), "base": str(base)}
    )
    text, is_error = server.tool(
        "doubt",
        {
            "id": uid,
            "reason": SECRET_STATEMENTS["assigned"],
            "repo_root": str(repo),
            "base": str(base),
        },
    )
    assert is_error is True
    assert "E-WRITE-SECRET" in text
    assert not list(base.rglob("*.doubt.md"))


@pytest.mark.parametrize(
    "statement",
    [
        "we hash the password field with bcrypt before storage",
        "the login form has a password field and a token bucket rate limiter",
        "auth uses JWT; set password=abc123 in the test fixture",  # short/single-class value
        "the service reads api_key from process.env at startup",
        "token bucket refills at 10 requests per second",
    ],
)
def test_note_accepts_password_discussion_lookalikes(server, code_repo, base, statement):
    repo, _head = code_repo
    server.ready()
    text, is_error = server.tool("note", note_args(repo, base, statement=statement, **UNANCHORED))
    assert is_error is False, text
    rel = text.splitlines()[0].removeprefix("wrote ")
    assert (base / rel).is_file()
    assert check_base(base).errors == []


def test_write_and_check_refuses_secret_in_summary_directly(tmp_path):
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    data = make_claim("01J8Z3K0000000000000000000", summary=SECRET_STATEMENTS["aws"])
    with pytest.raises(WriteError) as exc:
        write_and_check(base_dir, data)
    assert exc.value.code == "E-WRITE-SECRET"
    assert not list(base_dir.rglob("*.md"))
