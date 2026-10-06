"""`masora hook`: the agent hooks (MASORA_DESIGN.md §10.1, channels 1-2).

Two hooks share the install machinery and the silent-failure discipline:

- **SessionStart** (`session_start`): freshness automation for AUDIT.md's
  operational risk 1 ("silent recall decay") — background fetch + ff-only
  merge of each configured base clone, rebuild of stale indexes within a
  hard wall-clock budget, at most TWO lines of output (the stale summary
  plus the standing usage rule).
- **UserPromptSubmit** (`user_prompt_submit`, Phase 2's primary recall
  channel — the pre-registered evaluation showed the other channels barely
  engage): at every user prompt, FTS the prompt over the already-built
  index and inject the 2-3 most relevant claims with their trust labels,
  BEFORE the agent chooses any tool. Read-only apart from the per-session
  dedup state (the last injected hint's hash, keyed by session_id); the
  hint goes out on the session's first prompt and again only when its
  content changes. A missing or stale index is a SILENT SKIP —
  the SessionStart hook owns rebuilds.

At agent session start, the SessionStart hook — IN THE BACKGROUND, with
SILENT FAILURE (every exception swallowed, exit 0 always, never blocking the
session):

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
3. prints at most TWO lines — the stale-lineage summary (count + the worst
   staleness reason class) plus the standing usage rule — or just the usage
   rule when everything is fresh, and nothing at all when nothing is
   configured.

Installation (`masora hook install`) reuses the skill-install pattern: the
hook scripts ship inside the package (`masora/hooks/`, one canonical copy
each) and are written into every detected agent home. Claude Code also gets
BOTH hook entries (SessionStart + UserPromptSubmit) merged into
`~/.claude/settings.json`; for opencode the registration cannot
be written safely from here (its plugin format is JavaScript), so the manual
config snippet is printed instead — silent best-effort, never a hard failure.
Re-running install overwrites — that IS the update path.
"""

from __future__ import annotations

import hashlib
import json
import shlex
import sqlite3
import sys
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
from .write import auto_base

# Hook caps (MASORA_DESIGN.md §10.1): the hook borrows the session's machine,
# never its attention — one line of output maximum, a hard wall-clock budget
# on index rebuilds, short git timeouts, silent failure everywhere. Raising
# these is a §10.1 decision, not a local tweak.
REBUILD_BUDGET_S = 20.0
HOOK_GIT_TIMEOUT_S = 30

SCRIPT_REL = ".claude/hooks/masora_session_start.py"
PROMPT_SCRIPT_REL = ".claude/hooks/masora_user_prompt_submit.py"
OPENCODE_SCRIPT_REL = ".config/opencode/hooks/masora_session_start.py"
SETTINGS_REL = ".claude/settings.json"
HOOK_MARKER = "masora_session_start.py"
PROMPT_HOOK_MARKER = "masora_user_prompt_submit.py"

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
    """The packaged SessionStart hook script — the single canonical copy."""
    return (resources.files("masora") / "hooks/session_start.py").read_text(encoding="utf-8")


def prompt_script_text() -> str:
    """The packaged UserPromptSubmit hook script — the single canonical copy."""
    return (resources.files("masora") / "hooks/user_prompt_submit.py").read_text(encoding="utf-8")


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
    """Write the scripts (and, for claude, register both hooks); print one
    installed/updated line per artifact, idempotently."""
    text = script_text()
    script_rel = SCRIPT_REL if name == "claude" else OPENCODE_SCRIPT_REL
    target = home / script_rel
    existed = target.is_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"{'updated' if existed else 'installed'}: {target}")
    if name == "claude":
        prompt_target = home / PROMPT_SCRIPT_REL
        prompt_existed = prompt_target.is_file()
        prompt_target.parent.mkdir(parents=True, exist_ok=True)
        prompt_target.write_text(prompt_script_text(), encoding="utf-8")
        print(f"{'updated' if prompt_existed else 'installed'}: {prompt_target}")
        _register_claude(home / SETTINGS_REL, target, prompt_target)
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


def _hook_command(script: Path) -> str:
    """The registration command: the INTERPRETER install ran under, quoted —
    a bare `python3` may lack the masora package entirely (system python) or
    hold a stale copy (an old uv tool env), and the hook would then silently
    never run. `masora hook install` always executes with current code
    importable, so its own sys.executable is the one faithful interpreter."""
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"


def _register_claude(settings_path: Path, script: Path, prompt_script: Path) -> None:
    """Merge BOTH hook entries (SessionStart + UserPromptSubmit) into Claude
    Code's settings.json.

    Best-effort and idempotent per event: an entry whose command names our
    script is never duplicated — and a PRIOR masora entry (old registration
    shape, stale interpreter) is REPLACED, never left to shadow the fresh
    one; an unreadable/unwritable settings file degrades to the printed
    manual snippet — the hook install never breaks the agent's own
    configuration.
    """
    registrations = [
        ("SessionStart", HOOK_MARKER, script),
        ("UserPromptSubmit", PROMPT_HOOK_MARKER, prompt_script),
    ]
    data: dict = {}
    existed = settings_path.is_file()
    if existed:
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("settings.json is not a JSON object")  # noqa: TRY004
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"could not edit {settings_path} ({exc}) — manual snippet:")
            _print_manual_snippet(registrations)
            return
    hooks = data.setdefault("hooks", {})
    registered: list[str] = []
    for event, marker, command_path in registrations:
        entry = {
            "matcher": "",
            "hooks": [{"type": "command", "command": _hook_command(command_path)}],
        }
        events = hooks.setdefault(event, [])
        if not isinstance(events, list):
            print(f"could not edit {settings_path} (hooks.{event} is not a list) — manual snippet:")
            _print_manual_snippet(registrations)
            return
        ours = [e for e in events if isinstance(e, dict) and marker in json.dumps(e)]
        if ours:
            events = [e for e in events if e not in ours]
            if len(ours) == 1 and ours[0] == entry:
                events.append(entry)
                print(f"updated: {settings_path} ({event} entry already registered)")
                hooks[event] = events
                continue
            events.append(entry)
            hooks[event] = events
            registered.append(event)
            continue
        events.append(entry)
        registered.append(event)
    if not registered:
        return
    try:
        tmp = settings_path.parent / f".settings.json.masora-{id(data)}"
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp.replace(settings_path)
    except OSError as exc:
        print(f"could not write {settings_path} ({exc}) — manual snippet:")
        _print_manual_snippet(registrations)
        return
    print(f"{'updated' if existed else 'installed'}: {settings_path} ({', '.join(registered)})")


def _print_manual_snippet(
    registrations: list[tuple[str, str, Path]],
) -> None:
    snippet = {
        "hooks": {
            event: [{"matcher": "", "hooks": [{"type": "command", "command": _hook_command(path)}]}]
            for event, _marker, path in registrations
        }
    }
    print(json.dumps(snippet, indent=2))


# --- The hook's background work (session_start and its helpers) ---


def session_start() -> int:
    """The hook entry point: NEVER raises, ALWAYS exits 0, at most two lines
    on stdout (the stale summary + the standing usage rule). Every per-base
    failure is swallowed — a broken base must cost the session nothing (the
    hook is best-effort by §10.1)."""
    try:
        summary, configured = _run_quiet()
    except Exception:  # noqa: BLE001 — the hook must never fail a session start
        return 0
    # Two lines max: the stale-lineage summary (only when something is
    # stale) and the standing usage rule (whenever masora is configured —
    # this is the standing line the prompt hook deliberately never nags
    # with). Nothing configured (no/garbage config) prints NOTHING.
    lines = [line for line in (summary, SESSION_USAGE_LINE if configured else None) if line]
    for line in lines:
        try:
            print(line)
        except Exception:  # noqa: BLE001, S110 — even a broken stdout is silent
            pass
    return 0


def _run_quiet() -> tuple[str | None, bool]:
    """The (stale summary, bases-configured) pair — the summary is None when
    every index is fresh; `configured` is False only when no base resolves
    (no config, garbage config, no matching base dir)."""
    bases = _configured_bases()
    if not bases:
        return None, False
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
        return None, True
    return (
        f"masora: {stale_total} stale lineage(s)" + (f", worst reason: {worst}" if worst else ""),
        True,
    )


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


# --- The prompt-time recall hook (UserPromptSubmit: FTS over the prompt) ---


# Caps (MASORA_DESIGN.md §10.1): prompt-time recall must cost the session
# almost nothing — a hard wall-clock budget on the whole hook, short prompts
# skipped (commands and pleasantries — "continue", "thanks" — are not
# queries), at most 3 claim lines inside a ~100-token envelope. The bm25
# floor is the precision guard: prompt recall matches ANY prompt term (an
# AND of a long natural-language prompt matches nothing), so lexical false
# positives are the documented risk; FTS5's bm25 ranks better matches MORE
# NEGATIVE — a single informative-term match ranks ≈ -0.7 and below, a
# stopword/prefix-only hit ranks ≈ 0. The floor keeps the former, drops the
# latter. Raising any of these is a §10.1 decision, not a local tweak.
PROMPT_BUDGET_S = 2.0
PROMPT_MIN_CHARS = 25
PROMPT_MIN_WORDS = 4
PROMPT_MAX_CLAIMS = 3
PROMPT_TOKEN_BUDGET = 100
PROMPT_RANK_FLOOR = -0.5

# The WITH-condition usage lines (docs/EVALUATION.md amendment 2026-10-04):
# the recalled claims ship WITH the instruction that makes the deeper
# channels engage. At prompt time, when claims inject, the block is prefixed
# by ONE line; when nothing matches nothing prints (no nagging — the
# SessionStart hook carries the standing line instead). The SessionStart
# summary is at most TWO lines: the stale summary plus the standing usage
# rule (docs/AGENT_INSTRUCTIONS.md). Changing the wording is an evaluation-
# protocol decision, not a local tweak — the tests pin both lines.
PROMPT_USAGE_LINE = (
    "masora: recalled knowledge for this prompt — search/explain go deeper"
    " (the masora MCP tools); cppgraph owns code structure."
)
SESSION_USAGE_LINE = (
    "masora: recall recorded knowledge with the masora search / explain MCP"
    ' tools before investigating "what happens when X" questions.'
)

# Better status first when selecting the top claims (current knowledge
# before stale; a strongly-matching refuted lineage is negative knowledge —
# still worth injecting, but only when no current claim fills the cap).
_PROMPT_STATUS_PREF = {"current": 0, "restored": 0, "stale": 1, "none": 2}


def user_prompt_submit(
    prompt: str,
    cwd: Path,
    session_id: str | None = None,
    state_dir: Path | None = None,
) -> str | None:
    """The UserPromptSubmit hook: FTS the prompt, render the top claims.

    Resolves the base from the prompt's cwd (the `auto_base` resolution —
    mappings on origin, then `default_base`; nothing matched = silent skip),
    opens the EXISTING index (missing or stale = silent skip — the index is
    never built here, the SessionStart hook owns rebuilds), searches the
    content/questions/keywords union with the safe expression builder and
    renders at most `PROMPT_MAX_CLAIMS` lines — one per lineage, statuses
    per the §6 trust matrix, a refuted lineage as the `masora NOT:` form —
    inside the `PROMPT_TOKEN_BUDGET` envelope (the budget always wins over
    the claim count, but at least one claim renders whenever any matched).

    Per-session dedup: with a `session_id` (Claude Code hands one in the
    stdin payload), the hint goes out only on the session's FIRST prompt and
    again whenever its CONTENT changes (a background pull brought fresh
    drift) — an identical hint on a later turn prints nothing. The last
    injected hint's hash lives in a small per-session file under the masora
    state dir; `state_dir` overrides its directory (tests). The state is
    BEST-EFFORT and fails OPEN: any error reading or writing it degrades to
    injecting, never to silence and never to a crash.

    Silent-failure discipline: ANY problem (no base, unreadable config,
    missing/corrupt index, FTS error, budget spent) returns None — the hook
    never raises, never writes anything but the dedup state (read-only like
    `masora facts` otherwise).
    """
    if len(prompt) < PROMPT_MIN_CHARS or len(prompt.split()) < PROMPT_MIN_WORDS:
        return None
    try:
        claims = _prompt_injection(prompt, cwd)
    except Exception:  # noqa: BLE001 — the hook must never fail a prompt
        return None
    # The usage line rides ONLY with actual claims: nothing matched (or the
    # hook skipped) prints nothing — the standing instruction belongs to the
    # SessionStart summary, not to every prompt.
    if claims is None:
        return None
    text = f"{PROMPT_USAGE_LINE}\n{claims}"
    return _dedup_hint(text, session_id, state_dir)


def _hint_state_path(session_id: str, state_dir: Path | None) -> Path:
    """The per-session state file: the session_id (it can carry arbitrary
    characters) is hashed into a flat filename under the masora state dir —
    the same resolution pattern as the other user-side state (update-check),
    MASORA_HOME-aware, `state_dir` overriding for tests."""
    if state_dir is not None:
        return state_dir / f"{hashlib.sha256(session_id.encode('utf-8')).hexdigest()}.hint"
    home = config.masora_home()
    root = (
        (home / "hook-state")
        if home is not None
        else Path.home() / ".local" / "share" / "masora" / "hook-state"
    )
    return root / f"{hashlib.sha256(session_id.encode('utf-8')).hexdigest()}.hint"


def _dedup_hint(text: str, session_id: str | None, state_dir: Path | None) -> str | None:
    """Inject on the session's first prompt, then only when the hint's
    CONTENT changed since the last injection (a background pull refreshed
    the drift). Same content on a later turn → nothing. The state file
    stores the sha256 of the exact hint string; BEST-EFFORT and fail-open —
    any error (missing dir, corrupt file, unwritable path) defaults to
    INJECTING, and the hook's exit behavior is never touched."""
    if not session_id:
        return text
    try:
        path = _hint_state_path(session_id, state_dir)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        try:
            stored = path.read_text(encoding="utf-8").strip()
        except OSError:
            stored = None
        if stored == digest:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(digest + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001 — state is best-effort; fail OPEN to injecting
        return text
    return text


def _prompt_injection(prompt: str, cwd: Path) -> str | None:
    deadline = time.monotonic() + PROMPT_BUDGET_S
    try:
        base = auto_base(cwd)
    except Exception:  # noqa: BLE001 — matched-but-broken config is silent here too
        return None
    if base is None:
        return None
    hits: list[index.SearchHit] = []
    try:
        index_dir = index.index_dir_for(base)
        if index_dir.is_dir():
            for db in sorted(index_dir.glob("*.db")):
                if time.monotonic() >= deadline:
                    return None
                try:
                    hits.extend(index.search_index_capped(db, _prompt_query(prompt))[0])
                except index.IndexingError:
                    continue
    except OSError:
        return None
    selected = _select_prompt_hits(hits)
    if not selected:
        return None
    lines: list[str] = []
    tokens = 0
    for hit in selected:
        line = _prompt_line(hit)
        cost = len(line) // 4 + 1
        if lines and tokens + cost > PROMPT_TOKEN_BUDGET:
            break
        lines.append(line)
        tokens += cost
    return "\n".join(lines)


def _prompt_query(prompt: str) -> str:
    """The prompt as an ANY-term query for the safe FTS builder: the builder
    ANDs the terms of one group, and a long natural-language prompt under
    AND semantics matches nothing — recall here must be OR-of-terms, with
    precision recovered by the bm25 floor plus the top-3 cut. Reuses the
    builder's own tokenizer and term cap."""
    tokens = list(dict.fromkeys(index._TERM_RE.findall(prompt)))
    return " OR ".join(tokens[: index.MAX_QUERY_TERMS])


def _select_prompt_hits(hits: list[index.SearchHit]) -> list[index.SearchHit]:
    """The bm25 floor, then top claims: dedup by lineage, better status
    first, best rank within a status."""
    ranked = [hit for hit in hits if hit.rank <= PROMPT_RANK_FLOOR]
    ranked.sort(key=lambda hit: (_PROMPT_STATUS_PREF.get(hit.resolution, 3), hit.rank))
    selected: list[index.SearchHit] = []
    seen: set[str] = set()
    for hit in ranked:
        if hit.lineage in seen:
            continue
        seen.add(hit.lineage)
        selected.append(hit)
        if len(selected) == PROMPT_MAX_CLAIMS:
            break
    return selected


def _prompt_line(hit: index.SearchHit) -> str:
    """One claim line, statuses as LABELS per the §6 trust matrix (docs/
    CPPGRAPH_INTEGRATION.md §6): a refuted lineage is negative knowledge —
    the `masora NOT:` form, never advice; `unverified` renders nothing (the
    absence of a verify is not evidence). SearchHit carries no `effort`, so
    the `low-effort` interpretive token never renders here (it is pinned to
    `verified(llm)` with `effort: low` only)."""
    if hit.resolution == "none" or hit.refuted:
        return f"masora NOT: {hit.summary} [refuted]"
    labels = [hit.resolution]
    if hit.suspect:
        labels.append("suspect — re-check")
    if hit.doubted:
        labels.append("doubted")
    if hit.pending:
        labels.append("pending")
    if hit.unanchored:
        labels.append("unanchored")
    if hit.off_version:
        labels.append("off-version")
    if hit.unknown and hit.resolution != "unknown":
        labels.append("unknown")
    if hit.verification and hit.verification != "unverified":
        labels.append(hit.verification)
    return f"masora: {hit.summary} [{', '.join(labels)}]"
